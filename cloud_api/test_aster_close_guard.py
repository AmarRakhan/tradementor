import pytest
from pathlib import Path
import re

from aster_close_guard import AsterCloseBlocked, BLOCK_MESSAGE, CloseEvidence, require_profitable_automatic_close


def evidence(**changes):
    values=dict(account_uid="uid-1",symbol="BTCUSDT",side="LONG",caller="strategy2:FULL_TP",
        reason="TP",quantity=1,entry_price=100,mark_price=101,gross_pnl=1,entry_fees=.2,
        close_fee=.2,funding=0,slippage_buffer=.1,other_costs=0,ownership_reliable=True,
        fills_reliable=True,prices_reliable=True,costs_reliable=True)
    values.update(changes)
    return CloseEvidence(**values)


def test_profit_before_costs_but_loss_after_costs_is_blocked():
    with pytest.raises(AsterCloseBlocked,match=BLOCK_MESSAGE):
        require_profitable_automatic_close(evidence(gross_pnl=.2,entry_fees=.1,close_fee=.1,slippage_buffer=.1))


def test_exact_break_even_is_blocked():
    with pytest.raises(AsterCloseBlocked):
        require_profitable_automatic_close(evidence(gross_pnl=.4,entry_fees=.1,close_fee=.2,slippage_buffer=.1))


def test_reliable_profit_above_buffer_is_allowed():
    assert require_profitable_automatic_close(evidence()).expected_net == pytest.approx(.5)


@pytest.mark.parametrize("field",["ownership_reliable","fills_reliable","prices_reliable","costs_reliable"])
def test_missing_reliable_evidence_is_fail_closed_and_audited(field):
    events=[]
    with pytest.raises(AsterCloseBlocked):
        require_profitable_automatic_close(evidence(**{field:False}),audit=events.append)
    assert events[0]["accountUid"]=="uid-1" and events[0]["expectedNetResult"]==pytest.approx(.5)


def test_partial_close_with_negative_net_is_blocked():
    with pytest.raises(AsterCloseBlocked):
        require_profitable_automatic_close(evidence(quantity=.25,gross_pnl=.1,entry_fees=.08,close_fee=.04,slippage_buffer=.02))


def test_accounts_are_isolated_in_audit_events():
    events=[]
    with pytest.raises(AsterCloseBlocked):
        require_profitable_automatic_close(evidence(account_uid="broken",costs_reliable=False),audit=events.append)
    assert require_profitable_automatic_close(evidence(account_uid="healthy")).account_uid=="healthy"
    assert events[0]["accountUid"]=="broken"


def test_every_production_aster_close_is_forced_through_shared_executor():
    root=Path(__file__).parent
    production=[path for path in root.glob("*.py") if not path.name.startswith("test_")]
    direct=[]
    for path in production:
        source=path.read_text(encoding="utf-8")
        if re.search(r"AsterOrderIntent\([^)]*[\"']CLOSE[\"']",source,re.DOTALL) and path.name not in {"aster_execution.py","aster_gateway.py"}:
            direct.append(path.name)
    assert direct==[]
    executor=(root/"aster_execution.py").read_text(encoding="utf-8")
    assert 'if action.upper() == "CLOSE" and not manual_loss_confirmation:' in executor
    assert "require_profitable_automatic_close(close_evidence" in executor


def test_all_strategy_close_decisions_use_the_same_close_guard():
    root=Path(__file__).parent
    s2=(root/"aster_strategy2_execution.py").read_text(encoding="utf-8")
    s3=(root/"aster_strategy3_execution.py").read_text(encoding="utf-8")
    for kind in ("FULL_TP","PARTIAL_TP","EMERGENCY_REDUCE","CLOSE_PROTECTION"):
        assert kind in s2
    for kind in ("FULL_TP","TRAILING_TP","PARTIAL_TP"):
        assert kind in s3
    assert "close_evidence=evidence" in s2 and "close_evidence=evidence" in s3


def test_strategy2_blocked_close_cannot_starve_other_position_management():
    source=(Path(__file__).parent/"main.py").read_text(encoding="utf-8")
    tick=source[source.index("def _run_aster_strategy2_tick"):source.index("def _aster_brackets")]
    assert 'action_key=f"{leg.symbol}|{leg.side}|{decision.kind}"' in tick
    assert 'blocked_management[action_key]=int(now.timestamp()*1000)+5*60*1000' in tick
    assert 'reason=f"{BLOCK_MESSAGE}; andere posities blijven beheerbaar"' in tick
    assert "same_pair_protection_decision(settings,portfolio,management_owned,management_positions,blocked_actions)" in tick


def test_emergency_risk_reduction_is_allowed_to_reach_the_net_profit_guard():
    source=(Path(__file__).parent/"main.py").read_text(encoding="utf-8")
    tick=source[source.index("def _run_aster_strategy2_tick"):source.index("def _aster_brackets")]
    assert "risk_approved=lambda margin:\n                    decision.risk_reducing or" in tick


def test_retired_strategy1_and_strategy3_runtimes_are_absent_from_active_backend():
    source=(Path(__file__).parent/"main.py").read_text(encoding="utf-8")
    assert "def _run_aster_automation_tick" not in source
    assert "def _run_aster_strategy3_tick" not in source
    assert '/v1/me/aster/automation/start' not in source
    assert '/v1/me/aster/strategy3/start' not in source
