from pathlib import Path


def _block(src: str) -> str:
    return src[src.index("# v7 equity protection:"):src.index("# v7 post-release re-hedge")]


def test_equity_protection_precedes_rehedge_and_dca():
    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")
    lock = src.index("# v7 equity protection:")
    rehedge = src.index("# v7 post-release re-hedge")
    dca = src.index("# DCA is the ONLY re-hedge point")
    release = src.index("# v7 protected SHORT release")
    assert lock < rehedge < dca < release


def test_equity_protection_uses_real_account_equity_and_repairs_missing_hedge():
    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")
    block = _block(src)
    assert "current_equity + 1e-9 < cycle_start_equity" in block
    assert "EMERGENCY_EQUITY_LOCK_REHEDGED" in block
    assert "target_lock_qty = primary_qty * configured_hedge_ratio" in block
    assert '"reHedgeArmed": False' in block
    assert "DCA-trigger blijft behouden" in block


def test_equity_protection_does_not_freeze_normal_dca_and_release_stays_guarded():
    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")
    block = _block(src)
    assert "Intentionally continue into normal DCA evaluation below." in block
    assert "equityDcaRearmedAfterLock" in block
    assert "Do NOT backfill missed historical DCA orders" in block
    assert "FOCUS_HEDGE_RELEASED_NET_GREEN" not in block
    release = src[src.index("# v7 protected SHORT release"):src.index("# Legacy non-simple Focus TP only.")]
    assert "equity_release_ready" in release
    assert "price_release_ready and net_green_ready and equity_release_ready" in release
