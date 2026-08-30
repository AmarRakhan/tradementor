from pathlib import Path


def test_emergency_equity_lock_precedes_rehedge_and_dca():
    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")
    lock = src.index("# EMERGENCY v7 equity lock")
    rehedge = src.index("# v7 post-release re-hedge")
    dca = src.index("# DCA is the ONLY re-hedge point")
    release = src.index("# v7 mechanical SHORT release")
    assert lock < rehedge < dca < release


def test_emergency_equity_lock_uses_real_account_equity_and_cycle_baseline():
    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")
    block = src[src.index("# EMERGENCY v7 equity lock"):src.index("# v7 post-release re-hedge")]
    assert "current_equity + 1e-9 < cycle_start_equity" in block
    assert "EMERGENCY_EQUITY_LOCK_REHEDGED" in block
    assert "EMERGENCY_EQUITY_LOCK_HOLD" in block
    assert '"dcaTriggerPending": False' in block
    assert '"reHedgeArmed": False' in block
    assert "target_lock_qty = primary_qty * configured_hedge_ratio" in block


def test_equity_lock_blocks_release_churn_by_early_return():
    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")
    block = src[src.index("# EMERGENCY v7 equity lock"):src.index("# v7 post-release re-hedge")]
    assert '"status": "holding", "action": "EMERGENCY_EQUITY_LOCK_HOLD"' in block
    assert "FOCUS_HEDGE_RELEASED_MECHANICAL" not in block
