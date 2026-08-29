"""Strategy-2 Focus 2.0: protected LONG builder.

This engine is intentionally isolated from legacy Focus.  A SHORT is an airbag,
not a profit centre.  Recovery releases may therefore realise a red hedge while
cycle equity remains the governing metric.  Legacy Focus close guards are never
called from this module and remain unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Any, Callable
import hashlib, math, time

from aster_execution import PairExecutionPlan, execute_leg_once
from aster_close_guard import CloseEvidence
from aster_gateway import AsterOrderIntent, ContractRules, PositionSide
from aster_strategy2 import Strategy2Config
from aster_strategy2_focus import dca_notional_sequence, next_dca_trigger, rank_focus_pairs
from aster_strategy2_focus_adapter import current_focus_markets
from aster_strategy2_focus_multi import resolve_slot_leverage
from aster_strategy2_runtime import active_position_map, owned_from_mapping, owned_to_mapping, cost_evidence_max_age_seconds
from aster_strategy2_state import OwnedLeg

ROLE_LONG="FOCUS_V2_LONG"
ROLE_HEDGE="FOCUS_V2_HEDGE"
REHEDGE_PREFIX="s2fv2rh-"

def f(v:Any,d:float=0.0)->float:
    try:n=float(v)
    except (TypeError,ValueError):return d
    return n if math.isfinite(n) else d

@dataclass(frozen=True)
class FocusV2State:
    cycle_id:str=""; symbol:str=""; cycle_start_equity:float=0.0; opened_at_ms:int=0
    original_entry:float=0.0; weighted_entry:float=0.0; dca_count:int=0
    recent_low:float=0.0; recovery_high:float=0.0; release_stage:int=0
    rehedge_client_id:str=""; rehedge_stop_price:float=0.0
    realized_hedge_pnl:float=0.0; harvest_baseline_equity:float=0.0; total_harvested_profit:float=0.0; last_harvest_profit:float=0.0
    dca_anchor_price:float=0.0; last_action:str="IDLE"; last_reason:str=""

def state_from(raw:Any)->FocusV2State:
    x=raw if isinstance(raw,dict) else {}
    def g(c,s,d=None):return x[c] if c in x else x.get(s,d)
    return FocusV2State(str(g("cycleId","cycle_id","") or ""),str(g("symbol","symbol","") or "").upper(),f(g("cycleStartEquity","cycle_start_equity",0)),int(f(g("openedAt","opened_at_ms",0))),f(g("originalEntry","original_entry",0)),f(g("weightedEntry","weighted_entry",0)),int(f(g("dcaCount","dca_count",0))),f(g("recentLow","recent_low",0)),f(g("recoveryHigh","recovery_high",0)),int(f(g("releaseStage","release_stage",0))),str(g("rehedgeClientId","rehedge_client_id","") or ""),f(g("rehedgeStopPrice","rehedge_stop_price",0)),f(g("realizedHedgePnl","realized_hedge_pnl",0)),f(g("harvestBaselineEquity","harvest_baseline_equity",g("cycleStartEquity","cycle_start_equity",0))),f(g("totalHarvestedProfit","total_harvested_profit",0)),f(g("lastHarvestProfit","last_harvest_profit",0)),f(g("dcaAnchorPrice","dca_anchor_price",g("weightedEntry","weighted_entry",g("originalEntry","original_entry",0)))),str(g("lastAction","last_action","IDLE") or "IDLE"),str(g("lastReason","last_reason","") or ""))

def state_map(s:FocusV2State)->dict[str,Any]:
    return {"cycleId":s.cycle_id,"symbol":s.symbol,"cycleStartEquity":s.cycle_start_equity,"openedAt":s.opened_at_ms,"originalEntry":s.original_entry,"weightedEntry":s.weighted_entry,"dcaCount":s.dca_count,"recentLow":s.recent_low,"recoveryHigh":s.recovery_high,"releaseStage":s.release_stage,"rehedgeClientId":s.rehedge_client_id,"rehedgeStopPrice":s.rehedge_stop_price,"realizedHedgePnl":s.realized_hedge_pnl,"harvestBaselineEquity":s.harvest_baseline_equity,"totalHarvestedProfit":s.total_harvested_profit,"lastHarvestProfit":s.last_harvest_profit,"dcaAnchorPrice":s.dca_anchor_price,"lastAction":s.last_action,"lastReason":s.last_reason}

def target_hedge_notional(long_notional:float,*,min_bias_usdt:float,min_bias_ratio:float,max_hedge_ratio:float)->float:
    long=max(0.0,long_notional);bias=max(0.0,min_bias_usdt,long*max(0.0,min_bias_ratio))
    return max(0.0,min(long*max(0.0,min(max_hedge_ratio,.999999)),long-bias))


def continuous_dca_trigger(anchor_price:float,distance_pct:float)->float:
    if anchor_price<=0 or distance_pct<=0:return 0.0
    return anchor_price*(1-max(0.0,min(.99,distance_pct)))

def harvest_fraction(available_net_profit:float,harvest_usdt:float)->float:
    if available_net_profit<=0 or harvest_usdt<=0:return 0.0
    return max(0.0,min(.95,harvest_usdt/available_net_profit))

def combined_close_evidence(*,uid:str,symbol:str,mark:float,long_leg:OwnedLeg|None,short_leg:OwnedLeg|None,long_qty:float,short_qty:float,close_fee_rate:float=.0005,slippage_rate:float=.001)->tuple[float,dict[str,float]]:
    def leg_net(leg:OwnedLeg|None,qty:float,side:str)->tuple[float,float,float,float,float]:
        if leg is None or qty<=0 or leg.quantity<=0:return 0.0,0.0,0.0,0.0,0.0
        ratio=min(1.0,qty/max(leg.quantity,1e-12));gross=((mark-leg.weighted_entry) if side=="LONG" else (leg.weighted_entry-mark))*qty
        notional=qty*mark;fees=max(0.0,leg.fees)*ratio;funding=leg.funding*ratio;close_fee=notional*close_fee_rate;slip=notional*slippage_rate
        return gross+funding-fees-close_fee-slip,gross,fees+close_fee,funding,slip
    ln,lg,lf,lfo,ls=leg_net(long_leg,long_qty,"LONG");sn,sg,sf,sfo,ss=leg_net(short_leg,short_qty,"SHORT")
    return ln+sn,{"grossPnl":lg+sg,"fees":lf+sf,"funding":lfo+sfo,"slippageBuffer":ls+ss}

def _close_v2_leg(*,client:Any,plan:PairExecutionPlan,side:PositionSide,prefix:str)->dict[str,Any]:
    # Focus 2.0 combined-cycle profit is proven before this helper is called.
    # Do not apply a legacy per-leg profitable-close gate to a deliberately losing hedge leg.
    return execute_leg_once(client,plan,side=side,action="CLOSE",id_prefix=prefix,confirm=True,manual_loss_confirmation=True)

def release_quantity(short_quantity:float,release_ratio:float,full_release:bool)->float:
    return max(0.0,short_quantity if full_release else short_quantity*max(0.0,min(1.0,release_ratio)))

def recovery_confirmed(*,mark:float,recent_low:float,bollinger_middle:float,equity:float,cycle_start_equity:float,rebound_pct:float,portfolio_ratio:float,require_middle:bool)->bool:
    if mark<=0 or recent_low<=0 or cycle_start_equity<=0:return False
    price_ok=mark>=recent_low*(1+max(0.0,rebound_pct))
    middle_ok=(not require_middle) or (bollinger_middle>0 and mark>=bollinger_middle)
    portfolio_ok=equity>=cycle_start_equity*max(0.0,min(1.05,portfolio_ratio))
    # A strong price recovery can start staged release before full portfolio recovery;
    # the final tranche still requires the explicit portfolio threshold.
    return price_ok and middle_ok and (portfolio_ok or equity>=cycle_start_equity*.95)

def full_recovery(*,equity:float,cycle_start_equity:float,ratio:float)->bool:
    return cycle_start_equity>0 and equity>=cycle_start_equity*ratio

def rehedge_stop(mark:float,setback:float)->float:return max(0.0,mark*(1-max(0.0001,setback)))

def _audit(ref:Any,event:str,**details:Any)->None:
    try:ref.collection("audit").add({"event":event,"strategyId":"aster-strategy-2","mode":"focus_v2","details":details,"timestampMs":int(time.time()*1000)})
    except Exception:pass

def _owned(raw:dict[str,Any])->list[OwnedLeg]:
    out=[]
    for row in raw.get("ownedLegs",[]) if isinstance(raw.get("ownedLegs"),list) else []:
        try:out.append(owned_from_mapping(row))
        except Exception:pass
    return out

def _v2(owned:list[OwnedLeg],role:str)->OwnedLeg|None:return next((x for x in owned if str(x.role).upper()==role),None)

def _row(positions:list[dict[str,Any]],symbol:str,side:str)->dict[str,Any]|None:return active_position_map(positions).get((symbol.upper(),side.upper()))

def _notional(row:dict[str,Any]|None)->float:
    if not row:return 0.0
    return abs(f(row.get("positionAmt")))*(f(row.get("markPrice")) or f(row.get("entryPrice")))

def _plan(client:Any,symbol:str,mark:float,notional:float,leverage:int)->PairExecutionPlan:
    info=client.public_exchange_info();r=next(x for x in info.get("symbols",[]) if str(x.get("symbol","")).upper()==symbol.upper())
    rules=ContractRules.from_exchange_info(r);qty=rules.market_quantity(Decimal(str(notional/mark)),Decimal(str(mark)))
    return PairExecutionPlan(symbol,qty,qty*Decimal(str(mark)),leverage,rules.tick_size,rules.market_quantity_step,rules.market_min_quantity,rules.min_notional)

def _fill(result:dict[str,Any])->tuple[float,float,str,str]:
    row=result.get("result") if isinstance(result.get("result"),dict) else {}
    q=abs(f(row.get("executedQty")));p=f(row.get("avgPrice"));cid=str(row.get("clientOrderId","") or "");oid=str(row.get("orderId",cid) or cid)
    if q<=0 or p<=0:raise RuntimeError("Focus 2.0 order mist bevestigde fill")
    return q,p,cid,oid

def _upsert(owned:list[OwnedLeg],*,settings:Strategy2Config,state:FocusV2State,role:str,side:str,q:float,p:float,cid:str,oid:str,is_dca:bool,ts:int)->list[OwnedLeg]:
    old=_v2(owned,role)
    if old is None:
        leg=OwnedLeg(settings.strategy_id,"strategy2",state.symbol,side,state.cycle_id,settings.version,q,p,1 if is_dca else 0,role,tuple(x for x in (cid,) if x),tuple(x for x in (oid,) if x),(),ts,last_order_at_ms=ts)
        return [*owned,leg]
    total=old.quantity+q;avg=(old.quantity*old.weighted_entry+q*p)/total
    from dataclasses import replace
    new=replace(old,quantity=total,weighted_entry=avg,dca_count=old.dca_count+(1 if is_dca else 0),intent_ids=tuple(dict.fromkeys((*old.intent_ids,*((cid,) if cid else ())))),fill_ids=tuple(dict.fromkeys((*old.fill_ids,*((oid,) if oid else ())))),last_order_at_ms=ts)
    return [new if x is old else x for x in owned]

def _reduce_owned(owned:list[OwnedLeg],role:str,closed:float,ts:int)->list[OwnedLeg]:
    from dataclasses import replace
    old=_v2(owned,role)
    if not old:return owned
    remain=max(0.0,old.quantity-closed)
    if remain<=1e-12:return [x for x in owned if x is not old]
    new=replace(old,quantity=remain,last_order_at_ms=ts)
    return [new if x is old else x for x in owned]

def _cancel_rehedge(client:Any,state:FocusV2State)->None:
    if not state.rehedge_client_id or not state.symbol:return
    try:client.cancel_order(state.symbol,client_order_id=state.rehedge_client_id)
    except Exception:pass

def _arm_rehedge(*,client:Any,state:FocusV2State,settings:Strategy2Config,mark:float,quantity:float,reserve_order:Callable|None)->FocusV2State:
    from dataclasses import replace
    if quantity<=0:return replace(state,rehedge_client_id="",rehedge_stop_price=0.0)
    _cancel_rehedge(client,state)
    stop=rehedge_stop(mark,settings.focus_v2_rehedge_setback_pct)
    cid=(REHEDGE_PREFIX+hashlib.sha256(f"{state.cycle_id}|{state.release_stage}|{stop:.8f}".encode()).hexdigest()[:20])[:36]
    intent=AsterOrderIntent(cid,state.symbol,PositionSide.SHORT,Decimal(str(quantity)),"OPEN")
    if reserve_order:reserve_order(intent,{"kind":"FOCUS_V2_REHEDGE_STOP","cycleId":state.cycle_id,"riskReducing":True,"marginUsd":float(quantity)*mark/max(1,settings.leverage)})
    payload={"symbol":state.symbol,"side":"SELL","positionSide":"SHORT","type":"STOP_MARKET","quantity":format(Decimal(str(quantity)),"f"),"stopPrice":format(Decimal(str(stop)),"f"),"workingType":"MARK_PRICE","newClientOrderId":cid}
    response=client.signed_request("POST","/fapi/v3/order",payload)
    if not isinstance(response,dict) or response.get("orderId") is None:raise RuntimeError("Aster bevestigde Focus 2.0 re-hedge trigger niet")
    return replace(state,rehedge_client_id=cid,rehedge_stop_price=stop)

def _bb5(client:Any,symbol:str)->tuple[float,float,float]:
    closes=[]
    try:
        for c in client.klines(symbol,"5m",30):
            if len(c)>4 and f(c[4])>0:closes.append(f(c[4]))
    except Exception:return 0.0,0.0,0.0
    if len(closes)<20:return 0.0,0.0,min(closes) if closes else 0.0
    w=closes[-20:];mid=sum(w)/len(w);var=sum((x-mid)**2 for x in w)/len(w);dev=var**.5
    return mid,mid+2*dev,min(closes[-10:])

def _slot_for_symbol(settings:Strategy2Config,symbol:str)->dict[str,Any]:
    for raw in settings.focus_slots:
        if isinstance(raw,dict) and str(raw.get("pair",raw.get("symbol",""))).upper().strip()==symbol.upper():
            return dict(raw)
    return {"pair":symbol,"leverageMode":"exact","leverage":settings.leverage,"startNotional":settings.focus_start_order_notional}

def _resolved_leverage(client:Any,settings:Strategy2Config,symbol:str,existing:dict[str,Any]|None=None)->int:
    row=existing or {}
    current=int(f(row.get("leverage"))) if f(row.get("leverage"))>0 else None
    effective,_=resolve_slot_leverage(client,_slot_for_symbol(settings,symbol),settings,existing_leverage=current)
    return effective

def _selected_symbol(client:Any,settings:Strategy2Config,state:FocusV2State)->str:
    if state.symbol:return state.symbol
    if settings.focus_slots:
        pair=str(settings.focus_slots[0].get("pair","") if isinstance(settings.focus_slots[0],dict) else getattr(settings.focus_slots[0],"pair","")).upper().strip()
        if pair:return pair
    if settings.focus_manual_pair:return settings.focus_manual_pair.upper().strip()
    markets=current_focus_markets(client,settings);ranking=rank_focus_pairs(list(markets),minimum_quote_volume=settings.minimum_quote_volume_24h_usdt,minimum_liquidity_score=settings.focus_min_liquidity_score)
    return next((r.symbol for r in ranking if r.eligible),"")

def run_focus_v2_live_step(*,client:Any,ref:Any,raw_state:dict[str,Any],settings:Strategy2Config,uid:str,account:dict[str,Any],positions:list[dict[str,Any]],timestamp_ms:int,dry_run:bool=False,order_budget:int|None=None,reserve_order:Callable|None=None,open_orders:list[dict[str,Any]]|None=None)->dict[str,Any]:
    from dataclasses import replace
    state=state_from(raw_state.get("focusV2State"));owned=_owned(raw_state);equity=f(account.get("totalMarginBalance"),f(account.get("totalWalletBalance")));available=f(account.get("availableBalance"));maint=f(account.get("totalMaintMargin"))/equity if equity>0 else 1.0
    symbol=_selected_symbol(client,settings,state)
    if not symbol:return {"status":"waiting","action":"FOCUS_V2_NO_PAIR","ordersSent":0}
    old_focus=[x for x in owned if str(x.role).upper().startswith("FOCUS") and str(x.role).upper() not in {ROLE_LONG,ROLE_HEDGE}]
    if not state.cycle_id and old_focus:return {"status":"waiting","action":"FOCUS_V2_WAIT_FLAT","reason":"Bestaande Focus ownership wordt nooit gemigreerd","ordersSent":0}
    long_row=_row(positions,symbol,"LONG");short_row=_row(positions,symbol,"SHORT")
    if not state.cycle_id and (long_row or short_row):return {"status":"waiting","action":"FOCUS_V2_WAIT_FLAT","reason":"Bestaande exchange-positie wordt niet geadopteerd","ordersSent":0}
    mark=f((long_row or short_row or {}).get("markPrice"))
    if mark<=0:
        prices={str(x.get("symbol","")).upper():f(x.get("price")) for x in client.ticker_prices() if isinstance(x,dict)};mark=prices.get(symbol,0.0)
    if mark<=0:raise RuntimeError("Focus 2.0 heeft geen betrouwbare markprijs")
    mid,_,local_low=_bb5(client,symbol)
    if dry_run or settings.mode!="live":return {"status":"simulated","action":"FOCUS_V2_HOLD","symbol":symbol,"ordersSent":0}
    if order_budget is not None and order_budget<1:return {"status":"budget-exhausted","action":"FOCUS_V2_HOLD","ordersSent":0}

    # A new Focus 2.0 cycle is a protected pair: never intentionally create a naked LONG.
    if not state.cycle_id:
        if order_budget is not None and order_budget<2:
            return {"status":"budget-exhausted","action":"FOCUS_V2_WAIT_PROTECTED_OPEN","reason":"twee orderplaatsen vereist voor LONG + hedge","ordersSent":0}
        cycle=f"focusv2-{hashlib.sha256(f'{uid}|{symbol}|{timestamp_ms}'.encode()).hexdigest()[:16]}";start_notional=max(0.0,settings.focus_start_order_notional)
        if start_notional<=0:raise RuntimeError("Focus 2.0 startnotional is nul")
        leverage=_resolved_leverage(client,settings,symbol)
        hedge_target=target_hedge_notional(start_notional,min_bias_usdt=settings.focus_v2_min_net_long_usdt,min_bias_ratio=settings.focus_v2_min_net_long_ratio,max_hedge_ratio=settings.focus_v2_max_hedge_ratio)
        required_margin=(start_notional+hedge_target)/max(1,leverage)
        if required_margin>available: return {"status":"waiting","action":"FOCUS_V2_MARGIN_BLOCK","ordersSent":0}
        state=FocusV2State(cycle,symbol,equity,timestamp_ms,0,0,0,mark,mark,0,"",0,0,equity,0,0,mark,"OPEN_PENDING","nieuwe schone Focus 2.0 cycle")
        plan=_plan(client,symbol,mark,start_notional,leverage);prefix=f"s2fv2-{hashlib.sha256(f'{cycle}|long0'.encode()).hexdigest()[:12]}"
        def reserve(i:Any)->None:
            if reserve_order:reserve_order(i,{"kind":"FOCUS_V2_OPEN_LONG","cycleId":cycle,"marginUsd":start_notional/max(1,leverage)})
        result=execute_leg_once(client,plan,side=PositionSide.LONG,action="OPEN",id_prefix=prefix,confirm=True,before_submit=reserve,new_position_leverage=leverage)
        q,p,cid,oid=_fill(result);owned=_upsert(owned,settings=settings,state=state,role=ROLE_LONG,side="LONG",q=q,p=p,cid=cid,oid=oid,is_dca=False,ts=timestamp_ms);state=replace(state,original_entry=p,weighted_entry=p,recent_low=p,recovery_high=p,last_action="OPEN_LONG",last_reason="eerste LONG bevestigd")
        actual_long=q*p;actual_hedge_target=target_hedge_notional(actual_long,min_bias_usdt=settings.focus_v2_min_net_long_usdt,min_bias_ratio=settings.focus_v2_min_net_long_ratio,max_hedge_ratio=settings.focus_v2_max_hedge_ratio)
        try:
            hplan=_plan(client,symbol,p,actual_hedge_target,leverage);hprefix=f"s2fv2-{hashlib.sha256(f'{cycle}|hedge0'.encode()).hexdigest()[:12]}"
            hresult=execute_leg_once(client,hplan,side=PositionSide.SHORT,action="OPEN",id_prefix=hprefix,confirm=True,new_position_leverage=leverage)
            hq,hp,hcid,hoid=_fill(hresult);owned=_upsert(owned,settings=settings,state=state,role=ROLE_HEDGE,side="SHORT",q=hq,p=hp,cid=hcid,oid=hoid,is_dca=False,ts=timestamp_ms)
        except Exception:
            # Fail closed: if protection cannot be confirmed, immediately flatten the just-opened LONG.
            cplan=_plan(client,symbol,p,actual_long,leverage);cprefix=f"s2fv2-{hashlib.sha256(f'{cycle}|rollback'.encode()).hexdigest()[:12]}"
            execute_leg_once(client,cplan,side=PositionSide.LONG,action="CLOSE",id_prefix=cprefix,confirm=True)
            _audit(ref,"FOCUS_V2_PROTECTED_OPEN_ROLLBACK",cycleId=cycle,symbol=symbol,longNotional=actual_long,reason="protective SHORT kon niet bevestigd worden")
            raise
        state=replace(state,last_action="OPEN_PROTECTED",last_reason="LONG + beschermende SHORT bevestigd")
        ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned],"phase":"FOCUS_V2_LIVE"},merge=True)
        _audit(ref,"FOCUS_V2_CYCLE_STARTED",cycleId=cycle,symbol=symbol,cycleStartEquity=equity,longNotional=actual_long,shortNotional=hq*hp,effectiveLeverage=leverage)
        return {"status":"executed","action":"FOCUS_V2_OPEN_PROTECTED","symbol":symbol,"ordersSent":2,"cycleId":cycle,"effectiveLeverage":leverage}

    long_notional=_notional(long_row);short_notional=_notional(short_row);long_qty=abs(f((long_row or {}).get("positionAmt")));short_qty=abs(f((short_row or {}).get("positionAmt")))
    if long_notional<=0:
        _cancel_rehedge(client,state); pnl=equity-state.cycle_start_equity
        ref.set({"focusV2State":state_map(FocusV2State()),"ownedLegs":[owned_to_mapping(x) for x in owned if str(x.role).upper() not in {ROLE_LONG,ROLE_HEDGE}],"focusV2LastCycle":{"cycleId":state.cycle_id,"resultUsd":pnl,"closedAt":timestamp_ms},"phase":"FOCUS_LIVE"},merge=True)
        return {"status":"executed","action":"FOCUS_V2_CYCLE_FLAT","ordersSent":0,"cyclePnl":pnl}
    entry=f((long_row or {}).get("entryPrice"),state.weighted_entry);recent_low=min(x for x in (state.recent_low or mark,mark,local_low or mark) if x>0);state=replace(state,recent_low=recent_low,recovery_high=max(state.recovery_high,mark),weighted_entry=entry,dca_anchor_price=max(state.dca_anchor_price or mark,mark),harvest_baseline_equity=state.harvest_baseline_equity or state.cycle_start_equity)

    # Continuous Focus 2.0 harvest: realize only the configured profit slice and keep the cycle alive.
    baseline=state.harvest_baseline_equity or state.cycle_start_equity
    equity_gain=equity-baseline
    trigger_usdt=max(0.0,settings.focus_v2_profit_trigger_usdt);harvest_usdt=max(0.0,settings.focus_v2_profit_harvest_usdt)
    long_leg=_v2(owned,ROLE_LONG);short_leg=_v2(owned,ROLE_HEDGE)
    cost_max_age_ms=cost_evidence_max_age_seconds(owned)*1000
    costs_reliable=bool(long_leg and short_leg and long_leg.costs_updated_at_ms>0 and short_leg.costs_updated_at_ms>0 and timestamp_ms-long_leg.costs_updated_at_ms<=cost_max_age_ms and timestamp_ms-short_leg.costs_updated_at_ms<=cost_max_age_ms)
    full_net,full_costs=combined_close_evidence(uid=uid,symbol=symbol,mark=mark,long_leg=long_leg,short_leg=short_leg,long_qty=long_qty,short_qty=short_qty)
    harvest_available=min(equity_gain,full_net) if costs_reliable else 0.0
    if trigger_usdt>0 and harvest_usdt>0 and equity_gain>=trigger_usdt and not costs_reliable:
        return {"status":"waiting","action":"FOCUS_V2_HARVEST_COST_EVIDENCE_WAIT","ordersSent":0,"reason":"fees/funding bewijs is niet vers genoeg"}
    if trigger_usdt>0 and harvest_usdt>0 and equity_gain>=trigger_usdt and harvest_available>=harvest_usdt:
        if order_budget is not None and order_budget<2:return {"status":"budget-exhausted","action":"FOCUS_V2_WAIT_PROFIT_HARVEST","ordersSent":0}
        fraction=harvest_fraction(harvest_available,harvest_usdt)
        lq=long_qty*fraction;sq=short_qty*fraction
        if lq<=0 or sq<=0:return {"status":"waiting","action":"FOCUS_V2_HARVEST_NOT_EXECUTABLE","ordersSent":0}
        _cancel_rehedge(client,state)
        lplan=_plan(client,symbol,mark,lq*mark,int(f((long_row or {}).get("leverage"),settings.leverage)));splan=_plan(client,symbol,mark,sq*mark,int(f((short_row or {}).get("leverage"),settings.leverage)))
        # Re-evaluate the executable rounded quantities before sending either close.
        expected_net,costs=combined_close_evidence(uid=uid,symbol=symbol,mark=mark,long_leg=long_leg,short_leg=short_leg,long_qty=float(lplan.quantity),short_qty=float(splan.quantity))
        if expected_net < harvest_usdt:return {"status":"waiting","action":"FOCUS_V2_HARVEST_NET_BLOCK","ordersSent":0,"expectedNet":expected_net}
        sprefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|harvest|{state.total_harvested_profit:.8f}|short'.encode()).hexdigest()[:12]}"
        lprefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|harvest|{state.total_harvested_profit:.8f}|long'.encode()).hexdigest()[:12]}"
        sr=_close_v2_leg(client=client,plan=splan,side=PositionSide.SHORT,prefix=sprefix);scq,scp,_,_=_fill(sr);owned=_reduce_owned(owned,ROLE_HEDGE,scq,timestamp_ms)
        lr=_close_v2_leg(client=client,plan=lplan,side=PositionSide.LONG,prefix=lprefix);lcq,lcp,_,_=_fill(lr);owned=_reduce_owned(owned,ROLE_LONG,lcq,timestamp_ms)
        realized_net=min(harvest_available,expected_net)
        fresh_positions=client.position_risk(symbol)
        fresh_long=_row(fresh_positions,symbol,"LONG");fresh_short=_row(fresh_positions,symbol,"SHORT")
        fresh_mark=f((fresh_long or fresh_short or {}).get("markPrice"),mark)
        remaining_long=_notional(fresh_long);remaining_short=_notional(fresh_short)
        target_after=target_hedge_notional(remaining_long,min_bias_usdt=settings.focus_v2_min_net_long_usdt,min_bias_ratio=settings.focus_v2_min_net_long_ratio,max_hedge_ratio=settings.focus_v2_max_hedge_ratio)
        sent=2
        if remaining_short>target_after+max(1.0,remaining_long*.002):
            if order_budget is not None and order_budget<3:return {"status":"reconciling","action":"FOCUS_V2_HARVEST_HEDGE_TRIM_PENDING","ordersSent":2}
            extra=remaining_short-target_after;ep=_plan(client,symbol,fresh_mark,extra,int(f((fresh_short or {}).get("leverage"),settings.leverage)));er=_close_v2_leg(client=client,plan=ep,side=PositionSide.SHORT,prefix=f"{sprefix}-trim");ecq,ecp,_,_=_fill(er);owned=_reduce_owned(owned,ROLE_HEDGE,ecq,timestamp_ms);sent+=1
            fresh_positions=client.position_risk(symbol);fresh_long=_row(fresh_positions,symbol,"LONG");fresh_short=_row(fresh_positions,symbol,"SHORT");remaining_long=_notional(fresh_long);remaining_short=_notional(fresh_short)
        fresh_account=client.account_information();new_equity=f(fresh_account.get("totalMarginBalance"),f(fresh_account.get("totalWalletBalance"),equity))
        state=replace(state,harvest_baseline_equity=new_equity,total_harvested_profit=state.total_harvested_profit+realized_net,last_harvest_profit=realized_net,last_action="PROFIT_HARVEST",last_reason=f"{realized_net:.2f} USDT netto winst geoogst",rehedge_client_id="",rehedge_stop_price=0.0,dca_anchor_price=max(state.dca_anchor_price,fresh_mark))
        ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned],"focusV2History":{"cycleId":state.cycle_id,"cycleStartEquity":state.cycle_start_equity,"equity":new_equity,"harvestBaselineEquity":new_equity,"totalHarvestedProfit":state.total_harvested_profit,"lastHarvestProfit":realized_net,"longNotional":remaining_long,"shortNotional":remaining_short,"netExposure":remaining_long-remaining_short,"grossExposure":remaining_long+remaining_short,"dcaCount":state.dca_count,"cyclePnl":new_equity-state.cycle_start_equity}},merge=True)
        _audit(ref,"FOCUS_V2_PROFIT_HARVEST",cycleId=state.cycle_id,symbol=symbol,requestedProfitUsd=harvest_usdt,realizedNetProfitUsd=realized_net,longReducedQty=lcq,shortReducedQty=scq,remainingLongNotional=remaining_long,remainingShortNotional=remaining_short,remainingHedgeRatio=(remaining_short/remaining_long if remaining_long>0 else 0),equityBefore=equity,equityAfter=new_equity,feesFundingSlippage=costs,newBaselineEquity=new_equity)
        return {"status":"executed","action":"FOCUS_V2_PROFIT_HARVEST","symbol":symbol,"ordersSent":sent,"realizedNetProfitUsd":realized_net}

    # Long DCA has priority on a down move, using the existing Focus ladder/settings.
    anchor=max(state.dca_anchor_price or state.weighted_entry or state.original_entry,mark);state=replace(state,dca_anchor_price=anchor)
    trigger=continuous_dca_trigger(anchor,settings.focus_dca_distance) if (settings.focus_dca_unlimited or state.dca_count<settings.focus_max_dca) else 0.0
    if settings.focus_dca_enabled and trigger>0 and mark<=trigger:
        # A Focus 2.0 DCA is also protected as one pair: LONG DCA + immediate hedge resize.
        if order_budget is not None and order_budget<2:
            return {"status":"budget-exhausted","action":"FOCUS_V2_WAIT_PROTECTED_DCA","reason":"twee orderplaatsen vereist voor LONG DCA + hedge","ordersSent":0}
        if settings.focus_dca_amount_mode=="linear":notional=settings.focus_dca_notional+settings.focus_dca_increment*state.dca_count
        else:
            seq=dca_notional_sequence(amount=settings.focus_dca_notional,multiplier=settings.focus_dca_multiplier,count=state.dca_count+1);notional=seq[-1] if seq else settings.focus_dca_notional
        focus_used=long_notional; remaining=max(0.0,settings.focus_max_budget_usd-focus_used);notional=min(notional,remaining)
        liq=f((long_row or {}).get("liquidationPrice"));liqdist=abs(mark-liq)/mark if liq>0 else 1.0
        cycle_leverage=_resolved_leverage(client,settings,symbol,long_row)
        expected_long_after=long_notional+max(0.0,notional)
        expected_hedge=target_hedge_notional(expected_long_after,min_bias_usdt=settings.focus_v2_min_net_long_usdt,min_bias_ratio=settings.focus_v2_min_net_long_ratio,max_hedge_ratio=settings.focus_v2_max_hedge_ratio)
        expected_hedge_gap=max(0.0,expected_hedge-short_notional)
        required_margin=(max(0.0,notional)+expected_hedge_gap)/max(1,cycle_leverage)
        if notional>0 and required_margin<=available and maint<settings.emergency_margin_ratio and liqdist>=.05:
            plan=_plan(client,symbol,mark,notional,cycle_leverage);prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|dca|{state.dca_count}'.encode()).hexdigest()[:12]}"
            result=execute_leg_once(client,plan,side=PositionSide.LONG,action="OPEN",id_prefix=prefix,confirm=True);q,p,cid,oid=_fill(result)
            actual_long_after=long_notional+q*p
            hedge_target_after=target_hedge_notional(actual_long_after,min_bias_usdt=settings.focus_v2_min_net_long_usdt,min_bias_ratio=settings.focus_v2_min_net_long_ratio,max_hedge_ratio=settings.focus_v2_max_hedge_ratio)
            hedge_gap=max(0.0,hedge_target_after-short_notional)
            try:
                hq=hp=0.0;hcid=hoid=""
                if hedge_gap>max(1.0,actual_long_after*.002):
                    hplan=_plan(client,symbol,p,hedge_gap,cycle_leverage);hprefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|dcahedge|{state.dca_count}'.encode()).hexdigest()[:12]}"
                    hresult=execute_leg_once(client,hplan,side=PositionSide.SHORT,action="OPEN",id_prefix=hprefix,confirm=True,new_position_leverage=cycle_leverage);hq,hp,hcid,hoid=_fill(hresult)
            except Exception:
                # Roll back exactly the just-added LONG quantity if protection cannot be confirmed.
                rplan=_plan(client,symbol,p,q*p,cycle_leverage);rprefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|dcarollback|{state.dca_count}'.encode()).hexdigest()[:12]}"
                execute_leg_once(client,rplan,side=PositionSide.LONG,action="CLOSE",id_prefix=rprefix,confirm=True)
                _audit(ref,"FOCUS_V2_PROTECTED_DCA_ROLLBACK",cycleId=state.cycle_id,symbol=symbol,dcaNotional=q*p,reason="hedge na DCA kon niet bevestigd worden")
                raise
            owned=_upsert(owned,settings=settings,state=state,role=ROLE_LONG,side="LONG",q=q,p=p,cid=cid,oid=oid,is_dca=True,ts=timestamp_ms)
            if hq>0:owned=_upsert(owned,settings=settings,state=state,role=ROLE_HEDGE,side="SHORT",q=hq,p=hp,cid=hcid,oid=hoid,is_dca=False,ts=timestamp_ms)
            new_qty=long_qty+q;new_entry=((long_qty*entry)+(q*p))/new_qty if new_qty else p
            state=replace(state,dca_count=state.dca_count+1,weighted_entry=new_entry,last_action="DCA_PROTECTED",last_reason="LONG DCA + hedge opnieuw op actuele LONG gezet",recent_low=min(state.recent_low,p),dca_anchor_price=p)
            ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned]},merge=True)
            _audit(ref,"FOCUS_V2_DCA_PROTECTED",cycleId=state.cycle_id,symbol=symbol,dcaCount=state.dca_count,longNotional=actual_long_after,targetShortNotional=hedge_target_after,hedgeAddedNotional=hq*hp)
            return {"status":"executed","action":"FOCUS_V2_DCA_PROTECTED","symbol":symbol,"ordersSent":2 if hq>0 else 1}

    # Reconcile protective hedge to current LONG. This is why old start-size is never used.
    hedge_target=target_hedge_notional(long_notional,min_bias_usdt=settings.focus_v2_min_net_long_usdt,min_bias_ratio=settings.focus_v2_min_net_long_ratio,max_hedge_ratio=settings.focus_v2_max_hedge_ratio)
    recovery=recovery_confirmed(mark=mark,recent_low=state.recent_low,bollinger_middle=mid,equity=equity,cycle_start_equity=state.cycle_start_equity,rebound_pct=settings.focus_v2_recovery_rebound_pct,portfolio_ratio=settings.focus_v2_portfolio_recovery_ratio,require_middle=settings.focus_v2_require_bollinger_middle)
    full=full_recovery(equity=equity,cycle_start_equity=state.cycle_start_equity,ratio=settings.focus_v2_portfolio_recovery_ratio)
    if recovery and short_qty>0:
        q=release_quantity(short_qty,settings.focus_v2_release_ratio,full);plan=_plan(client,symbol,mark,q*mark,int(f((short_row or {}).get("leverage"),settings.leverage)));prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|release|{state.release_stage}'.encode()).hexdigest()[:12]}";result=_close_v2_leg(client=client,plan=plan,side=PositionSide.SHORT,prefix=prefix);cq,cp,_,_=_fill(result);short_entry=f((short_row or {}).get("entryPrice"));realized=(short_entry-cp)*cq;owned=_reduce_owned(owned,ROLE_HEDGE,cq,timestamp_ms);new_stage=state.release_stage+1;state=replace(state,release_stage=new_stage,realized_hedge_pnl=state.realized_hedge_pnl+realized,last_action="HEDGE_RELEASE",last_reason="5m herstel + portfolio recovery",recovery_high=max(state.recovery_high,mark));released_notional=cq*cp
        # The amount just released is protected by an exchange-side STOP_MARKET. It can be re-opened before the next scanner tick.
        rules=ContractRules.from_exchange_info(next(x for x in client.public_exchange_info().get("symbols",[]) if str(x.get("symbol","")).upper()==symbol));reh_q=rules.market_quantity(Decimal(str(released_notional/mark)),Decimal(str(mark))) if not full else Decimal("0")
        if reh_q>0:state=_arm_rehedge(client=client,state=state,settings=settings,mark=mark,quantity=float(reh_q),reserve_order=reserve_order)
        else:_cancel_rehedge(client,state);state=replace(state,rehedge_client_id="",rehedge_stop_price=0)
        ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned],"focusV2History":{"cycleId":state.cycle_id,"cycleStartEquity":state.cycle_start_equity,"equity":equity,"longNotional":long_notional,"shortNotional":max(0,short_notional-released_notional),"netExposure":long_notional-max(0,short_notional-released_notional),"dcaCount":state.dca_count,"releaseStage":state.release_stage,"rehedgeTrigger":state.rehedge_stop_price,"realizedHedgePnl":state.realized_hedge_pnl,"cyclePnl":equity-state.cycle_start_equity}},merge=True);_audit(ref,"FOCUS_V2_HEDGE_RELEASE",cycleId=state.cycle_id,symbol=symbol,releaseNotional=released_notional,realizedHedgePnl=realized,cyclePnl=equity-state.cycle_start_equity,rehedgeTrigger=state.rehedge_stop_price,fullRelease=full);return {"status":"executed","action":"FOCUS_V2_HEDGE_RELEASE","symbol":symbol,"ordersSent":2 if reh_q>0 else 1,"hedgeRealizedPnl":realized,"cyclePnl":equity-state.cycle_start_equity}

    # No recovery: make sure hedge is large enough for current LONG, unless an already-armed stop covers the released tranche.
    armed_qty=0.0
    for o in open_orders or []:
        if isinstance(o,dict) and str(o.get("symbol","")).upper()==symbol and str(o.get("clientOrderId","")).startswith(REHEDGE_PREFIX):armed_qty+=abs(f(o.get("origQty",o.get("quantity"))))*mark
    gap=max(0.0,hedge_target-short_notional-armed_qty)
    if gap>max(1.0,long_notional*.002):
        cycle_leverage=_resolved_leverage(client,settings,symbol,long_row);plan=_plan(client,symbol,mark,gap,cycle_leverage);prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|hedge|{state.dca_count}|{round(gap,2)}'.encode()).hexdigest()[:12]}";result=execute_leg_once(client,plan,side=PositionSide.SHORT,action="OPEN",id_prefix=prefix,confirm=True);q,p,cid,oid=_fill(result);owned=_upsert(owned,settings=settings,state=state,role=ROLE_HEDGE,side="SHORT",q=q,p=p,cid=cid,oid=oid,is_dca=False,ts=timestamp_ms);state=replace(state,last_action="HEDGE_GROW",last_reason="hedge opnieuw berekend op actuele totale LONG");ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned]},merge=True);_audit(ref,"FOCUS_V2_HEDGE_GROW",cycleId=state.cycle_id,symbol=symbol,longNotional=long_notional,targetShortNotional=hedge_target);return {"status":"executed","action":"FOCUS_V2_HEDGE_GROW","symbol":symbol,"ordersSent":1}

    rebound_price=state.recent_low*(1+max(0.0,settings.focus_v2_recovery_rebound_pct)) if state.recent_low>0 else 0.0
    price_met=mark>=rebound_price if rebound_price>0 else False
    middle_met=(not settings.focus_v2_require_bollinger_middle) or (mid>0 and mark>=mid)
    configured_portfolio_met=state.cycle_start_equity>0 and equity>=state.cycle_start_equity*settings.focus_v2_portfolio_recovery_ratio
    portfolio_gate_met=configured_portfolio_met or (state.cycle_start_equity>0 and equity>=state.cycle_start_equity*.95)
    ref.set({"focusV2State":state_map(replace(state,last_action="HOLD",last_reason="bescherming in balans")),"phase":"FOCUS_V2_LIVE","lastReason":"FOCUS_V2_HOLD","focusV2History":{"cycleId":state.cycle_id,"cycleStartEquity":state.cycle_start_equity,"equity":equity,"longNotional":long_notional,"shortNotional":short_notional,"netExposure":long_notional-short_notional,"grossExposure":long_notional+short_notional,"dcaCount":state.dca_count,"rehedgeTrigger":state.rehedge_stop_price,"rehedgeArmed":bool(state.rehedge_client_id and state.rehedge_stop_price>0),"cyclePnl":equity-state.cycle_start_equity,"currentPrice":mark,"longEntry":entry,"shortEntry":f((short_row or {}).get("entryPrice")),"bollinger5mMiddle":mid,"recoveryReboundPrice":rebound_price,"recoveryPriceMet":price_met,"bollinger5mConfirmed":middle_met,"portfolioRecoveryTarget":state.cycle_start_equity*settings.focus_v2_portfolio_recovery_ratio if state.cycle_start_equity>0 else 0.0,"portfolioRecoveryMet":portfolio_gate_met,"configuredPortfolioRecoveryMet":configured_portfolio_met,"shortReleaseRatio":settings.focus_v2_release_ratio,"shortReleaseReady":bool(price_met and middle_met and portfolio_gate_met),"dcaAnchorPrice":state.dca_anchor_price,"nextDcaTrigger":continuous_dca_trigger(state.dca_anchor_price,settings.focus_dca_distance),"harvestBaselineEquity":state.harvest_baseline_equity,"profitSinceHarvest":equity-state.harvest_baseline_equity,"profitTriggerUsdt":settings.focus_v2_profit_trigger_usdt,"profitHarvestUsdt":settings.focus_v2_profit_harvest_usdt,"profitRemainingUsdt":(max(0.0,settings.focus_v2_profit_trigger_usdt-(equity-state.harvest_baseline_equity)) if settings.focus_v2_profit_trigger_usdt>0 else 0.0),"totalHarvestedProfit":state.total_harvested_profit,"lastHarvestProfit":state.last_harvest_profit}},merge=True)
    return {"status":"waiting","action":"FOCUS_V2_HOLD","symbol":symbol,"ordersSent":0,"cyclePnl":equity-state.cycle_start_equity}
