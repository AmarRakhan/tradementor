from decimal import Decimal

from aster_gateway import AsterOrderIntent, PositionSide
from aster_portfolio_emergency_guard import FEATURE_ENABLED, emergency_blocks


def intent(action="OPEN", intent_id="tm-normal-order"):
    return AsterOrderIntent(
        intent_id=intent_id,
        symbol="XRPUSDT",
        position_side=PositionSide.LONG,
        quantity=Decimal("1"),
        action=action,
    )


def test_p0_kill_switch_is_disabled():
    assert FEATURE_ENABLED is False


def test_off_does_not_block_normal_open():
    assert emergency_blocks({"enabled": False, "status": "OFF"}, intent()) is False


def test_armed_stale_state_does_not_block_while_feature_disabled():
    assert emergency_blocks({"enabled": True, "status": "ARMED"}, intent()) is False


def test_executing_stale_state_does_not_block_normal_open_while_feature_disabled():
    assert emergency_blocks({"enabled": True, "status": "EXECUTING"}, intent()) is False


def test_executing_never_blocks_manual_close():
    assert emergency_blocks({"enabled": True, "status": "EXECUTING"}, intent("CLOSE")) is False


def test_locked_stale_state_does_not_block_while_feature_disabled():
    assert emergency_blocks({"enabled": True, "status": "LOCKED"}, intent()) is False


def test_locked_allows_explicit_manual_close():
    assert emergency_blocks({"enabled": True, "status": "LOCKED"}, intent("CLOSE")) is False


def test_emergency_order_is_not_blocked_by_gate():
    assert emergency_blocks(
        {"enabled": True, "status": "EXECUTING"},
        intent("OPEN", "tm-eh-3-deadbeef"),
    ) is False


def test_disabled_stale_locked_state_does_not_block():
    assert emergency_blocks({"enabled": False, "status": "LOCKED"}, intent()) is False
