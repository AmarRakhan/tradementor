from pathlib import Path

from aster_gateway import AsterOrderIntent, PositionSide, build_hedge_order_payload
from decimal import Decimal


def test_manual_close_payload_cannot_reverse_long_or_short_hedge_leg():
    long_payload = build_hedge_order_payload(
        AsterOrderIntent("manual-close-long", "BTCUSDT", PositionSide.LONG, Decimal("1.25"), "CLOSE"),
        hedge_mode_confirmed=True, risk_approved=False,
    )
    short_payload = build_hedge_order_payload(
        AsterOrderIntent("manual-close-short", "BTCUSDT", PositionSide.SHORT, Decimal("2.5"), "CLOSE"),
        hedge_mode_confirmed=True, risk_approved=False,
    )
    assert (long_payload["side"], long_payload["positionSide"], long_payload["quantity"]) == ("SELL", "LONG", "1.25")
    assert (short_payload["side"], short_payload["positionSide"], short_payload["quantity"]) == ("BUY", "SHORT", "2.5")


def test_manual_close_route_has_idempotency_and_fresh_position_fail_closed_guards():
    source = Path(__file__).with_name("main.py").read_text()
    route = source[source.index('@app.post("/v1/me/aster/positions/{symbol}/close")'):source.index('@app.post("/v1/me/aster/simulate")')]
    assert "intent_ref.create" in route
    assert "AlreadyExists" in route
    assert "client.position_risk()" in route
    assert "expected_quantity" in route
    assert "manual_loss_confirmation=True" in route
    assert "expected_remaining" in route
    assert "remaining_quantity" in route
    assert "er wordt niet opnieuw besteld" in route


def test_manual_close_route_supports_only_the_four_safe_partial_percentages():
    source = Path(__file__).with_name("main.py").read_text()
    request_model = source[source.index("class AsterManualCloseRequest"):source.index("class AsterProfitableCloseRequest")]
    route = source[source.index('@app.post("/v1/me/aster/positions/{symbol}/close")'):source.index('@app.post("/v1/me/aster/simulate")')]

    assert "percentage: int = Field(default=100, ge=25, le=100)" in request_model
    assert "request.percentage not in ALLOWED_CLOSE_PERCENTAGES" in route
    assert "close_size(live_quantity, request.percentage)" in route
    assert "rules.market_quantity" in route
    assert "request.percentage != 100" in route
    assert '"percentage": request.percentage' in route
    assert '"remainingSize": remaining_quantity' in route


def test_manual_partial_close_explicitly_releases_auto_hedge_before_submit():
    source = Path(__file__).with_name("main.py").read_text()
    route = source[source.index('@app.post("/v1/me/aster/positions/{symbol}/close")'):source.index('@app.post("/v1/me/aster/simulate")')]

    release = route.index("_begin_position_loss_auto_hedge_manual_release(")
    hedge_guard = route.index("require_auto_hedge_close_allowed(")
    manual_lock = route.index("begin_manual_action(")
    submit = route.index("execute_aster_leg(")
    assert release < hedge_guard < manual_lock < submit
    assert "request.percentage == 100" not in route[route.index("needs_manual_auto_hedge_release = ("):release]
    assert 'caller="manual-position-close"' in route
    assert "except AutoHedgeCloseBlocked as exc" in route
