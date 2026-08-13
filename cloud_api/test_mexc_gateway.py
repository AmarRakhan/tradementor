import hashlib
import hmac
import json

import httpx

from mexc_gateway import (
    MexcApiError, MexcCanaryUncertain, MexcClient, MexcCredentials,
    canary_existing_action, normalized_positions, place_canary_once, place_order_once, query_string, signature,
    usdt_asset, volume_for_notional,
)


CREDS = MexcCredentials("access", "secret")


def test_signature_matches_documented_hmac_rule():
    target = b"access1700000000000symbol=BTC_USDT"
    expected = hmac.new(b"secret", target, hashlib.sha256).hexdigest()
    assert signature(CREDS, 1700000000000, "symbol=BTC_USDT") == expected


def test_query_string_is_sorted_and_omits_null():
    assert query_string({"symbol": "BTC_USDT", "positionId": None, "a": 2}) == "a=2&symbol=BTC_USDT"


def test_private_get_uses_signature_headers_without_exposing_secret():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == "access"
        assert request.headers["request-time"] == "1700000000000"
        assert request.headers["signature"] == signature(CREDS, 1700000000000, "")
        assert "secret" not in str(request.url)
        return httpx.Response(200, json={"success": True, "code": 0, "data": [{"currency": "USDT", "equity": 125}]})

    client = MexcClient(CREDS, transport=httpx.MockTransport(handler), clock_ms=lambda: 1700000000000)
    assert usdt_asset(client.assets())["equity"] == 125


def test_open_orders_uses_documented_symbol_route():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/private/order/list/open_orders/BTC_USDT"
        return httpx.Response(200, json={"success": True, "code": 0, "data": [{"orderId": "1"}]})
    client = MexcClient(CREDS, transport=httpx.MockTransport(handler), clock_ms=lambda: 1700000000000)
    assert client.open_orders("BTC_USDT") == [{"orderId": "1"}]


def test_post_signature_uses_exact_compact_json():
    body = {"symbol": "BTC_USDT", "vol": 1, "side": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        exact = json.dumps(body, separators=(",", ":"))
        assert request.content.decode() == exact
        assert request.headers["signature"] == signature(CREDS, 1700000000000, exact)
        return httpx.Response(200, json={"success": True, "code": 0, "data": "order-id"})

    client = MexcClient(CREDS, transport=httpx.MockTransport(handler), clock_ms=lambda: 1700000000000)
    assert client._private("POST", "/unused-test-endpoint", body) == "order-id"


def test_canary_volume_never_exceeds_confirmed_notional():
    volume, actual = volume_for_notional(8.50, 64_900.0, {"contractSize": 0.0001, "minVol": 1, "volUnit": 1})
    assert volume == 1
    assert actual == 6.49
    assert actual <= 8.50


def test_market_canary_payload_can_use_fixed_cross_200_profile():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert request.url.path == "/api/v1/private/order/create"
        assert body == {
            "symbol": "BTC_USDT",
            "price": 0,
            "vol": 1,
            "leverage": 200,
            "side": 1,
            "type": 5,
            "openType": 2,
            "externalOid": "tmc_test",
            "positionMode": 1,
        }
        return httpx.Response(200, json={"success": True, "code": 0, "data": {"orderId": "order-1"}})

    client = MexcClient(CREDS, transport=httpx.MockTransport(handler), clock_ms=lambda: 1700000000000)
    result = client.place_market_order(
        symbol="BTC_USDT", volume=1, side=1, leverage=200,
        external_oid="tmc_test", open_type=2,
    )
    assert result["orderId"] == "order-1"


def test_cross_leverage_is_explicitly_fixed_for_both_position_sides():
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        calls.append(body)
        return httpx.Response(200, json={"success": True, "code": 0, "data": True})
    client = MexcClient(CREDS, transport=httpx.MockTransport(handler), clock_ms=lambda: 1700000000000)
    assert client.change_leverage(symbol="BTC_USDT", position_type=1, leverage=200, open_type=2)
    assert client.change_leverage(symbol="BTC_USDT", position_type=2, leverage=200, open_type=2)
    assert calls == [
        {"leverage": 200, "openType": 2, "symbol": "BTC_USDT", "positionType": 1},
        {"leverage": 200, "openType": 2, "symbol": "BTC_USDT", "positionType": 2},
    ]


def test_canary_existing_status_prevents_duplicate_submission():
    assert canary_existing_action("accepted") == "replay"
    assert canary_existing_action("filled") == "replay"
    assert canary_existing_action("pending") == "replay"
    assert canary_existing_action("uncertain") == "block"
    assert canary_existing_action("rejected") == "proceed"


def test_canary_submits_exactly_once_on_success():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"success": True, "code": 0, "data": {"orderId": "order-1"}})

    client = MexcClient(CREDS, transport=httpx.MockTransport(handler), clock_ms=lambda: 1700000000000)
    result, recovered = place_canary_once(client, symbol="BTC_USDT", volume=1, external_oid="tmc_once")
    assert result["orderId"] == "order-1"
    assert recovered is False
    assert calls == [("POST", "/api/v1/private/order/create")]


def test_canary_recovers_after_ambiguous_submit_without_second_post():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json={"success": False, "code": 999, "message": "timeout"})
        return httpx.Response(200, json={"success": True, "code": 0, "data": {"orderId": "recovered-1"}})

    client = MexcClient(CREDS, transport=httpx.MockTransport(handler), clock_ms=lambda: 1700000000000)
    result, recovered = place_canary_once(client, symbol="BTC_USDT", volume=1, external_oid="tmc_recover")
    assert result["orderId"] == "recovered-1"
    assert recovered is True
    assert sum(method == "POST" for method, _ in calls) == 1
    assert sum(method == "GET" for method, _ in calls) == 1


def test_canary_ambiguous_without_recovery_is_blocked_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"success": False, "code": 999, "message": "unknown"})

    client = MexcClient(CREDS, transport=httpx.MockTransport(handler), clock_ms=lambda: 1700000000000)
    try:
        place_canary_once(client, symbol="BTC_USDT", volume=1, external_oid="tmc_uncertain")
        assert False, "uncertain submission must be blocked"
    except MexcCanaryUncertain:
        pass
    assert sum(method == "POST" for method, _ in calls) == 1
    assert sum(method == "GET" for method, _ in calls) == 1


def test_generic_automation_order_is_always_cross_200_and_supports_close_side():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content.decode())
            assert body["side"] == 4
            assert body["leverage"] == 200
            assert body["openType"] == 2
            assert body["positionId"] == 77
            return httpx.Response(200, json={"success": True, "code": 0, "data": {"orderId": "close-1"}})
        raise AssertionError("unexpected request")
    client = MexcClient(CREDS, transport=httpx.MockTransport(handler), clock_ms=lambda: 1700000000000)
    result, recovered = place_order_once(client, symbol="BTC_USDT", volume=1, side=4, external_oid="tm_close", position_id=77)
    assert result["orderId"] == "close-1"
    assert recovered is False


def test_candles_aggregate_three_one_minute_rows_into_one_three_minute_candle():
    def handler(request: httpx.Request) -> httpx.Response:
        data = {"time": [0, 60, 120, 180, 240, 300], "open": [10, 11, 12, 13, 14, 15], "high": [12, 13, 14, 15, 16, 17], "low": [9, 10, 11, 12, 13, 14], "close": [11, 12, 13, 14, 15, 16], "vol": [1, 2, 3, 4, 5, 6]}
        return httpx.Response(200, json={"success": True, "code": 0, "data": data})
    client = MexcClient(CREDS, transport=httpx.MockTransport(handler), clock_ms=lambda: 1700000000000)
    candles = client.candles("BTC_USDT", "3m", 2)
    assert len(candles) == 2
    assert candles[0] == {"time": 0, "open": 10.0, "high": 14.0, "low": 9.0, "close": 13.0, "volume": 6.0}


def test_normalized_isolated_long_position_uses_contract_notional():
    normalized = normalized_positions([{
        "positionId": 42,
        "symbol": "BTC_USDT",
        "positionType": 1,
        "openType": 1,
        "holdVol": 1,
        "holdAvgPrice": 64_900,
        "im": 6.49,
        "unrealised": 0.03,
        "liquidatePrice": 200,
        "leverage": 1,
    }], mark_price=65_000, contract={
        "contractSize": 0.0001, "maintenanceMarginRate": 0.001,
        "liquidationFeeRate": 0.0004,
    })
    assert len(normalized) == 1
    result = normalized[0]
    assert result["positionId"] == "42"
    assert result["side"] == "long"
    assert result["isolated"] is True
    assert result["notionalUsd"] == 6.5
    assert result["marginUsd"] == 6.49
    assert result["unrealizedPnl"] == 0.03
    assert result["maintenanceMarginRate"] == 0.001
    assert result["liquidationFeeRate"] == 0.0004
    assert abs(result["marginRatioPercent"] - 0.1395705521) < 0.00001


def test_normalized_short_position_and_empty_rows():
    normalized = normalized_positions([
        {"positionType": 2, "openType": 2, "holdVol": 2, "openAvgPrice": 100, "leverage": 10},
        {"positionType": 1, "holdVol": 0},
    ], mark_price=90, contract={"contractSize": 0.01})
    assert len(normalized) == 1
    assert normalized[0]["side"] == "short"
    assert normalized[0]["isolated"] is False
    assert normalized[0]["notionalUsd"] == 1.8


def test_cross_position_margin_ratio_uses_shared_account_equity():
    normalized = normalized_positions([{
        "positionType": 1, "openType": 2, "holdVol": 1,
        "holdAvgPrice": 65_000, "im": 0.0325, "unrealised": 0,
        "leverage": 200,
    }], mark_price=65_000, contract={
        "contractSize": 0.0001, "maintenanceMarginRate": 0.001,
        "liquidationFeeRate": 0.0004,
    }, account_equity=125.0)
    result = normalized[0]
    assert result["isolated"] is False
    assert result["leverage"] == 200
    assert abs(result["marginRatioPercent"] - 0.00728) < 0.000001


def test_margin_ratio_moves_toward_one_hundred_as_margin_is_consumed():
    contract = {"contractSize": 0.0001, "maintenanceMarginRate": 0.001, "liquidationFeeRate": 0.0004}
    safe = normalized_positions([{
        "positionType": 1, "openType": 1, "holdVol": 1, "holdAvgPrice": 65_000,
        "im": 6.5, "unrealised": 0, "leverage": 1,
    }], mark_price=65_000, contract=contract)[0]
    danger = normalized_positions([{
        "positionType": 1, "openType": 1, "holdVol": 1, "holdAvgPrice": 65_000,
        "im": 6.5, "unrealised": -6.4909, "leverage": 1,
    }], mark_price=65_000, contract=contract)[0]
    assert safe["marginRatioPercent"] < 1.0
    assert abs(danger["marginRatioPercent"] - 100.0) < 0.000001
