from decimal import Decimal
from pathlib import Path
import pytest
from aster_strategy2_execution import *
from aster_strategy2 import Decision

class Client:
    def __init__(self,status="FILLED"):self.status=status;self.calls=[]
    def submit_order_once(self,intent,**kwargs):self.calls.append(intent.intent_id);return ({"status":self.status,"orderId":len(self.calls)},False)
    def query_order(self,symbol,intent_id):return {"status":self.status,"orderId":1}
    def change_margin_type(self,*a):pass
    def change_leverage(self,*a):return {}

def plan():return PairExecutionPlan("BTCUSDT",Decimal(".1"),Decimal("10"),10)
def context(owned=True,reconciled=True):return ExecutionContext("s2","c1",3,OwnedLeg("s2","strategy2","BTCUSDT","LONG","c1",3,.1,90,
    fill_ids=("f1",),fees=.01,funding=0,costs_updated_at_ms=1) if owned else None,reconciled,True,account_uid="uid",cost_evidence_fresh=True)

def test_unknown_fill_never_continues_or_resends():
    client=Client("NEW")
    with pytest.raises(RuntimeError):execute_decision(client,Decision("ADD_DCA","LONG",10),plan(),context(),risk_approved=lambda _:True)
    assert len(client.calls)==1

def test_unreconciled_state_blocks_before_order():
    client=Client()
    with pytest.raises(RuntimeError):execute_decision(client,Decision("ADD_DCA","LONG",10),plan(),context(reconciled=False),risk_approved=lambda _:True)
    assert not client.calls

def test_missing_ownership_blocks_dca_and_close():
    for decision in (Decision("ADD_DCA","LONG",10),Decision("FULL_TP","LONG",10)):
        client=Client()
        with pytest.raises(RuntimeError):execute_decision(client,decision,plan(),context(owned=False),risk_approved=lambda _:True)
        assert not client.calls

def test_risk_denial_blocks_dca():
    client=Client()
    with pytest.raises(Strategy2RiskBlocked):execute_decision(client,Decision("ADD_DCA","LONG",10),plan(),context(),risk_approved=lambda _:False)
    assert not client.calls

def test_runtime_converts_risk_denial_to_waiting_without_http_failure():
    source=(Path(__file__).parent/"main.py").read_text(encoding="utf-8")
    assert "except Strategy2RiskBlocked as exc:" in source
    assert '"action":"RISK_BLOCKED"' in source

def test_confirmed_close_has_strategy_cycle_version_intent():
    client=Client();result=execute_decision(client,Decision("FULL_TP","LONG",10),plan(),context(),risk_approved=lambda _:True)
    assert result and "s2-s2-c1-v3" in client.calls[0]

def test_queue_reserves_exact_intent_immediately_before_submission():
    reserved=[];base=context();queued=ExecutionContext(**{**base.__dict__,"before_submit":lambda intent:reserved.append(intent.intent_id)})
    client=Client();execute_decision(client,Decision("ADD_DCA","LONG",10),plan(),queued,risk_approved=lambda _:True)
    assert reserved==client.calls and len(reserved)==1


def test_profitable_tp_accepts_fresh_cost_evidence_when_legacy_fill_ids_are_missing():
    owned=OwnedLeg("s2","strategy2","BTCUSDT","LONG","c1",3,.1,90,
        fill_ids=(),fees=.01,funding=0,costs_updated_at_ms=123)
    ctx=ExecutionContext("s2","c1",3,owned,True,True,account_uid="uid",cost_evidence_fresh=True)
    client=Client()
    result=execute_decision(client,Decision("FULL_TP","LONG",10,reason="TP"),plan(),ctx,risk_approved=lambda _:True)
    assert result and len(client.calls)==1


def test_missing_fill_ids_still_fail_closed_without_fresh_cost_evidence():
    owned=OwnedLeg("s2","strategy2","BTCUSDT","LONG","c1",3,.1,90,
        fill_ids=(),fees=.01,funding=0,costs_updated_at_ms=123)
    ctx=ExecutionContext("s2","c1",3,owned,True,True,account_uid="uid",cost_evidence_fresh=False)
    client=Client()
    from aster_close_guard import AsterCloseBlocked
    with pytest.raises(AsterCloseBlocked):
        execute_decision(client,Decision("FULL_TP","LONG",10,reason="TP"),plan(),ctx,risk_approved=lambda _:True)
    assert not client.calls
