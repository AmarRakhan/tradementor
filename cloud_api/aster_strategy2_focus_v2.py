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
RECOVERY_MODEL_FAST=2
RECOVERY_STAGE_PROGRESS=(0.22,0.48,0.72,0.95)

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
    recovery_model_version:int=1; released_short_qty:float=0.0; armed_rehedge_qty:float=0.0
    last_release_price:float=0.0; next_release_price:float=0.0; recovery_progress_ratio:float=0.0; last_rehedge_price:float=0.0
    rehedge_client_ids:tuple[str,...]=()


def state_from(raw:Any)->FocusV2State:
    x=raw if isinstance(raw,dict) else {}
    def g(c,s,d=None):return x[c] if c in x else x.get(s,d)
    ids=g("rehedgeClientIds","rehedge_client_ids",())
    if not isinstance(ids,(list,tuple)):ids=()
    return FocusV2State(
        cycle_id=str(g("cycleId","cycle_id","") or ""),symbol=str(g("symbol","symbol","") or "").upper(),
        cycle_start_equity=f(g("cycleStartEquity","cycle_start_equity",0)),opened_at_ms=int(f(g("openedAt","opened_at_ms",0))),
        original_entry=f(g("originalEntry","original_entry",0)),weighted_entry=f(g("weightedEntry","weighted_entry",0)),dca_count=int(f(g("dcaCount","dca_count",0))),
        recent_low=f(g("recentLow","recent_low",0)),recovery_high=f(g("recoveryHigh","recovery_high",0)),release_stage=int(f(g("releaseStage","release_stage",0))),
        rehedge_client_id=str(g("rehedgeClientId","rehedge_client_id","") or ""),rehedge_stop_price=f(g("rehedgeStopPrice","rehedge_stop_price",0)),
        realized_hedge_pnl=f(g("realizedHedgePnl","realized_hedge_pnl",0)),harvest_baseline_equity=f(g("harvestBaselineEquity","harvest_baseline_equity",g("cycleStartEquity","cycle_start_equity",0))),
        total_harvested_profit=f(g("totalHarvestedProfit","total_harvested_profit",0)),last_harvest_profit=f(g("lastHarvestProfit","last_harvest_profit",0)),
        dca_anchor_price=f(g("dcaAnchorPrice","dca_anchor_price",g("weightedEntry","weighted_entry",g("originalEntry","original_entry",0)))),last_action=str(g("lastAction","last_action","IDLE") or "IDLE"),last_reason=str(g("lastReason","last_reason","") or ""),
        recovery_model_version=int(f(g("recoveryModelVersion","recovery_model_version",1),1)),released_short_qty=f(g("releasedShortQty","released_short_qty",0)),armed_rehedge_qty=f(g("armedRehedgeQty","armed_rehedge_qty",0)),
        last_release_price=f(g("lastReleasePrice","last_release_price",0)),next_release_price=f(g("nextReleasePrice","next_release_price",0)),recovery_progress_ratio=f(g("recoveryProgressRatio","recovery_progress_ratio",0)),last_rehedge_price=f(g("lastRehedgePrice","last_rehedge_price",0)),
        rehedge_client_ids=tuple(str(v) for v in ids if v),
    )

def state_map(s:FocusV2State)->dict[str,Any]:
    # Compatibility boundary: behavior-v1 cycles keep the exact legacy persisted shape.
    # This prevents deployment from migrating or version-stamping an already-active cycle.
    out={"cycleId":s.cycle_id,"symbol":s.symbol,"cycleStartEquity":s.cycle_start_equity,"openedAt":s.opened_at_ms,"originalEntry":s.original_entry,"weightedEntry":s.weighted_entry,"dcaCount":s.dca_count,
        "recentLow":s.recent_low,"recoveryHigh":s.recovery_high,"releaseStage":s.release_stage,"rehedgeClientId":s.rehedge_client_id,"rehedgeStopPrice":s.rehedge_stop_price,
        "realizedHedgePnl":s.realized_hedge_pnl,"harvestBaselineEquity":s.harvest_baseline_equity,"totalHarvestedProfit":s.total_harvested_profit,"lastHarvestProfit":s.last_harvest_profit,"dcaAnchorPrice":s.dca_anchor_price,
        "lastAction":s.last_action,"lastReason":s.last_reason}
    if s.recovery_model_version>=RECOVERY_MODEL_FAST:
        out.update({"recoveryModelVersion":s.recovery_model_version,"releasedShortQty":s.released_short_qty,"armedRehedgeQty":s.armed_rehedge_qty,"lastReleasePrice":s.last_release_price,
            "nextReleasePrice":s.next_release_price,"recoveryProgressRatio":s.recovery_progress_ratio,"lastRehedgePrice":s.last_rehedge_price,"rehedgeClientIds":list(s.rehedge_client_ids)})
    return out

def target_hedge_notional(long_notional:float,*,min_bias_usdt:float,min_bias_ratio:float,max_hedge_ratio:float)->float:
    long=max(0.0,long_notional);bias=max(0.0,min_bias_usdt,long*max(0.0,min_bias_ratio))
    return max(0.0,min(long*max(0.0,min(max_hedge_ratio,.999999)),long-bias))


def recovery_progress(mark:float,recent_low:float,long_break_even:float)->float:
    if mark<=0 or recent_low<=0:return 0.0
    if long_break_even<=recent_low:return 1.0 if mark>=max(long_break_even,recent_low) else 0.0
    return max(0.0,(mark-recent_low)/(long_break_even-recent_low))

def recovery_stage_for_progress(progress:float)->int:
    stage=0
    for idx,threshold in enumerate(RECOVERY_STAGE_PROGRESS,1):
        if progress+1e-12>=threshold:stage=idx
    return stage

def recovery_remaining_ratio(stage:int,release_ratio:float)->float:
    if stage>=len(RECOVERY_STAGE_PROGRESS):return 0.0
    return (1-max(0.0,min(1.0,release_ratio)))**max(0,stage)

def recovery_stage_price(recent_low:float,long_break_even:float,stage:int)->float:
    if recent_low<=0 or long_break_even<=recent_low or stage<1 or stage>len(RECOVERY_STAGE_PROGRESS):return 0.0
    return recent_low+(long_break_even-recent_low)*RECOVERY_STAGE_PROGRESS[stage-1]

def recovery_status(stage:int,progress:float)->str:
    if stage<=0:return "BODEM GEVORMD" if progress>0 else "DALING · VOLLEDIG BESCHERMD"
    if stage==1:return "HERSTEL START · SHORT WORDT LOSGELATEN"
    if stage==2:return "RECOVERY 2 · HEDGE VERDER OMLAAG"
    if stage==3:return "BIJNA BREAK-EVEN · LONG KRIJGT RUIMTE"
    return "BOVEN BREAK-EVEN · HEDGE VRIJ"

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

def _rehedge_ids(state:FocusV2State)->tuple[str,...]:
    return tuple(dict.fromkeys((*state.rehedge_client_ids,*((state.rehedge_client_id,) if state.rehedge_client_id else ()))))


def _sync_hedge_owned(owned:list[OwnedLeg],*,settings:Strategy2Config,state:FocusV2State,short_qty:float,short_entry:float,ts:int)->list[OwnedLeg]:
    from dataclasses import replace
    old=_v2(owned,ROLE_HEDGE)
    if short_qty<=1e-12:
        return [x for x in owned if x is not old] if old else owned
    if old is None:
        leg=OwnedLeg(settings.strategy_id,"strategy2",state.symbol,"SHORT",state.cycle_id,settings.version,short_qty,short_entry,0,ROLE_HEDGE,(),(),(),ts,last_order_at_ms=ts)
        return [*owned,leg]
    if abs(old.quantity-short_qty)<=1e-10 and (short_entry<=0 or abs(old.weighted_entry-short_entry)<=1e-10):return owned
    new=replace(old,quantity=short_qty,weighted_entry=short_entry or old.weighted_entry,last_order_at_ms=ts)
    return [new if x is old else x for x in owned]

def _cancel_rehedge(client:Any,state:FocusV2State)->None:
    if not state.symbol:return
    for cid in _rehedge_ids(state):
        try:client.cancel_order(state.symbol,client_order_id=cid)
        except Exception:pass

def _rehedge_orders(open_orders:list[dict[str,Any]]|None,symbol:str)->list[dict[str,Any]]:
    return [o for o in (open_orders or []) if isinstance(o,dict) and str(o.get("symbol","")).upper()==symbol.upper() and str(o.get("clientOrderId","")).startswith(REHEDGE_PREFIX)]

def _open_rehedge_qty(open_orders:list[dict[str,Any]]|None,symbol:str)->float:
    return sum(abs(f(o.get("origQty",o.get("quantity")))) for o in _rehedge_orders(open_orders,symbol))

def _open_rehedge_stage(open_orders:list[dict[str,Any]]|None,symbol:str)->int:
    stage=0
    for row in _rehedge_orders(open_orders,symbol):
        cid=str(row.get("clientOrderId","") or "")
        try: stage=max(stage,int(cid[len(REHEDGE_PREFIX):].split("-",1)[0]))
        except (ValueError,IndexError): pass
    return stage


def _arm_rehedge_legacy(*,client:Any,state:FocusV2State,settings:Strategy2Config,mark:float,quantity:float,reserve_order:Callable|None)->FocusV2State:
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

def _arm_rehedge(*,client:Any,state:FocusV2State,settings:Strategy2Config,mark:float,quantity:float,reserve_order:Callable|None)->FocusV2State:
    from dataclasses import replace
    if quantity<=0:return state
    stop=rehedge_stop(mark,settings.focus_v2_rehedge_setback_pct)
    cid=(f"{REHEDGE_PREFIX}{state.release_stage}-"+hashlib.sha256(f"{state.cycle_id}|{state.release_stage}|{state.released_short_qty:.8f}|{stop:.8f}|{quantity:.8f}".encode()).hexdigest()[:18])[:36]
    if cid in _rehedge_ids(state):return state
    intent=AsterOrderIntent(cid,state.symbol,PositionSide.SHORT,Decimal(str(quantity)),"OPEN")
    if reserve_order:reserve_order(intent,{"kind":"FOCUS_V2_REHEDGE_STOP","cycleId":state.cycle_id,"riskReducing":True,"marginUsd":float(quantity)*mark/max(1,settings.leverage)})
    payload={"symbol":state.symbol,"side":"SELL","positionSide":"SHORT","type":"STOP_MARKET","quantity":format(Decimal(str(quantity)),"f"),"stopPrice":format(Decimal(str(stop)),"f"),"workingType":"MARK_PRICE","newClientOrderId":cid}
    response=client.signed_request("POST","/fapi/v3/order",payload)
    if not isinstance(response,dict) or response.get("orderId") is None:raise RuntimeError("Aster bevestigde Focus 2.0 re-hedge trigger niet")
    ids=tuple(dict.fromkeys((*_rehedge_ids(state),cid)))
    return replace(state,rehedge_client_id=cid,rehedge_client_ids=ids,rehedge_stop_price=stop,armed_rehedge_qty=state.armed_rehedge_qty+float(quantity))

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
        state=FocusV2State(cycle,symbol,equity,timestamp_ms,0,0,0,mark,mark,0,"",0,0,equity,0,0,mark,"OPEN_PENDING","nieuwe schone Focus 2.0 cycle",recovery_model_version=RECOVERY_MODEL_FAST)
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
    if state.recovery_model_version>=RECOVERY_MODEL_FAST:owned=_sync_hedge_owned(owned,settings=settings,state=state,short_qty=short_qty,short_entry=f((short_row or {}).get("entryPrice")),ts=timestamp_ms)
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
        if state.recovery_model_version>=RECOVERY_MODEL_FAST:
            state=replace(state,rehedge_client_ids=(),armed_rehedge_qty=0.0)
            backup_notional=max(0.0,target_after-remaining_short)
            backup_qty=backup_notional/max(fresh_mark,1e-12)
            if backup_notional>max(1.0,remaining_long*.002):
                state=_arm_rehedge(client=client,state=state,settings=settings,mark=(state.last_release_price or fresh_mark),quantity=backup_qty,reserve_order=reserve_order);sent+=1
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
        armed_before_dca=(_open_rehedge_qty(open_orders,symbol)*mark if state.recovery_model_version>=RECOVERY_MODEL_FAST else 0.0);expected_hedge_gap=max(0.0,expected_hedge-short_notional-armed_before_dca)
        required_margin=(max(0.0,notional)+expected_hedge_gap)/max(1,cycle_leverage)
        if notional>0 and required_margin<=available and maint<settings.emergency_margin_ratio and liqdist>=.05:
            plan=_plan(client,symbol,mark,notional,cycle_leverage);prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|dca|{state.dca_count}'.encode()).hexdigest()[:12]}"
            result=execute_leg_once(client,plan,side=PositionSide.LONG,action="OPEN",id_prefix=prefix,confirm=True);q,p,cid,oid=_fill(result)
            actual_long_after=long_notional+q*p
            hedge_target_after=target_hedge_notional(actual_long_after,min_bias_usdt=settings.focus_v2_min_net_long_usdt,min_bias_ratio=settings.focus_v2_min_net_long_ratio,max_hedge_ratio=settings.focus_v2_max_hedge_ratio)
            fresh_after_long=client.position_risk(symbol) if state.recovery_model_version>=RECOVERY_MODEL_FAST else positions;fresh_short_after_long=_row(fresh_after_long,symbol,"SHORT");short_after_long=_notional(fresh_short_after_long) if state.recovery_model_version>=RECOVERY_MODEL_FAST else short_notional;armed_before_dca=(_open_rehedge_qty(open_orders,symbol)*p if state.recovery_model_version>=RECOVERY_MODEL_FAST else 0.0);hedge_gap=max(0.0,hedge_target_after-short_after_long-armed_before_dca)
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

    # Reconcile protective hedge to current LONG. Existing cycles stay behavior-v1; new cycles use staged fast recovery.
    hedge_target=target_hedge_notional(long_notional,min_bias_usdt=settings.focus_v2_min_net_long_usdt,min_bias_ratio=settings.focus_v2_min_net_long_ratio,max_hedge_ratio=settings.focus_v2_max_hedge_ratio)
    if state.recovery_model_version < RECOVERY_MODEL_FAST:
        recovery=recovery_confirmed(mark=mark,recent_low=state.recent_low,bollinger_middle=mid,equity=equity,cycle_start_equity=state.cycle_start_equity,rebound_pct=settings.focus_v2_recovery_rebound_pct,portfolio_ratio=settings.focus_v2_portfolio_recovery_ratio,require_middle=settings.focus_v2_require_bollinger_middle)
        full=full_recovery(equity=equity,cycle_start_equity=state.cycle_start_equity,ratio=settings.focus_v2_portfolio_recovery_ratio)
        if recovery and short_qty>0:
            q=release_quantity(short_qty,settings.focus_v2_release_ratio,full);plan=_plan(client,symbol,mark,q*mark,int(f((short_row or {}).get("leverage"),settings.leverage)));prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|release|{state.release_stage}'.encode()).hexdigest()[:12]}";result=_close_v2_leg(client=client,plan=plan,side=PositionSide.SHORT,prefix=prefix);cq,cp,_,_=_fill(result);short_entry=f((short_row or {}).get("entryPrice"));realized=(short_entry-cp)*cq;owned=_reduce_owned(owned,ROLE_HEDGE,cq,timestamp_ms);new_stage=state.release_stage+1;state=replace(state,release_stage=new_stage,realized_hedge_pnl=state.realized_hedge_pnl+realized,last_action="HEDGE_RELEASE",last_reason="5m herstel + portfolio recovery",recovery_high=max(state.recovery_high,mark));released_notional=cq*cp
            rules=ContractRules.from_exchange_info(next(x for x in client.public_exchange_info().get("symbols",[]) if str(x.get("symbol","")).upper()==symbol));reh_q=rules.market_quantity(Decimal(str(released_notional/mark)),Decimal(str(mark))) if not full else Decimal("0")
            if reh_q>0:state=_arm_rehedge_legacy(client=client,state=state,settings=settings,mark=mark,quantity=float(reh_q),reserve_order=reserve_order)
            else:_cancel_rehedge(client,state);state=replace(state,rehedge_client_id="",rehedge_stop_price=0)
            ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned],"focusV2History":{"cycleId":state.cycle_id,"cycleStartEquity":state.cycle_start_equity,"equity":equity,"longNotional":long_notional,"shortNotional":max(0,short_notional-released_notional),"netExposure":long_notional-max(0,short_notional-released_notional),"dcaCount":state.dca_count,"releaseStage":state.release_stage,"rehedgeTrigger":state.rehedge_stop_price,"realizedHedgePnl":state.realized_hedge_pnl,"cyclePnl":equity-state.cycle_start_equity}},merge=True);_audit(ref,"FOCUS_V2_HEDGE_RELEASE",cycleId=state.cycle_id,symbol=symbol,releaseNotional=released_notional,realizedHedgePnl=realized,cyclePnl=equity-state.cycle_start_equity,rehedgeTrigger=state.rehedge_stop_price,fullRelease=full);return {"status":"executed","action":"FOCUS_V2_HEDGE_RELEASE","symbol":symbol,"ordersSent":2 if reh_q>0 else 1,"hedgeRealizedPnl":realized,"cyclePnl":equity-state.cycle_start_equity}
    else:
        armed_live_qty=_open_rehedge_qty(open_orders,symbol)
        armed_stage=_open_rehedge_stage(open_orders,symbol)
        target_qty=hedge_target/max(mark,1e-12)
        state=replace(state,armed_rehedge_qty=armed_live_qty,release_stage=max(state.release_stage,armed_stage))
        progress=recovery_progress(mark,state.recent_low,entry)
        desired_stage=recovery_stage_for_progress(progress)
        next_stage=min(len(RECOVERY_STAGE_PROGRESS),state.release_stage+1)
        state=replace(state,recovery_progress_ratio=progress,next_release_price=recovery_stage_price(state.recent_low,entry,next_stage),recovery_high=max(state.recovery_high,mark))
        setback_hit=state.last_release_price>0 and mark<=state.last_release_price*(1-max(0.0001,settings.focus_v2_rehedge_setback_pct))
        tolerance_qty=max(1e-10,max(1.0,long_notional*.002)/max(mark,1e-12))
        desired_armed_qty=max(0.0,target_qty-short_qty)
        if armed_live_qty>desired_armed_qty+tolerance_qty:
            old_orders=_rehedge_orders(open_orders,symbol)
            replacement=replace(state,rehedge_client_id="",rehedge_client_ids=(),rehedge_stop_price=0.0,armed_rehedge_qty=0.0)
            sent=0
            if desired_armed_qty>tolerance_qty:
                replacement=_arm_rehedge(client=client,state=replacement,settings=settings,mark=(state.last_release_price or mark),quantity=desired_armed_qty,reserve_order=reserve_order);sent=1
            for row in old_orders:
                cid=str(row.get("clientOrderId","") or "")
                if cid and cid!=replacement.rehedge_client_id:
                    try:client.cancel_order(symbol,client_order_id=cid)
                    except Exception:pass
            state=replace(replacement,last_action="REHEDGE_RECONCILED",last_reason="exchange-side protection aangepast aan geldig target")
            ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned]},merge=True)
            _audit(ref,"FOCUS_V2_REHEDGE_RECONCILED",cycleId=state.cycle_id,symbol=symbol,targetQty=target_qty,currentShortQty=short_qty,armedQty=desired_armed_qty)
            return {"status":"executed","action":"FOCUS_V2_REHEDGE_RECONCILED","symbol":symbol,"ordersSent":sent}
        if short_qty>target_qty+tolerance_qty:
            excess_qty=short_qty-target_qty
            plan=_plan(client,symbol,mark,excess_qty*mark,int(f((short_row or {}).get("leverage"),settings.leverage)))
            result=_close_v2_leg(client=client,plan=plan,side=PositionSide.SHORT,prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|overhedge|{short_qty:.8f}|{target_qty:.8f}'.encode()).hexdigest()[:12]}")
            cq,_,_,_=_fill(result);owned=_reduce_owned(owned,ROLE_HEDGE,cq,timestamp_ms)
            state=replace(state,last_action="HEDGE_OVERPROTECTION_TRIM",last_reason="SHORT boven geldig protection-target getrimd")
            ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned]},merge=True)
            _audit(ref,"FOCUS_V2_OVERHEDGE_TRIM",cycleId=state.cycle_id,symbol=symbol,trimQty=cq,targetQty=target_qty)
            return {"status":"executed","action":"FOCUS_V2_OVERHEDGE_TRIM","symbol":symbol,"ordersSent":1}
        if setback_hit and short_qty>=target_qty-tolerance_qty and armed_live_qty<=tolerance_qty:
            state=replace(state,release_stage=0,recovery_high=mark,last_rehedge_price=mark,last_action="REHEDGE_RESTORED",last_reason="TERUGVAL · HEDGE HERSTELD",rehedge_client_id="",rehedge_client_ids=(),rehedge_stop_price=0.0,armed_rehedge_qty=0.0)
            desired_stage=0
        middle_ok=(not settings.focus_v2_require_bollinger_middle) or (mid>0 and mark>=mid)
        configured_equity_floor=state.cycle_start_equity*min(0.95,max(0.50,settings.focus_v2_portfolio_recovery_ratio-.15)) if state.cycle_start_equity>0 else 0.0
        equity_context_ok=state.cycle_start_equity<=0 or equity>=configured_equity_floor
        if desired_stage>state.release_stage and short_qty>0 and middle_ok and equity_context_ok:
            remaining_ratio=recovery_remaining_ratio(desired_stage,settings.focus_v2_release_ratio)
            desired_short_qty=max(0.0,target_qty*remaining_ratio)
            release_raw=max(0.0,short_qty-desired_short_qty)
            if release_raw>tolerance_qty:
                plan=_plan(client,symbol,mark,release_raw*mark,int(f((short_row or {}).get("leverage"),settings.leverage)))
                planned_qty=float(plan.quantity);armed_before=_open_rehedge_qty(open_orders,symbol)
                expected_after=max(0.0,short_qty-planned_qty)
                backup_qty=min(planned_qty,max(0.0,target_qty-expected_after-armed_before))
                # Safety ordering: exchange-side fallback is confirmed before SHORT is released.
                armed_state=state;sent=0;new_backup_cid=""
                if backup_qty>tolerance_qty:
                    arm_seed=replace(state,release_stage=desired_stage,released_short_qty=state.released_short_qty+planned_qty)
                    armed_state=_arm_rehedge(client=client,state=arm_seed,settings=settings,mark=mark,quantity=backup_qty,reserve_order=reserve_order);sent=1;new_backup_cid=armed_state.rehedge_client_id
                prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|fastrelease|{desired_stage}'.encode()).hexdigest()[:12]}"
                try:
                    result=_close_v2_leg(client=client,plan=plan,side=PositionSide.SHORT,prefix=prefix);cq,cp,_,_=_fill(result)
                except Exception:
                    if new_backup_cid:
                        try:client.cancel_order(symbol,client_order_id=new_backup_cid)
                        except Exception:pass
                    raise
                short_entry=f((short_row or {}).get("entryPrice"));realized=(short_entry-cp)*cq;owned=_reduce_owned(owned,ROLE_HEDGE,cq,timestamp_ms)
                current_after=max(0.0,short_qty-cq)
                state=replace(armed_state,release_stage=desired_stage,released_short_qty=state.released_short_qty+cq,realized_hedge_pnl=state.realized_hedge_pnl+realized,last_release_price=cp,last_action=f"RECOVERY_{desired_stage}_RELEASE",last_reason=recovery_status(desired_stage,progress));sent+=1
                next_release=recovery_stage_price(state.recent_low,entry,min(len(RECOVERY_STAGE_PROGRESS),state.release_stage+1)) if state.release_stage<len(RECOVERY_STAGE_PROGRESS) else 0.0
                next_remaining=recovery_remaining_ratio(min(len(RECOVERY_STAGE_PROGRESS),state.release_stage+1),settings.focus_v2_release_ratio)
                next_release_qty=max(0.0,current_after-target_qty*next_remaining) if state.release_stage<len(RECOVERY_STAGE_PROGRESS) else 0.0
                history={"cycleId":state.cycle_id,"cycleStartEquity":state.cycle_start_equity,"equity":equity,"longNotional":long_notional,"shortNotional":current_after*mark,"targetShortNotional":hedge_target,"netExposure":long_notional-current_after*mark,"grossExposure":long_notional+current_after*mark,"hedgeRatio":current_after*mark/long_notional if long_notional>0 else 0.0,"dcaCount":state.dca_count,"recoveryStage":state.release_stage,"recoveryProgressRatio":progress,"recoveryLow":state.recent_low,"recoveryHigh":state.recovery_high,"longBreakEven":entry,"nextReleasePrice":next_release,"nextReleaseQty":next_release_qty,"releasedShortQty":state.released_short_qty,"armedRehedgeQty":state.armed_rehedge_qty,"rehedgeTrigger":state.rehedge_stop_price,"rehedgeArmed":state.armed_rehedge_qty>0,"recoveryModelVersion":state.recovery_model_version,"cyclePnl":equity-state.cycle_start_equity}
                ref.set({"focusV2State":state_map(replace(state,next_release_price=next_release)),"ownedLegs":[owned_to_mapping(x) for x in owned],"focusV2History":history},merge=True)
                _audit(ref,"FOCUS_V2_FAST_HEDGE_RELEASE",cycleId=state.cycle_id,symbol=symbol,recoveryStage=desired_stage,recoveryProgressRatio=progress,releaseQty=cq,armedRehedgeQty=state.armed_rehedge_qty,rehedgeTrigger=state.rehedge_stop_price,fullRelease=(desired_stage>=len(RECOVERY_STAGE_PROGRESS)))
                return {"status":"executed","action":f"FOCUS_V2_RECOVERY_{desired_stage}_RELEASE","symbol":symbol,"ordersSent":sent,"recoveryStage":desired_stage,"recoveryProgressRatio":progress}

    # No recovery: make sure hedge is large enough for current LONG, unless an already-armed stop covers the released tranche.
    armed_qty=_open_rehedge_qty(open_orders,symbol)*mark
    gap=max(0.0,hedge_target-short_notional-armed_qty)
    if gap>max(1.0,long_notional*.002):
        cycle_leverage=_resolved_leverage(client,settings,symbol,long_row);plan=_plan(client,symbol,mark,gap,cycle_leverage);prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|hedge|{state.dca_count}|{round(gap,2)}'.encode()).hexdigest()[:12]}";result=execute_leg_once(client,plan,side=PositionSide.SHORT,action="OPEN",id_prefix=prefix,confirm=True);q,p,cid,oid=_fill(result);owned=_upsert(owned,settings=settings,state=state,role=ROLE_HEDGE,side="SHORT",q=q,p=p,cid=cid,oid=oid,is_dca=False,ts=timestamp_ms);state=replace(state,last_action="HEDGE_GROW",last_reason="hedge opnieuw berekend op actuele totale LONG");ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned]},merge=True);_audit(ref,"FOCUS_V2_HEDGE_GROW",cycleId=state.cycle_id,symbol=symbol,longNotional=long_notional,targetShortNotional=hedge_target);return {"status":"executed","action":"FOCUS_V2_HEDGE_GROW","symbol":symbol,"ordersSent":1}

    rebound_price=state.recent_low*(1+max(0.0,settings.focus_v2_recovery_rebound_pct)) if state.recent_low>0 else 0.0
    price_met=mark>=rebound_price if rebound_price>0 else False
    middle_met=(not settings.focus_v2_require_bollinger_middle) or (mid>0 and mark>=mid)
    configured_portfolio_met=state.cycle_start_equity>0 and equity>=state.cycle_start_equity*settings.focus_v2_portfolio_recovery_ratio
    portfolio_gate_met=configured_portfolio_met or (state.cycle_start_equity>0 and equity>=state.cycle_start_equity*.95)
    hold_history={"cycleId":state.cycle_id,"cycleStartEquity":state.cycle_start_equity,"equity":equity,"longNotional":long_notional,"shortNotional":short_notional,"netExposure":long_notional-short_notional,"grossExposure":long_notional+short_notional,"dcaCount":state.dca_count,"rehedgeTrigger":state.rehedge_stop_price,"rehedgeArmed":bool(state.rehedge_client_id and state.rehedge_stop_price>0),"cyclePnl":equity-state.cycle_start_equity,"currentPrice":mark,"longEntry":entry,"shortEntry":f((short_row or {}).get("entryPrice")),"bollinger5mMiddle":mid,"recoveryReboundPrice":rebound_price,"recoveryPriceMet":price_met,"bollinger5mConfirmed":middle_met,"portfolioRecoveryTarget":state.cycle_start_equity*settings.focus_v2_portfolio_recovery_ratio if state.cycle_start_equity>0 else 0.0,"portfolioRecoveryMet":portfolio_gate_met,"configuredPortfolioRecoveryMet":configured_portfolio_met,"shortReleaseRatio":settings.focus_v2_release_ratio,"shortReleaseReady":bool(price_met and middle_met and portfolio_gate_met),"dcaAnchorPrice":state.dca_anchor_price,"nextDcaTrigger":continuous_dca_trigger(state.dca_anchor_price,settings.focus_dca_distance),"harvestBaselineEquity":state.harvest_baseline_equity,"profitSinceHarvest":equity-state.harvest_baseline_equity,"profitTriggerUsdt":settings.focus_v2_profit_trigger_usdt,"profitHarvestUsdt":settings.focus_v2_profit_harvest_usdt,"profitRemainingUsdt":(max(0.0,settings.focus_v2_profit_trigger_usdt-(equity-state.harvest_baseline_equity)) if settings.focus_v2_profit_trigger_usdt>0 else 0.0),"totalHarvestedProfit":state.total_harvested_profit,"lastHarvestProfit":state.last_harvest_profit}
    if state.recovery_model_version>=RECOVERY_MODEL_FAST:
        hold_history.update({"rehedgeArmed":_open_rehedge_qty(open_orders,symbol)>0,"recoveryModelVersion":state.recovery_model_version,"recoveryStage":state.release_stage,"recoveryProgressRatio":state.recovery_progress_ratio,"recoveryLow":state.recent_low,"recoveryHigh":state.recovery_high,"longBreakEven":entry,"nextReleasePrice":state.next_release_price,"nextReleaseQty":max(0.0,short_qty-(hedge_target/max(mark,1e-12))*recovery_remaining_ratio(min(len(RECOVERY_STAGE_PROGRESS),state.release_stage+1),settings.focus_v2_release_ratio)) if state.release_stage<len(RECOVERY_STAGE_PROGRESS) else 0.0,"releasedShortQty":state.released_short_qty,"armedRehedgeQty":_open_rehedge_qty(open_orders,symbol),"targetShortNotional":hedge_target,"hedgeRatio":short_notional/long_notional if long_notional>0 else 0.0,"recoveryStatus":recovery_status(state.release_stage,state.recovery_progress_ratio)})
    ref.set({"focusV2State":state_map(replace(state,last_action="HOLD",last_reason="bescherming in balans")),"phase":"FOCUS_V2_LIVE","lastReason":"FOCUS_V2_HOLD","focusV2History":hold_history},merge=True)
    return {"status":"waiting","action":"FOCUS_V2_HOLD","symbol":symbol,"ordersSent":0,"cyclePnl":equity-state.cycle_start_equity}
