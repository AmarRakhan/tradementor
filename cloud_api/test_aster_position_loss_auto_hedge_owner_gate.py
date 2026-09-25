from __future__ import annotations

from pathlib import Path


def test_auto_hedge_extension_is_hard_owner_only_and_fail_closed():
    source = Path(__file__).with_name("aster_position_loss_auto_hedge_extension.py").read_text(encoding="utf-8")
    assert "main.require_continuity_owner(user)" in source
    assert 'return {"available": False, "ownerOnly": True' in source
    assert 'uid != _owner_uid()' in source
    assert 'DYNAMIC_HEDGE_CONFLICT' in source
    assert 'ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED' in source
    assert 'default=DEFAULT_THRESHOLD_USD' in source
    assert 'collection("asterPositionLossAutoHedge")' in source


def test_legacy_portfolio_noodhedge_stays_unregistered_in_production_entrypoint():
    source = Path(__file__).with_name("withdraw_app.py").read_text(encoding="utf-8")
    assert "import aster_position_loss_auto_hedge_extension" in source
    assert "Portfolio Noodhedge is globally disabled" in source
    assert "aster_portfolio_emergency_hedge_extension" not in source
    assert "aster_portfolio_emergency_margin_extension" not in source
