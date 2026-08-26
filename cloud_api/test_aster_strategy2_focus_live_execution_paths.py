from __future__ import annotations
from dataclasses import replace

from aster_close_guard import CloseEvidence
from aster_strategy2 import Strategy2Config
from aster_strategy2_focus import FocusState
from aster_strategy2_focus_live import run_focus_live_step
from aster_strategy2_runtime import owned_to_mapping
from aster_strategy2_state import OwnedLeg


class FakeCollection:
    def add(self,_value): pass

class FakeRef:
    def __init__(self): self.values=[]
    def set(self,value,merge=False): self.values.append(value)
    def collection(self,_name): return FakeCollection()

class FakeClient:
    def public_exchange_info(self):
        return {"symbols":[{"symbol":"BTCUSDT","quoteAsset":"USDT","status":"TRADING","contractType":"PERPETUAL","filters":[
            {"filterType":"PRICE_FILTER","minPrice":"0.1","maxPrice":"1000000","tickSize":"0.1"},
            {"filterType":"LOT_SIZE","minQty":"0.001","maxQty":"1000","stepSize":"0.001"},
            {"filterType":"MARKET_LOT_SIZE","minQty":"0.001","maxQty":"1000","stepSize":"0.001"},
            {"filterType":"MIN_NOTIONAL","notional":"5"}]}]}
    def leverage_brackets(self,*_args): return [{"symbol":"BTCUSDT","brackets":[{"notionalFloor":"0","notionalCap":"1000000","initialLeverage":"20","maintMarginRatio":"0.01"}]}]


def config():
    return Strategy2Config.from_mapping({"tradingMode":"focus","mode":"live","focusLiveEnabled":True,"leverage":20,
        "focusMaxBudgetUsd":1000,"focusDcaEnabled":True,"focusMaxDca":5,"focusDcaDistance":.02,"strategyBudget":.9})


def focus_leg(qty=1.0,entry=100.0,dca=0):
    return OwnedLeg("aster-strategy-2","strategy2","BTCUSDT","LONG","focus-cycle",1,qty,entry,dca,"FOCUS",
        ("open-1",),("fill-1",),(),1000,last_order_at_ms=1000)


def position(qty=1.0,entry=100.0,mark=98.0):
    return {"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":str(qty),"entryPrice":str(entry),"markPrice":str(mark),"leverage":"20"}


def test_live_dca_updates_weighted_entry_and_focus_ownership(monkeypatch):
    previous=FocusState(active_pair="BTCUSDT",cycle_id="focus-cycle",original_entry=100,weighted_entry=100,
        total_quantity=1,total_notional=100,used_margin=5,focus_budget_used=100,dca_count=0)
    planned=replace(previous,next_dca_trigger=98,last_action="HOLD")
    report={"decision":{"kind":"DCA","symbol":"BTCUSDT","notional":100,"reason":"DCA 1 trigger bereikt"},
        "state":planned.public_dict(),"ranking":[{"symbol":"BTCUSDT","price":98}],"ordersSent":0}
    leg=focus_leg()
    monkeypatch.setattr("aster_strategy2_focus_live.build_focus_live_plan",lambda **_k:(report,previous,[leg]))
    reservations=[]
    def execute(_client,_plan,**kwargs):
        kwargs["before_submit"](object())
        return {"result":{"executedQty":"1","avgPrice":"98","clientOrderId":"dca-1","orderId":"dca-fill"}}
    monkeypatch.setattr("aster_strategy2_focus_live.execute_leg_once",execute)
    ref=FakeRef()
    result=run_focus_live_step(client=FakeClient(),ref=ref,raw_state={"ownedLegs":[owned_to_mapping(leg)]},settings=config(),uid="u",
        account={},positions=[position()],timestamp_ms=2000,reserve_order=lambda _i,d:reservations.append(d),open_orders=[])
    assert result["action"]=="FOCUS_DCA" and result["ordersSent"]==1
    final=next(v for v in reversed(ref.values) if "ownedLegs" in v)
    assert final["focusLiveState"]["dcaCount"]==1
    assert final["focusLiveState"]["weightedEntry"]==99.0
    assert final["ownedLegs"][0]["dcaCount"]==1
    assert final["ownedLegs"][0]["quantity"]==2.0
    assert reservations[0]["kind"]=="FOCUS_DCA"


def test_live_full_close_removes_focus_ownership_and_resets_for_next_cycle(monkeypatch):
    previous=FocusState(active_pair="BTCUSDT",cycle_id="focus-cycle",original_entry=100,weighted_entry=100,
        total_quantity=1,total_notional=100,used_margin=5,focus_budget_used=100,highest_price=106,trailing_active=True,trailing_floor=104)
    planned=replace(previous,last_action="CLOSE",last_reason="trailing floor geraakt")
    report={"decision":{"kind":"CLOSE","symbol":"BTCUSDT","reason":"trailing floor geraakt","risk_reducing":True},
        "state":planned.public_dict(),"ranking":[{"symbol":"BTCUSDT","price":105}],"ordersSent":0}
    leg=focus_leg()
    monkeypatch.setattr("aster_strategy2_focus_live.build_focus_live_plan",lambda **_k:(report,previous,[leg]))
    monkeypatch.setattr("aster_strategy2_focus_live._close_evidence",lambda **_k:CloseEvidence(
        "u","BTCUSDT","LONG","strategy2:FOCUS","trail",1,100,105,5,.05,.05,0,.1,True,True,True,True))
    reservations=[]
    def execute(_client,_plan,**kwargs):
        kwargs["before_submit"](object())
        return {"result":{"executedQty":"1","avgPrice":"105","clientOrderId":"close-1","orderId":"close-fill"}}
    monkeypatch.setattr("aster_strategy2_focus_live.execute_leg_once",execute)
    ref=FakeRef()
    result=run_focus_live_step(client=FakeClient(),ref=ref,raw_state={"ownedLegs":[owned_to_mapping(leg)]},settings=config(),uid="u",
        account={},positions=[position(mark=105)],timestamp_ms=3000,reserve_order=lambda _i,d:reservations.append(d),open_orders=[])
    assert result["action"]=="FOCUS_CLOSE" and result["ordersSent"]==1
    final=next(v for v in reversed(ref.values) if "ownedLegs" in v)
    assert final["ownedLegs"]==[]
    assert final["focusLiveState"]["activePair"]==""
    assert final["focusLiveState"]["totalQuantity"]==0
    assert final["focusLiveState"]["realizedPnl"]==5.0
    assert reservations[0]["kind"]=="FOCUS_CLOSE"
