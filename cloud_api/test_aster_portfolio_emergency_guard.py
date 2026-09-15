from decimal import Decimal

from aster_gateway import AsterOrderIntent, PositionSide
from aster_portfolio_emergency_guard import emergency_blocks


def intent(action="OPEN", intent_id="tm-normal-order"):
    return AsterOrderIntent(
        intent_id=intent_id,
        symbol="XRPUSDT",
        position_side=PositionSide.LONG,
        quantity=Decimal("1"),
        action=action,
    )


def test_off_does_not_block_normal_open():
    assert emergency_blocks({"enabled": False, "status": "OFF"}, intent()) is False


def test_armed_does_not_block_normal_open_before_trigger():
    assert emergency_blocks({"enabled": True, "status": "ARMED"}, intent()) is False


def test_executing_blocks_normal_open():
    assert emergency_blocks({"enabled": True, "status": "EXECUTING"}, intent()) is True


def test_executing_blocks_close_to_prevent_reconciliation_race():
    assert emergency_blocks({"enabled": True, "status": "EXECUTING"}, intent("CLOSE")) is True


def test_locked_blocks_new_exposure():
    assert emergency_blocks({"enabled": True, "status": "LOCKED"}, intent()) is True


def test_locked_allows_explicit_manual_close():
    assert emergency_blocks({"enabled": True, "status": "LOCKED"}, intent("CLOSE")) is False


def test_emergency_order_is_never_blocked_by_its_own_gate():
    assert emergency_blocks(
        {"enabled": True, "status": "EXECUTING"},
        intent("OPEN", "tm-eh-3-deadbeef"),
    ) is False


def test_disabled_stale_locked_state_does_not_block():
    assert emergency_blocks({"enabled": False, "status": "LOCKED"}, intent()) is False
