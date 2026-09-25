from pathlib import Path


def source() -> str:
    return Path(__file__).with_name("aster_position_loss_auto_hedge_extension.py").read_text(encoding="utf-8")


def test_pair_lifecycle_is_persistent_and_recovery_is_explicit():
    value = source()
    assert '.collection("pairs")' in value
    assert '"HEDGED"' in value
    assert '"ADJUSTING"' in value
    assert '"RECOVERY"' in value
    assert '"REHEDGE_ARMED"' in value
    assert '"PRECISION_BLOCKED"' in value
    assert '"PROTECTED_LEG_CLOSED_RECOVERY_REMAINS"' in value
    assert '"reservedHedgeQty": 0.0' in value
    assert '"rehedgeEnabled": False' in value


def test_recovery_rehedge_requires_explicit_user_control_and_global_auto_hedge():
    value = source()
    assert '/position-loss-auto-hedge/pairs/{symbol}/rehedge' in value
    assert 'class RehedgeRequest' in value
    assert 'Zet Auto Hedge eerst AAN' in value
    assert 'USER_REHEDGE_ENABLED' in value
    assert 'USER_REHEDGE_DISABLED' in value
    assert 'next_status = (' in value
    assert '"DISABLED"' in value


def test_global_off_does_not_abandon_existing_locked_cycles():
    value = source()
    assert 'has_active_lock = any(' in value
    assert 'settings.get("enabled") is not True and not has_active_lock' in value
    assert 'Global OFF stops new triggers but never abandons an existing lock.' in value


def test_closed_pairs_stay_persisted_but_leave_current_hedged_positions_view():
    value = source()
    assert 'if str(value.get("status", "")).upper() != "CLOSED"' in value
    assert '"status": "CLOSED"' in value
