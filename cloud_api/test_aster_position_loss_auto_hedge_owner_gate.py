from __future__ import annotations

from pathlib import Path


def test_auto_hedge_extension_is_release_gated_and_fail_closed():
    source = Path(__file__).with_name("aster_position_loss_auto_hedge_extension.py").read_text(encoding="utf-8")
    assert 'main.require_release_feature(user, "auto_hedge_v2")' in source
    assert "main.require_continuity_owner(user)" not in source
    assert "_owner_uid" not in source
    assert '"reason": "FEATURE_NOT_RELEASED"' in source
    assert 'main._release_feature_enabled_for_uid(uid, "auto_hedge_v2")' in source
    assert 'collection("asterPositionLossAutoHedge").stream()' in source
    assert "allow_new_triggers=entitled" in source
    assert "DYNAMIC_HEDGE_CONFLICT" in source
    assert "ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED" in source
    assert "default=DEFAULT_THRESHOLD_USD" in source


def test_release_rollback_stops_new_triggers_but_keeps_existing_locks_managed():
    source = Path(__file__).with_name("aster_position_loss_auto_hedge_extension.py").read_text(encoding="utf-8")
    assert "has_existing_lock = any(" in source
    assert "if not entitled and not has_existing_lock" in source
    assert "allow_new_triggers = entitled" in source
    assert "settings.get(\"enabled\") is True and allow_new_triggers" in source
    assert 'state.get("rehedgeEnabled") is True and allow_new_triggers' in source
    assert "Global OFF stops new triggers but never abandons an existing lock." in source


def test_legacy_portfolio_noodhedge_stays_unregistered_in_production_entrypoint():
    source = Path(__file__).with_name("withdraw_app.py").read_text(encoding="utf-8")
    assert "import aster_position_loss_auto_hedge_extension" in source
    assert "Portfolio Noodhedge is globally disabled" in source
    assert "aster_portfolio_emergency_hedge_extension" not in source
    assert "aster_portfolio_emergency_margin_extension" not in source


def test_multi_bb_auto_hedge_close_blocks_are_local_not_account_fatal():
    source = Path(__file__).with_name("aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert "from aster_position_loss_auto_hedge_lock import AutoHedgeCloseBlocked" in source
    assert source.count("except (AsterCloseBlocked, AutoHedgeCloseBlocked) as exc:") >= 2
    assert '"kind": "TP_BLOCKED"' in source
    assert '"kind": "ASYM_SHORT_CLOSE_BLOCKED"' in source


def test_strategy2_cannot_reopen_a_manually_released_auto_hedge_side_before_rehedge():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    start = source.index("def _block_strategy2_order_during_conflict")
    end = source.index("def _block_sniper_order_during_conflict", start)
    guard = source[start:end]
    assert '"RECOVERY", "REHEDGE_ARMED", "DISABLED"' in guard
    assert '"MANUAL_RELEASE_PENDING", "MANUAL_RELEASE_UNCERTAIN"' in guard
    assert 'side == str(pair.get("protectedSide", "")).upper()' in guard
    assert "AUTO_HEDGE_RECOVERY_SIDE_AWAITS_EXPLICIT_REHEDGE" in guard
