from pathlib import Path


def test_manual_hedge_close_reconciles_to_same_rehedge_anchor_without_strategy_changes():
    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")
    assert "manual_hedge_closed = bool(" in src
    assert "FOCUS_MANUAL_HEDGE_CLOSE_RECONCILED" in src
    assert '"reHedgeArmed": True, "reHedgePrice": last_dca_manual' in src
    assert '"cycleStatus": "LONG_ONLY"' in src
    assert 'not bool(state.get("reHedgeArmed"))' in src
    assert 'focus_v2_hedge_release_recovery_pct' in src
    assert 'FOCUS_PORTFOLIO_TARGET_CLOSED' in src
    assert 'next_dca_from_anchor' in src
