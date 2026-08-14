from decimal import Decimal
import pytest

from aster_execution import PairExecutionPlan
from aster_strategy2_state import OwnedLeg, reconcile_owned_legs
from aster_strategy3 import Decision
from aster_strategy3_execution import Strategy3ExecutionContext, execute_strategy3_decision
from aster_strategy3_readiness import build_strategy3_readiness_report


class FakeClient:
    def __init__(self, *, status="FILLED"):
        self.status = status
        self.calls = []
    def change_margin_type(self, symbol, mode): self.calls.append(("margin", symbol, mode))
    def change_leverage(self, symbol, leverage): self.calls.append(("leverage", symbol, leverage)); return {}
    def submit_order_once(self, intent, **kwargs):
        self.calls.append(("submit", intent.intent_id, intent.action))
        return ({"status": self.status, "executedQty": "1", "avgPrice": "10", "clientOrderId": intent.intent_id}, False)
    def query_order(self, symbol, intent_id):
        self.calls.append(("query", intent_id)); return {"status": self.status}


def plan(): return PairExecutionPlan("BTCUSDT", Decimal("1"), Decimal("10"), 10)
def context(**changes):
    values = dict(cycle_id="c1", config_version=3, ownership=None, exchange_reconciled=True, confirm=True, live_gate_open=True)
    values.update(changes); return Strategy3ExecutionContext(**values)
def owned(**changes):
    values = dict(strategy_id="aster-strategy-3", engine_type="strategy3", symbol="BTCUSDT", side="LONG", cycle_id="c1", config_version=3, quantity=1, weighted_entry=10)
    values.update(changes); return OwnedLeg(**values)


def test_live_gate_and_confirmation_are_both_required():
    with pytest.raises(RuntimeError): execute_strategy3_decision(FakeClient(), Decision("OPEN_BASE", "LONG", 10), plan(), context(live_gate_open=False), risk_approved=lambda _: True)
    with pytest.raises(ValueError): execute_strategy3_decision(FakeClient(), Decision("OPEN_BASE", "LONG", 10), plan(), context(confirm=False), risk_approved=lambda _: True)


def test_open_uses_shared_confirmed_executor_and_unique_s3_id():
    client=FakeClient(); result=execute_strategy3_decision(client,Decision("OPEN_BASE","LONG",10),plan(),context(),risk_approved=lambda _:True)
    assert result[0]["result"]["status"]=="FILLED"
    submit=[x for x in client.calls if x[0]=="submit"]
    assert len(submit)==1 and submit[0][1].startswith("s3-")


def test_scheduler_retry_keeps_same_exchange_client_order_id():
    first=FakeClient();second=FakeClient()
    decision=Decision("OPEN_BASE","LONG",10)
    execute_strategy3_decision(first,decision,plan(),context(tick_id="tick-a",action_id="stable-action"),risk_approved=lambda _:True)
    execute_strategy3_decision(second,decision,plan(),context(tick_id="tick-b",action_id="stable-action"),risk_approved=lambda _:True)
    first_id=[x[1] for x in first.calls if x[0]=="submit"][0]
    second_id=[x[1] for x in second.calls if x[0]=="submit"][0]
    assert first_id==second_id


def test_unknown_fill_never_causes_blind_resend():
    client=FakeClient(status="NEW")
    with pytest.raises(RuntimeError): execute_strategy3_decision(client,Decision("OPEN_BASE","LONG",10),plan(),context(),risk_approved=lambda _:True)
    assert len([x for x in client.calls if x[0]=="submit"])==1


def test_partial_fill_returns_proven_quantity_for_reconciliation_without_resend():
    client=FakeClient(status="PARTIALLY_FILLED")
    result=execute_strategy3_decision(client,Decision("OPEN_BASE","LONG",10),plan(),context(),risk_approved=lambda _:True)
    assert result[0]["result"]["executedQty"]=="1"
    assert result[0]["result"]["partialFillRequiresReconciliation"] is True
    assert len([x for x in client.calls if x[0]=="submit"])==1


def test_dca_and_close_require_exact_strategy3_ownership():
    wrong=owned(strategy_id="aster-strategy-2",engine_type="strategy2")
    for decision in (Decision("ADD_DCA","LONG",10),Decision("FULL_TP","LONG",10)):
        with pytest.raises(RuntimeError): execute_strategy3_decision(FakeClient(),decision,plan(),context(ownership=wrong),risk_approved=lambda _:True)


def test_partial_tp_executes_reduce_action_with_owned_leg():
    client=FakeClient(); result=execute_strategy3_decision(client,Decision("PARTIAL_TP","LONG",5,retain_notional=5),plan(),context(ownership=owned()),risk_approved=lambda _:True)
    assert result[0]["action"]=="CLOSE" and len([x for x in client.calls if x[0]=="submit"])==1


def test_strategy3_reconciliation_names_correct_owner():
    result=reconcile_owned_legs(persisted=[],positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"10"}],open_orders=[],fills=[],exchange_reliable=True,strategy_label="Strategy-3")
    assert not result.allow_risk_increase and "Strategy-3-ownership" in result.reasons[0]


def test_readiness_requires_coexistence_and_canary():
    base=dict(hedge_mode=True,account={"totalMarginBalance":"100"},positions=[],open_orders=[],strategy3_ownership_keys=set(),all_known_ownership_keys=set(),order_history_readable=True,fills_readable=True,income_readable=True,reconciliation_passed=True)
    report=build_strategy3_readiness_report(**base,coexistence_safe=True,canary_validated=False)
    assert report["softwareReady"] and not report["liveReady"] and report["ordersSent"]==0
    report=build_strategy3_readiness_report(**base,coexistence_safe=False,canary_validated=True)
    assert not report["softwareReady"] and not report["liveReady"]


def test_readiness_reports_actual_cross_strategy_collision():
    base=dict(hedge_mode=True,account={"totalMarginBalance":"100"},positions=[],open_orders=[],
        strategy3_ownership_keys={("CAPUSDT","LONG")},all_known_ownership_keys={("CAPUSDT","LONG")},
        order_history_readable=True,fills_readable=True,income_readable=True,reconciliation_passed=True)
    report=build_strategy3_readiness_report(**base,conflicting_ownership_keys={("CAPUSDT","LONG")},
        coexistence_safe=False,canary_validated=True)
    assert report["ownershipCollisions"]==[{"symbol":"CAPUSDT","side":"LONG"}]
    assert not report["softwareReady"]


def test_full_tp_and_trailing_tp_share_safe_close_path():
    for kind in ("FULL_TP","TRAILING_TP"):
        client=FakeClient()
        result=execute_strategy3_decision(client,Decision(kind,"LONG",10),plan(),context(ownership=owned()),risk_approved=lambda _:True)
        assert result[0]["action"]=="CLOSE"
        assert len([x for x in client.calls if x[0]=="submit"])==1


def test_risk_rejection_places_no_base_or_dca_order():
    for decision,owner in ((Decision("OPEN_BASE","LONG",10),None),(Decision("ADD_DCA","LONG",10),owned())):
        client=FakeClient()
        with pytest.raises(ValueError):
            execute_strategy3_decision(client,decision,plan(),context(ownership=owner),risk_approved=lambda _:False)
        assert not [x for x in client.calls if x[0]=="submit"]
