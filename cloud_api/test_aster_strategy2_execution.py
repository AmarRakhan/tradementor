from decimal import Decimal
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
def context(owned=True,reconciled=True):return ExecutionContext("s2","c1",3,OwnedLeg("s2","strategy2","BTCUSDT","LONG","c1",3,.1,100) if owned else None,reconciled,True)

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
    with pytest.raises(ValueError):execute_decision(client,Decision("ADD_DCA","LONG",10),plan(),context(),risk_approved=lambda _:False)
    assert not client.calls

def test_confirmed_close_has_strategy_cycle_version_intent():
    client=Client();result=execute_decision(client,Decision("FULL_TP","LONG",10),plan(),context(),risk_approved=lambda _:True)
    assert result and "s2-s2-c1-v3" in client.calls[0]
