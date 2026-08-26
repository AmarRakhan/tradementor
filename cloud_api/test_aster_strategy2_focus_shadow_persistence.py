from pathlib import Path

from aster_strategy2_focus import FocusState
from aster_strategy2_focus_adapter import advance_focus_shadow_state


def test_partial_tp_advances_quantity_once_and_keeps_realized_pnl():
    previous=FocusState(active_pair="BTCUSDT",cycle_id="focus-1",weighted_entry=100.0,original_entry=100.0,total_quantity=10.0,total_notional=1000.0,used_margin=100.0,focus_budget_used=1000.0,theoretical_portfolio_value=1000.0)
    report={
        "decision":{"kind":"PARTIAL_TP","symbol":"BTCUSDT","close_fraction":0.25,"reason":"eerste partial TP bereikt"},
        "ranking":[{"symbol":"BTCUSDT","price":110.0}],
        "state":{**previous.public_dict(),"partials_taken":[1]},
        "performance":{"portfolioEquity":1000.0},
    }
    updated=advance_focus_shadow_state(report,previous,leverage=10,timestamp_ms=1)
    assert updated.total_quantity==7.5
    assert updated.total_notional==750.0
    assert updated.used_margin==75.0
    assert updated.focus_budget_used==750.0
    assert updated.realized_pnl==25.0
    assert updated.theoretical_portfolio_value==1025.0
    assert updated.partials_taken==(1,)


def test_scheduler_shadow_uses_non_order_capable_client_and_persists_audit():
    source=Path(__file__).with_name("main.py").read_text()
    start=source.index("def _run_focus_shadow_scheduler_step")
    end=source.index("def _run_aster_strategy2_tick",start)
    helper=source[start:end]
    assert "live_authorized=False" in helper
    assert "focusShadowAudit" in helper
    assert '"focusShadowOrdersSent":0' in helper
    assert "execute_aster_strategy2_decision" not in helper
    assert "_run_focus_shadow_scheduler_step(uid,ref,raw,settings,now)" in source
