from decimal import Decimal

import httpx
import pytest

from aster_gateway import (
    AsterAutomationConfig,
    AsterApiError,
    AsterV3Client,
    AsterOrderIntent,
    AsterSubmissionUncertain,
    AsterValidationError,
    ContractRules,
    LeverageBracket,
    PositionSide,
    MonotonicNonce,
    build_hedge_order_payload,
    classify_submission,
    maximum_allowed_leverage,
    stream_event_is_newer,
)


def rules():
    return ContractRules.from_exchange_info({
        "symbol": "BTCUSDT",
        "filters": [
            {"filterType": "PRICE_FILTER", "minPrice": "0.1", "maxPrice": "1000000", "tickSize": "0.1"},
            {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
            {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "10", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
        ],
    })


def test_aster_is_off_and_paper_by_default():
    config = AsterAutomationConfig()
    assert config.enabled is False
    assert config.mode == "paper"
    assert config.can_submit_live() is False


def test_contract_filters_round_down_without_exceeding_requested_quantity():
    quantity = rules().market_quantity("0.00199", "65000")
    assert quantity == Decimal("0.001")
    assert quantity <= Decimal("0.00199")


def test_minimum_notional_and_quantity_are_enforced_before_order_creation():
    with pytest.raises(AsterValidationError):
        rules().market_quantity("0.0009", "65000")


def test_dynamic_leverage_uses_exchange_bracket_for_actual_notional():
    brackets = [
        LeverageBracket(Decimal("0"), Decimal("10000"), 75, Decimal("0.0065")),
        LeverageBracket(Decimal("10000"), Decimal("50000"), 25, Decimal("0.01")),
    ]
    assert maximum_allowed_leverage(9000, brackets) == 75
    assert maximum_allowed_leverage(12000, brackets) == 25


def test_open_long_payload_is_explicit_and_omits_reduce_only_in_hedge_mode():
    intent = AsterOrderIntent("tm-open-long-1", "btcusdt", PositionSide.LONG, Decimal("0.01"), "OPEN")
    payload = build_hedge_order_payload(intent, hedge_mode_confirmed=True, risk_approved=True)
    assert payload == {
        "symbol": "BTCUSDT", "side": "BUY", "positionSide": "LONG", "type": "MARKET",
        "quantity": "0.01", "newClientOrderId": "tm-open-long-1",
    }
    assert "reduceOnly" not in payload


def test_close_short_uses_buy_short_and_remains_available_when_risk_gate_is_closed():
    intent = AsterOrderIntent("tm-close-short-1", "BTCUSDT", PositionSide.SHORT, Decimal("0.02"), "CLOSE")
    payload = build_hedge_order_payload(intent, hedge_mode_confirmed=True, risk_approved=False)
    assert payload["side"] == "BUY"
    assert payload["positionSide"] == "SHORT"


def test_risk_increasing_order_is_blocked_without_both_gates():
    intent = AsterOrderIntent("tm-open-short-1", "BTCUSDT", PositionSide.SHORT, Decimal("0.02"), "OPEN")
    with pytest.raises(AsterValidationError):
        build_hedge_order_payload(intent, hedge_mode_confirmed=False, risk_approved=True)
    with pytest.raises(AsterValidationError):
        build_hedge_order_payload(intent, hedge_mode_confirmed=True, risk_approved=False)


def test_503_is_uncertain_and_never_classified_as_safe_retry():
    with pytest.raises(AsterSubmissionUncertain):
        classify_submission(503, None)
    assert classify_submission(200, {"orderId": 123}) == "accepted"


def test_out_of_order_user_stream_events_are_ignored():
    assert stream_event_is_newer(1000, {"E": 1001}) is True
    assert stream_event_is_newer(1000, {"E": 999}) is False
    assert stream_event_is_newer(1000, {"E": 1000}) is False


def test_nonce_is_strictly_monotonic_even_when_clock_does_not_move():
    nonce = MonotonicNonce(lambda: 123)
    assert [nonce.next(), nonce.next(), nonce.next()] == [123, 124, 125]


def test_signed_read_uses_exact_encoded_message_and_never_exposes_credentials():
    signed_messages = []

    def sign(message: str) -> str:
        signed_messages.append(message)
        return "signature"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/fapi/v3/positionSide/dual"
        assert "signer=0xagent" in request.url.query.decode()
        assert "signature=signature" in request.url.query.decode()
        return httpx.Response(200, json={"dualSidePosition": True})

    client = AsterV3Client(
        signer_address="0xagent", sign_message=sign,
        transport=httpx.MockTransport(handler), nonce=MonotonicNonce(lambda: 1700000000000000),
    )
    assert client.position_mode() is True
    assert signed_messages == ["nonce=1700000000000000&signer=0xagent"]


def test_public_ticker_read_never_signs_or_submits_an_order():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=[{"symbol": "BTCUSDT", "price": "65000"}])

    client = AsterV3Client(
        signer_address="0xagent", sign_message=lambda _: (_ for _ in ()).throw(AssertionError("must not sign")),
        transport=httpx.MockTransport(handler),
    )
    assert client.ticker_prices()[0]["price"] == "65000"
    assert calls == [("GET", "/fapi/v3/ticker/price")]


def test_live_submission_requires_three_explicit_authorization_layers():
    intent = AsterOrderIntent("tm-open-long-2", "BTCUSDT", PositionSide.LONG, Decimal("0.01"), "OPEN")
    client = AsterV3Client(signer_address="0xagent", sign_message=lambda _: "sig")
    with pytest.raises(AsterValidationError):
        client.submit_order_once(
            intent, config=AsterAutomationConfig(enabled=True, mode="live"), confirm=True,
            hedge_mode_confirmed=True, risk_approved=True,
        )


def test_503_recovers_by_client_order_id_without_second_post():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(503, json={"code": -1000, "msg": "unknown"})
        return httpx.Response(200, json={"orderId": 77, "status": "FILLED"})

    client = AsterV3Client(
        signer_address="0xagent", sign_message=lambda _: "sig",
        transport=httpx.MockTransport(handler), nonce=MonotonicNonce(lambda: 1700000000000000),
        live_authorized=True,
    )
    intent = AsterOrderIntent("tm-open-long-3", "BTCUSDT", PositionSide.LONG, Decimal("0.01"), "OPEN")
    result, recovered = client.submit_order_once(
        intent, config=AsterAutomationConfig(enabled=True, mode="live"), confirm=True,
        hedge_mode_confirmed=True, risk_approved=True,
    )
    assert result["orderId"] == 77
    assert recovered is True
    assert calls == [("POST", "/fapi/v3/order"), ("GET", "/fapi/v3/order")]


def test_margin_and_leverage_configuration_are_signed_once():
    seen = []
    def handler(request: httpx.Request):
        seen.append((request.url.path, request.content.decode()))
        return httpx.Response(200, json={"ok": True})
    client = AsterV3Client(signer_address="0xagent", sign_message=lambda _: "sig",
                           transport=httpx.MockTransport(handler))
    client.change_margin_type("btcusdt", "crossed")
    client.change_leverage("btcusdt", 200)
    assert [item[0] for item in seen] == ["/fapi/v3/marginType", "/fapi/v3/leverage"]
    assert "marginType=CROSSED" in seen[0][1]
    assert "leverage=200" in seen[1][1]


def test_strategy2_recovery_reads_use_official_v3_endpoints_and_never_write():
    seen = []
    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, request.url.query.decode()))
        return httpx.Response(200, json=[])
    client = AsterV3Client(signer_address="0xagent", sign_message=lambda _: "sig",
                           transport=httpx.MockTransport(handler))
    client.all_orders("btcusdt", limit=25)
    client.user_trades("btcusdt", from_id=10, limit=50)
    client.income_history(symbol="btcusdt", income_type="funding_fee", limit=20)
    assert [(x[0], x[1]) for x in seen] == [
        ("GET", "/fapi/v3/allOrders"), ("GET", "/fapi/v3/userTrades"),
        ("GET", "/fapi/v3/income"),
    ]
    assert "symbol=BTCUSDT" in seen[0][2] and "limit=25" in seen[0][2]
    assert "fromId=10" in seen[1][2]
    assert "incomeType=FUNDING_FEE" in seen[2][2]


def test_fill_history_rejects_ambiguous_cursor_and_time_window():
    client = AsterV3Client(signer_address="0xagent", sign_message=lambda _: "sig")
    with pytest.raises(AsterValidationError):
        client.user_trades("BTCUSDT", from_id=1, start_time=2)


def test_history_reads_reject_malformed_records_instead_of_treating_them_as_empty():
    def handler(request: httpx.Request):
        return httpx.Response(200, json=[{"id": 1}, None])
    client = AsterV3Client(signer_address="0xagent", sign_message=lambda _: "sig",
                           transport=httpx.MockTransport(handler))
    with pytest.raises(AsterApiError):
        client.user_trades("BTCUSDT")
    with pytest.raises(AsterApiError):
        client.income_history(symbol="BTCUSDT")
