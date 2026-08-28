from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_airbag import bollinger_1m, plan_focus_airbag


def plan(**updates):
    base=dict(enabled=True,main_side="LONG",main_quantity=10,mark=100,hedge_quantity=0,start_ratio=.2,maximum_ratio=.6,minimum_ratio=0,
        drawdown_levels=(.015,.03,.05),adverse_drawdown=0,portfolio_drawdown=0,bollinger=(101,103,97),local_extreme=104,new_portfolio_high=False)
    base.update(updates);return plan_focus_airbag(**base)


def test_airbag_off_is_noop_without_hedge_and_closes_only_its_existing_hedge():
    assert plan(enabled=False).action=="HOLD"
    result=plan(enabled=False,hedge_quantity=2)
    assert result.status=="UIT" and result.action=="CLOSE" and result.target_ratio==0


def test_initial_airbag_opens_start_ratio_when_enabled():
    result=plan()
    assert result.action=="INCREASE" and abs(result.target_ratio-.2)<1e-12


def test_deeper_drawdown_increases_to_mid_and_max():
    mid=plan(adverse_drawdown=.031)
    maximum=plan(adverse_drawdown=.051)
    assert .2<mid.target_ratio<.6 and maximum.target_ratio==.6


def test_portfolio_drawdown_can_drive_protection_even_if_pair_flat():
    assert plan(portfolio_drawdown=.051).target_ratio==.6


def test_new_portfolio_high_returns_hedge_to_minimum():
    result=plan(hedge_quantity=4,new_portfolio_high=True)
    assert result.target_ratio==0 and result.action=="REDUCE"


def test_recovery_above_middle_reduces_target():
    baseline=plan(adverse_drawdown=.031,mark=98,bollinger=(99,103,95),local_extreme=105)
    recovery=plan(adverse_drawdown=.031,mark=100,bollinger=(99,103,95),local_extreme=105)
    assert recovery.target_ratio<baseline.target_ratio


def test_breakout_returns_to_minimum_so_upside_is_not_capped():
    result=plan(mark=104,hedge_quantity=4,bollinger=(100,103,97),local_extreme=103)
    assert result.target_ratio==0 and result.action=="REDUCE"


def test_short_main_position_is_side_correct_on_recovery():
    result=plan(main_side="SHORT",mark=96,hedge_quantity=4,bollinger=(97,101,95),local_extreme=95,adverse_drawdown=.03)
    assert result.action=="REDUCE" and result.target_ratio<.4


def test_bollinger_uses_last_twenty_valid_closes():
    bands=bollinger_1m(range(80,101))
    assert bands and bands[0]>0 and bands[1]>bands[0]>bands[2]


def test_airbag_config_defaults_off_and_roundtrips():
    default=Strategy2Config.from_mapping({})
    assert default.focus_airbag_enabled is False
    configured=Strategy2Config.from_mapping({"focusAirbagEnabled":True,"focusAirbagStartRatio":.2,"focusAirbagMaxRatio":.6,"focusAirbagMinRatio":.05,"focusAirbagDrawdown1":.01,"focusAirbagDrawdown2":.02,"focusAirbagDrawdown3":.04})
    out=configured.public_dict()
    assert out["focusAirbagEnabled"] is True and out["focusAirbagMinRatio"]==.05

from aster_strategy2_focus_multi import run_multi_focus_live_step
from aster_strategy2_runtime import owned_to_mapping
from aster_strategy2_state import OwnedLeg


class Ref:
    def __init__(self): self.data={};self.events=[]
    def set(self,value,merge=True): self.data.update(value)
    def collection(self,_name): return self
    def add(self,value): self.events.append(value);return None


class AirbagClient:
    def __init__(self, *, side="LONG", mark=100.0, quantity=10.0, leverage=50, liquidation=0.0):
        self.mark=mark;self.leverage=leverage;self.main_side=side;self.submissions=[];self.order_id=100
        self.positions=[{"symbol":"SOLUSDT","positionSide":side,"positionAmt":str(quantity),"entryPrice":"100","markPrice":str(mark),"leverage":str(leverage),"liquidationPrice":str(liquidation)}]
    def ticker_prices(self): return [{"symbol":"SOLUSDT","price":str(self.mark)}]
    def leverage_brackets(self,symbol=None): return [{"symbol":"SOLUSDT","brackets":[{"notionalFloor":"0","notionalCap":"1000000","initialLeverage":"100","maintMarginRatio":"0.01"}]}]
    def public_exchange_info(self):
        return {"symbols":[{"symbol":"SOLUSDT","filters":[
            {"filterType":"PRICE_FILTER","minPrice":"0.001","maxPrice":"1000000","tickSize":"0.001"},
            {"filterType":"LOT_SIZE","minQty":"0.001","maxQty":"1000000","stepSize":"0.001"},
            {"filterType":"MARKET_LOT_SIZE","minQty":"0.001","maxQty":"1000000","stepSize":"0.001"},
            {"filterType":"MIN_NOTIONAL","notional":"1"},
        ]}]}
    def klines(self,symbol,interval,limit):
        # Completed candles sit above the current mark -> no recovery/breakout.
        return [[i,0,0,0,("101" if self.main_side=="LONG" else "99"),0] for i in range(limit)]
    def position_risk(self,symbol=None): return [dict(x) for x in self.positions]
    def change_margin_type(self,*_args): return {"marginType":"CROSSED"}
    def change_leverage(self,symbol,leverage): self.leverage=leverage;return {"symbol":symbol,"leverage":leverage}
    def user_trades(self,*_args,**_kwargs): return []
    def income_history(self,*_args,**_kwargs): return []
    def submit_order_once(self,intent,**_kwargs):
        self.submissions.append(intent);self.order_id+=1
        side=intent.position_side.value;qty=float(intent.quantity)
        row=next((x for x in self.positions if x["positionSide"]==side),None)
        if intent.action=="OPEN":
            if row is None:
                row={"symbol":"SOLUSDT","positionSide":side,"positionAmt":"0","entryPrice":str(self.mark),"markPrice":str(self.mark),"leverage":str(self.leverage),"liquidationPrice":"0"};self.positions.append(row)
            old=float(row["positionAmt"]);new=old+qty;row["positionAmt"]=str(new);row["entryPrice"]=str(self.mark);row["markPrice"]=str(self.mark);row["leverage"]=str(self.leverage)
        else:
            if row is None: raise AssertionError("closing absent hedge")
            new=max(0.0,float(row["positionAmt"])-qty);row["positionAmt"]=str(new);row["markPrice"]=str(self.mark)
            if new<=1e-12:self.positions=[x for x in self.positions if x is not row]
        return {"orderId":self.order_id,"clientOrderId":intent.intent_id,"executedQty":str(qty),"avgPrice":str(self.mark),"status":"FILLED"},False


def airbag_cfg(*,side="LONG",**updates):
    raw={"mode":"live","tradingMode":"focus","focusLiveEnabled":True,"focusSelectionMode":"manual","focusManualPair":"SOLUSDT",
         "focusSlots":[{"slotId":"slot-1","pair":"SOLUSDT","side":side,"leverageMode":"minimum","leverage":50,"startNotional":100}],
         "focusDcaEnabled":False,"focusMinimumProfitPct":.20,"focusTrailingActivationPct":.20,"focusAirbagEnabled":True,"focusAirbagStartRatio":.20,"focusAirbagMaxRatio":.60,"focusAirbagMinRatio":0,
         "focusAirbagDrawdown1":.015,"focusAirbagDrawdown2":.03,"focusAirbagDrawdown3":.05}
    raw.update(updates);return Strategy2Config.from_mapping(raw)


def airbag_raw(*,side="LONG",dca=4,original=100.0):
    leg=OwnedLeg("aster-strategy-2","strategy2","SOLUSDT",side,"cycle-a",1,10,100,dca,"FOCUS_SLOT:slot-1",created_at_ms=1000,last_order_at_ms=1000)
    return {"ownedLegs":[owned_to_mapping(leg)],"focusDesiredSlotCount":1,"focusLiveSlots":[{"slotId":"slot-1","pair":"SOLUSDT","side":side,"status":"ACTIVE","cycleId":"cycle-a","originalEntry":original,"weightedEntry":100,"quantity":10,"dcaCount":dca,"createdAt":1000}]}


def run_airbag(client, raw, settings, *, available=1000.0, ref=None, open_orders=None):
    ref=ref or Ref()
    result=run_multi_focus_live_step(client=client,ref=ref,raw_state=raw,settings=settings,uid="u",account={"totalMarginBalance":"1000","availableBalance":str(available),"totalMaintMargin":"1"},positions=client.position_risk(),timestamp_ms=200000,dry_run=False,order_budget=15,open_orders=open_orders or [])
    return result,ref


def test_runtime_airbag_activates_existing_trade_without_resetting_cycle_dca_or_entry():
    client=AirbagClient();raw=airbag_raw(dca=4,original=108.99);result,ref=run_airbag(client,raw,airbag_cfg())
    assert result["action"]=="FOCUS_AIRBAG_INCREASE" and len(client.submissions)==1
    short=next(x for x in client.positions if x["positionSide"]=="SHORT")
    assert abs(float(short["positionAmt"])-6)<.01
    state=ref.data["focusLiveSlots"][0]
    assert state["dcaCount"]==4 and state["originalEntry"]==108.99 and state["cycleId"]=="cycle-a"
    assert state["airbag"]["hedgeRatio"]>.19
    assert any(str(x.get("role","")).startswith("FOCUS_SLOT_AIRBAG:") for x in ref.data["ownedLegs"])


def test_runtime_airbag_is_idempotent_at_target_ratio():
    client=AirbagClient();raw=airbag_raw();result,ref=run_airbag(client,raw,airbag_cfg())
    raw2={**raw,**ref.data};before=len(client.submissions)
    result2,ref2=run_airbag(client,raw2,airbag_cfg(),ref=ref)
    assert result2["action"]=="FOCUS_HOLD" and len(client.submissions)==before


def test_runtime_airbag_deeper_drawdown_increases_existing_hedge():
    client=AirbagClient();raw=airbag_raw();_,ref=run_airbag(client,raw,airbag_cfg())
    # Move main and hedge to a 6% adverse move; max target becomes 60%.
    client.mark=94
    for row in client.positions: row["markPrice"]="94"
    raw2={**raw,**ref.data};result,ref=run_airbag(client,raw2,airbag_cfg(),ref=ref)
    assert result["action"]=="FOCUS_AIRBAG_INCREASE"
    hedge=next(x for x in client.positions if x["positionSide"]=="SHORT")
    assert float(hedge["positionAmt"])>5.9


def test_runtime_airbag_breakout_reduces_to_minimum_and_does_not_close_main():
    client=AirbagClient();raw=airbag_raw();_,ref=run_airbag(client,raw,airbag_cfg())
    client.mark=104
    for row in client.positions: row["markPrice"]="104"
    # Current mark is above constant 1m upper band -> target 0.
    raw2={**raw,**ref.data};result,ref=run_airbag(client,raw2,airbag_cfg(),ref=ref)
    assert result["action"]=="FOCUS_AIRBAG_REDUCE"
    assert any(x["positionSide"]=="LONG" and float(x["positionAmt"])==10 for x in client.positions)
    assert not any(x["positionSide"]=="SHORT" and float(x["positionAmt"])>0 for x in client.positions)


def test_runtime_airbag_blocks_new_hedge_when_liquidation_distance_is_unsafe():
    client=AirbagClient(liquidation=96);raw=airbag_raw();result,ref=run_airbag(client,raw,airbag_cfg())
    assert result["action"]=="FOCUS_HOLD" and not client.submissions
    state=ref.data["focusLiveSlots"][0]
    assert "Liquidatie" in state["airbag"]["reason"]


def test_runtime_airbag_blocks_new_hedge_on_insufficient_available_margin():
    client=AirbagClient();raw=airbag_raw();result,ref=run_airbag(client,raw,airbag_cfg(),available=.1)
    assert result["action"]=="FOCUS_HOLD" and not client.submissions
    assert "margin" in ref.data["focusLiveSlots"][0]["airbag"]["reason"].lower()


def test_runtime_airbag_open_order_pending_blocks_adjustment():
    client=AirbagClient();raw=airbag_raw();result,ref=run_airbag(client,raw,airbag_cfg(),open_orders=[{"symbol":"SOLUSDT"}])
    assert result["action"]=="FOCUS_HOLD" and not client.submissions
    assert ref.data["focusLiveSlots"][0]["pendingAction"]=="OPEN_ORDER_PENDING"


def test_runtime_short_focus_uses_long_airbag():
    client=AirbagClient(side="SHORT");raw=airbag_raw(side="SHORT");result,ref=run_airbag(client,raw,airbag_cfg(side="SHORT"))
    assert result["action"]=="FOCUS_AIRBAG_INCREASE"
    assert any(x["positionSide"]=="LONG" and float(x["positionAmt"])>0 for x in client.positions)


def test_runtime_airbag_off_leaves_current_focus_path_unchanged_when_no_airbag_exists():
    client=AirbagClient();raw=airbag_raw();settings=airbag_cfg(focusAirbagEnabled=False)
    result,ref=run_airbag(client,raw,settings)
    assert result["action"]=="FOCUS_HOLD" and not client.submissions
    state=ref.data["focusLiveSlots"][0]
    assert "airbag" not in state and state["cycleId"]=="cycle-a" and state["dcaCount"]==4


def test_disabling_airbag_closes_only_proven_airbag_hedge_and_keeps_main_trade():
    client=AirbagClient();raw=airbag_raw();_,ref=run_airbag(client,raw,airbag_cfg())
    assert any(x["positionSide"]=="SHORT" for x in client.positions)
    disabled=airbag_cfg(focusAirbagEnabled=False)
    result,ref=run_airbag(client,{**raw,**ref.data},disabled,ref=ref)
    assert result["action"]=="FOCUS_AIRBAG_REDUCE"
    assert any(x["positionSide"]=="LONG" and float(x["positionAmt"])==10 for x in client.positions)
    assert not any(x["positionSide"]=="SHORT" and float(x["positionAmt"])>0 for x in client.positions)


def test_runtime_airbag_stale_or_missing_1m_market_data_fails_closed():
    client=AirbagClient();client.klines=lambda *_args: []
    result,ref=run_airbag(client,airbag_raw(),airbag_cfg())
    assert result["action"]=="FOCUS_HOLD" and not client.submissions
    assert "1m" in ref.data["focusLiveSlots"][0]["airbag"]["reason"]


def test_runtime_airbag_never_claims_unknown_opposite_exchange_exposure():
    client=AirbagClient();client.positions.append({"symbol":"SOLUSDT","positionSide":"SHORT","positionAmt":"1","entryPrice":"100","markPrice":"100","leverage":"50","liquidationPrice":"0"})
    result,ref=run_airbag(client,airbag_raw(),airbag_cfg())
    assert result["action"]=="FOCUS_HOLD" and not client.submissions
    assert "geen bewezen Airbag-ownership" in ref.data["focusLiveSlots"][0]["airbag"]["reason"]


def test_queue_recovery_has_dedicated_airbag_role():
    from pathlib import Path
    source=Path("main.py").read_text()
    assert 'FOCUS_SLOT_AIRBAG:{slot_id}' in source
    assert 'FOCUS_AIRBAG_INCREASE' in source and 'FOCUS_AIRBAG_REDUCE' in source


def test_generic_strategy2_management_does_not_manage_airbag_hedge_as_harvest_leg():
    from pathlib import Path
    source=Path("main.py").read_text()
    assert 'not str(leg.role).upper().startswith("FOCUS_SLOT_AIRBAG:")' in source


def test_tp_candidate_removes_airbag_before_main_close_so_no_naked_hedge_remains():
    client=AirbagClient();raw=airbag_raw();_,ref=run_airbag(client,raw,airbag_cfg())
    assert any(x["positionSide"]=="SHORT" for x in client.positions)
    client.mark=103
    for row in client.positions: row["markPrice"]="103"
    settings=airbag_cfg(focusMinimumProfitPct=.02,focusTrailingActivationPct=.02)
    result,ref=run_airbag(client,{**raw,**ref.data},settings,ref=ref)
    assert result["action"]=="FOCUS_AIRBAG_EXIT_FOR_TP"
    assert any(x["positionSide"]=="LONG" and float(x["positionAmt"])==10 for x in client.positions)
    assert not any(x["positionSide"]=="SHORT" and float(x["positionAmt"])>0 for x in client.positions)


def test_manual_main_close_triggers_airbag_orphan_cleanup_before_any_restart():
    client=AirbagClient();raw=airbag_raw();_,ref=run_airbag(client,raw,airbag_cfg())
    client.positions=[x for x in client.positions if x["positionSide"]!="LONG"]
    before=len(client.submissions)
    result,ref=run_airbag(client,{**raw,**ref.data},airbag_cfg(),ref=ref)
    assert result["action"]=="FOCUS_AIRBAG_ORPHAN_CLEANUP"
    assert len(client.submissions)==before+1
    assert not any(float(x["positionAmt"])>0 for x in client.positions)
    assert not any(str(x.get("role","")).startswith("FOCUS_SLOT_AIRBAG:") for x in ref.data["ownedLegs"])
