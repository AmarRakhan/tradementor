from pathlib import Path


def source() -> str:
    return Path(__file__).with_name("aster_position_loss_auto_hedge_extension.py").read_text(encoding="utf-8")


def main_source() -> str:
    return Path(__file__).with_name("main.py").read_text(encoding="utf-8")


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


def test_global_disable_requires_explicit_confirmation_and_is_audited():
    value = source()
    assert "confirmDisable: bool = False" in value
    assert "Auto Hedge uitschakelen vereist expliciete bevestiging" in value
    assert "BLOCKED_CONFIRMATION_REQUIRED" in value
    assert "GLOBAL_SETTINGS_CHANGE" in value
    assert '"previousEnabled": bool(previous_enabled)' in value
    assert '"requestedEnabled": bool(requested_enabled)' in value
    assert '"clientBuild": str(request.clientBuild or "")[:32]' in value
    assert '"clientSource": str(request.clientSource or "")[:64]' in value
    assert '"sourceRoute": source_route' in value
    assert '"result": result' in value


def test_manual_full_leg_release_is_symmetric_and_never_auto_reopens():
    extension = source()
    main = main_source()
    assert '"MANUAL_RELEASE_PENDING"' in extension
    assert '"MANUAL_RELEASE_UNCERTAIN"' in extension
    assert 'REHEDGEABLE_STATUSES = {"RECOVERY", "REHEDGE_ARMED", "DISABLED"}' in extension
    assert 'status not in REHEDGEABLE_STATUSES' in extension
    assert 'def _begin_position_loss_auto_hedge_manual_release' in main
    assert 'normalized_side not in {protected_side, hedge_side}' in main
    assert '"protectedSide": normalized_side' in main
    assert '"hedgeSide": survivor_side' in main
    assert '"rehedgeEnabled": False' in main
    assert '"status": "MANUAL_RELEASE_PENDING"' in main
    assert '"status": "MANUAL_RELEASE_UNCERTAIN"' in main
    assert '"USER_MANUAL_LEG_RELEASE_RECOVERY"' in main
    assert '"status": status' in main
    assert '"AUTO_HEDGE_LEG_RELEASE"' in main


def test_manual_auto_hedge_release_is_only_for_full_leg_closes():
    main = main_source()
    start = main.index("def _begin_position_loss_auto_hedge_manual_release")
    end = main.index("def _complete_position_loss_auto_hedge_manual_release", start)
    helper = main[start:end]
    assert 'if int(percentage) != 100:' in helper
    assert 'return None' in helper
    assert '"requestedCloseQty": float(close_quantity)' in helper
