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
    assert "remaining is not None" in route
    assert "er wordt niet opnieuw besteld" in route
