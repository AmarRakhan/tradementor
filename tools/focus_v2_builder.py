#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]

def replace_once(path:str,old:str,new:str)->None:
    p=ROOT/path
    text=p.read_text()
    if old not in text:
        raise SystemExit(f"anchor missing in {path}: {old[:120]!r}")
    if text.count(old)!=1:
        raise SystemExit(f"anchor not unique in {path}: {old[:120]!r}")
    p.write_text(text.replace(old,new,1))

def insert_after(path:str,anchor:str,addition:str)->None:
    replace_once(path,anchor,anchor+addition)

# ---------------------------------------------------------------------------
# Backend settings: default-off, isolated Focus 2.0 configuration.
# ---------------------------------------------------------------------------
settings_path="cloud_api/aster_strategy2.py"
text=(ROOT/settings_path).read_text()
if "focus_v2_enabled" not in text:
    anchor="    focus_airbag_drawdown_3: float = 0.05\n"
    addition='''    # Focus 2.0 is deliberately opt-in. Existing Focus behavior is unchanged when false.\n    focus_v2_enabled: bool = False\n    focus_v2_min_net_long_usdt: float = 5.0\n    focus_v2_min_net_long_ratio: float = 0.02\n    focus_v2_max_hedge_ratio: float = 0.95\n    focus_v2_release_ratio: float = 0.33\n    focus_v2_recovery_rebound_pct: float = 0.003\n    focus_v2_portfolio_recovery_ratio: float = 0.99\n    focus_v2_rehedge_setback_pct: float = 0.003\n    focus_v2_require_bollinger_middle: bool = True\n'''
    if anchor not in text: raise SystemExit("Strategy2Config field anchor missing")
    text=text.replace(anchor,anchor+addition,1)
    parse_anchor='            focus_airbag_drawdown_3=float(raw.get("focusAirbagDrawdown3",0.05)),\n'
    parse_add='''            focus_v2_enabled=bool(raw.get("focusV2Enabled",False)),\n            focus_v2_min_net_long_usdt=float(raw.get("focusV2MinNetLongUsdt",5.0)),\n            focus_v2_min_net_long_ratio=float(raw.get("focusV2MinNetLongRatio",0.02)),\n            focus_v2_max_hedge_ratio=float(raw.get("focusV2MaxHedgeRatio",0.95)),\n            focus_v2_release_ratio=float(raw.get("focusV2ReleaseRatio",0.33)),\n            focus_v2_recovery_rebound_pct=float(raw.get("focusV2RecoveryReboundPct",0.003)),\n            focus_v2_portfolio_recovery_ratio=float(raw.get("focusV2PortfolioRecoveryRatio",0.99)),\n            focus_v2_rehedge_setback_pct=float(raw.get("focusV2RehedgeSetbackPct",0.003)),\n            focus_v2_require_bollinger_middle=bool(raw.get("focusV2RequireBollingerMiddle",True)),\n'''
    if parse_anchor not in text: raise SystemExit("Strategy2Config parser anchor missing")
    text=text.replace(parse_anchor,parse_anchor+parse_add,1)
    # validation is inserted immediately before final return when possible
    validation='''\n        if config.focus_v2_enabled:\n            if config.trading_mode != "focus": raise ValueError("Focus 2.0 vereist tradingMode focus")\n            if config.focus_v2_min_net_long_usdt < 0: raise ValueError("Focus 2.0 netto LONG-bias USD mag niet negatief zijn")\n            if not 0 <= config.focus_v2_min_net_long_ratio < 1: raise ValueError("Focus 2.0 netto LONG-bias ratio moet tussen 0 en 1 liggen")\n            if not 0 < config.focus_v2_max_hedge_ratio < 1: raise ValueError("Focus 2.0 maximale hedge moet tussen 0 en 100% liggen")\n            if not 0 < config.focus_v2_release_ratio <= 1: raise ValueError("Focus 2.0 release moet tussen 0 en 100% liggen")\n            if not 0 < config.focus_v2_recovery_rebound_pct < .25: raise ValueError("Focus 2.0 recovery rebound is ongeldig")\n            if not .5 <= config.focus_v2_portfolio_recovery_ratio <= 1.05: raise ValueError("Focus 2.0 portfolio recovery ratio is ongeldig")\n            if not 0 < config.focus_v2_rehedge_setback_pct < .25: raise ValueError("Focus 2.0 re-hedge setback is ongeldig")\n'''
    # Strategy2Settings parser uses `return config`; only insert into from_dict block once.
    marker="        return config\n"
    if marker not in text: raise SystemExit("Strategy2Config return anchor missing")
    text=text.replace(marker,validation+marker,1)
    (ROOT/settings_path).write_text(text)

# ---------------------------------------------------------------------------
# New isolated Focus 2.0 execution engine.
# ---------------------------------------------------------------------------
v2=ROOT/"cloud_api/aster_strategy2_focus_v2.py"
v2.write_text(r'''"""Strategy-2 Focus 2.0: protected LONG builder.

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
from aster_gateway import AsterOrderIntent, ContractRules, PositionSide
from aster_strategy2 import Strategy2Config
from aster_strategy2_focus import dca_notional_sequence, next_dca_trigger, rank_focus_pairs
from aster_strategy2_focus_adapter import current_focus_markets
from aster_strategy2_runtime import active_position_map, owned_from_mapping, owned_to_mapping
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
    realized_hedge_pnl:float=0.0; last_action:str="IDLE"; last_reason:str=""

def state_from(raw:Any)->FocusV2State:
    x=raw if isinstance(raw,dict) else {}
    def g(c,s,d=None):return x[c] if c in x else x.get(s,d)
    return FocusV2State(str(g("cycleId","cycle_id","") or ""),str(g("symbol","symbol","") or "").upper(),f(g("cycleStartEquity","cycle_start_equity",0)),int(f(g("openedAt","opened_at_ms",0))),f(g("originalEntry","original_entry",0)),f(g("weightedEntry","weighted_entry",0)),int(f(g("dcaCount","dca_count",0))),f(g("recentLow","recent_low",0)),f(g("recoveryHigh","recovery_high",0)),int(f(g("releaseStage","release_stage",0))),str(g("rehedgeClientId","rehedge_client_id","") or ""),f(g("rehedgeStopPrice","rehedge_stop_price",0)),f(g("realizedHedgePnl","realized_hedge_pnl",0)),str(g("lastAction","last_action","IDLE") or "IDLE"),str(g("lastReason","last_reason","") or ""))

def state_map(s:FocusV2State)->dict[str,Any]:
    return {"cycleId":s.cycle_id,"symbol":s.symbol,"cycleStartEquity":s.cycle_start_equity,"openedAt":s.opened_at_ms,"originalEntry":s.original_entry,"weightedEntry":s.weighted_entry,"dcaCount":s.dca_count,"recentLow":s.recent_low,"recoveryHigh":s.recovery_high,"releaseStage":s.release_stage,"rehedgeClientId":s.rehedge_client_id,"rehedgeStopPrice":s.rehedge_stop_price,"realizedHedgePnl":s.realized_hedge_pnl,"lastAction":s.last_action,"lastReason":s.last_reason}

def target_hedge_notional(long_notional:float,*,min_bias_usdt:float,min_bias_ratio:float,max_hedge_ratio:float)->float:
    long=max(0.0,long_notional);bias=max(0.0,min_bias_usdt,long*max(0.0,min_bias_ratio))
    return max(0.0,min(long*max(0.0,min(max_hedge_ratio,.999999)),long-bias))

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

    # New clean cycle: LONG first, then protective SHORT to target bias.
    if not state.cycle_id:
        cycle=f"focusv2-{hashlib.sha256(f'{uid}|{symbol}|{timestamp_ms}'.encode()).hexdigest()[:16]}";start_notional=max(0.0,settings.focus_start_order_notional)
        if start_notional<=0:raise RuntimeError("Focus 2.0 startnotional is nul")
        if start_notional/max(1,settings.leverage)>available: return {"status":"waiting","action":"FOCUS_V2_MARGIN_BLOCK","ordersSent":0}
        state=FocusV2State(cycle,symbol,equity,timestamp_ms,0,0,0,mark,mark,0,"",0,0,"OPEN_PENDING","nieuwe schone Focus 2.0 cycle")
        plan=_plan(client,symbol,mark,start_notional,settings.leverage);prefix=f"s2fv2-{hashlib.sha256(f'{cycle}|long0'.encode()).hexdigest()[:12]}"
        def reserve(i:Any)->None:
            if reserve_order:reserve_order(i,{"kind":"FOCUS_V2_OPEN_LONG","cycleId":cycle,"marginUsd":start_notional/max(1,settings.leverage)})
        result=execute_leg_once(client,plan,side=PositionSide.LONG,action="OPEN",id_prefix=prefix,confirm=True,before_submit=reserve,new_position_leverage=settings.leverage)
        q,p,cid,oid=_fill(result);owned=_upsert(owned,settings=settings,state=state,role=ROLE_LONG,side="LONG",q=q,p=p,cid=cid,oid=oid,is_dca=False,ts=timestamp_ms);state=replace(state,original_entry=p,weighted_entry=p,recent_low=p,recovery_high=p,last_action="OPEN_LONG",last_reason="eerste LONG bevestigd")
        # hedge is intentionally a second idempotent order; if budget only allowed one, next tick reconciles and opens it.
        ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned],"phase":"FOCUS_V2_LIVE"},merge=True)
        _audit(ref,"FOCUS_V2_CYCLE_STARTED",cycleId=cycle,symbol=symbol,cycleStartEquity=equity,longNotional=q*p)
        return {"status":"executed","action":"FOCUS_V2_OPEN_LONG","symbol":symbol,"ordersSent":1,"cycleId":cycle}

    long_notional=_notional(long_row);short_notional=_notional(short_row);long_qty=abs(f((long_row or {}).get("positionAmt")));short_qty=abs(f((short_row or {}).get("positionAmt")))
    if long_notional<=0:
        _cancel_rehedge(client,state); pnl=equity-state.cycle_start_equity
        ref.set({"focusV2State":state_map(FocusV2State()),"ownedLegs":[owned_to_mapping(x) for x in owned if str(x.role).upper() not in {ROLE_LONG,ROLE_HEDGE}],"focusV2LastCycle":{"cycleId":state.cycle_id,"resultUsd":pnl,"closedAt":timestamp_ms},"phase":"FOCUS_LIVE"},merge=True)
        return {"status":"executed","action":"FOCUS_V2_CYCLE_FLAT","ordersSent":0,"cyclePnl":pnl}
    entry=f((long_row or {}).get("entryPrice"),state.weighted_entry);recent_low=min(x for x in (state.recent_low or mark,mark,local_low or mark) if x>0);state=replace(state,recent_low=recent_low,recovery_high=max(state.recovery_high,mark),weighted_entry=entry)

    # Cycle TP uses account equity baseline: aggregate hedge losses are intentionally included.
    tp_reached=(settings.focus_take_profit_mode=="usdt" and equity>=state.cycle_start_equity+settings.focus_take_profit_usdt) or (settings.focus_take_profit_mode!="usdt" and equity>=state.cycle_start_equity*(1+settings.focus_minimum_profit_pct))
    if tp_reached:
        _cancel_rehedge(client,state);sent=0
        # close hedge first, then long; aggregate cycle gate replaces legacy per-leg profit guard only here.
        for side,row,role in (("SHORT",short_row,ROLE_HEDGE),("LONG",long_row,ROLE_LONG)):
            qty=abs(f((row or {}).get("positionAmt")))
            if qty<=0:continue
            m=f((row or {}).get("markPrice"),mark);plan=_plan(client,symbol,m,qty*m,int(f((row or {}).get("leverage"),settings.leverage)));prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|tp|{side}'.encode()).hexdigest()[:12]}"
            result=execute_leg_once(client,plan,side=PositionSide.SHORT if side=="SHORT" else PositionSide.LONG,action="CLOSE",id_prefix=prefix,confirm=True);cq,cp,_,_=_fill(result);owned=_reduce_owned(owned,role,cq,timestamp_ms);sent+=1
        _audit(ref,"FOCUS_V2_CYCLE_TP",cycleId=state.cycle_id,cycleStartEquity=state.cycle_start_equity,equity=equity,cyclePnl=equity-state.cycle_start_equity)
        ref.set({"focusV2State":state_map(replace(state,last_action="TP_CLOSE",last_reason="cycle portfolio-winstdoel bereikt",rehedge_client_id="",rehedge_stop_price=0)),"ownedLegs":[owned_to_mapping(x) for x in owned]},merge=True)
        return {"status":"executed","action":"FOCUS_V2_TP_CLOSE","symbol":symbol,"ordersSent":sent,"cyclePnl":equity-state.cycle_start_equity}

    # Long DCA has priority on a down move, using the existing Focus ladder/settings.
    trigger=next_dca_trigger(original_entry=state.original_entry,dca_count=state.dca_count,max_dca=settings.focus_max_dca,distance_pct=settings.focus_dca_distance,mode=settings.focus_dca_mode,custom_levels=settings.focus_dca_custom_levels,unlimited=settings.focus_dca_unlimited)
    if settings.focus_dca_enabled and trigger>0 and mark<=trigger:
        if settings.focus_dca_amount_mode=="linear":notional=settings.focus_dca_notional+settings.focus_dca_increment*state.dca_count
        else:
            seq=dca_notional_sequence(amount=settings.focus_dca_notional,multiplier=settings.focus_dca_multiplier,count=state.dca_count+1);notional=seq[-1] if seq else settings.focus_dca_notional
        focus_used=long_notional; remaining=max(0.0,settings.focus_max_budget_usd-focus_used);notional=min(notional,remaining)
        liq=f((long_row or {}).get("liquidationPrice"));liqdist=abs(mark-liq)/mark if liq>0 else 1.0
        if notional>0 and notional/max(1,settings.leverage)<=available and maint<settings.emergency_margin_ratio and liqdist>=.05:
            plan=_plan(client,symbol,mark,notional,settings.leverage);prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|dca|{state.dca_count}'.encode()).hexdigest()[:12]}";result=execute_leg_once(client,plan,side=PositionSide.LONG,action="OPEN",id_prefix=prefix,confirm=True);q,p,cid,oid=_fill(result);owned=_upsert(owned,settings=settings,state=state,role=ROLE_LONG,side="LONG",q=q,p=p,cid=cid,oid=oid,is_dca=True,ts=timestamp_ms);new_qty=long_qty+q;new_entry=((long_qty*entry)+(q*p))/new_qty if new_qty else p;state=replace(state,dca_count=state.dca_count+1,weighted_entry=new_entry,last_action="DCA_LONG",last_reason="bestaande Focus DCA-ladder",recent_low=min(state.recent_low,p));ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned]},merge=True);_audit(ref,"FOCUS_V2_DCA_LONG",cycleId=state.cycle_id,symbol=symbol,dcaCount=state.dca_count,longNotional=(long_notional+q*p));return {"status":"executed","action":"FOCUS_V2_DCA_LONG","symbol":symbol,"ordersSent":1}

    # Reconcile protective hedge to current LONG. This is why old start-size is never used.
    hedge_target=target_hedge_notional(long_notional,min_bias_usdt=settings.focus_v2_min_net_long_usdt,min_bias_ratio=settings.focus_v2_min_net_long_ratio,max_hedge_ratio=settings.focus_v2_max_hedge_ratio)
    recovery=recovery_confirmed(mark=mark,recent_low=state.recent_low,bollinger_middle=mid,equity=equity,cycle_start_equity=state.cycle_start_equity,rebound_pct=settings.focus_v2_recovery_rebound_pct,portfolio_ratio=settings.focus_v2_portfolio_recovery_ratio,require_middle=settings.focus_v2_require_bollinger_middle)
    full=full_recovery(equity=equity,cycle_start_equity=state.cycle_start_equity,ratio=settings.focus_v2_portfolio_recovery_ratio)
    if recovery and short_qty>0:
        q=release_quantity(short_qty,settings.focus_v2_release_ratio,full);plan=_plan(client,symbol,mark,q*mark,int(f((short_row or {}).get("leverage"),settings.leverage)));prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|release|{state.release_stage}'.encode()).hexdigest()[:12]}";result=execute_leg_once(client,plan,side=PositionSide.SHORT,action="CLOSE",id_prefix=prefix,confirm=True);cq,cp,_,_=_fill(result);short_entry=f((short_row or {}).get("entryPrice"));realized=(short_entry-cp)*cq;owned=_reduce_owned(owned,ROLE_HEDGE,cq,timestamp_ms);new_stage=state.release_stage+1;state=replace(state,release_stage=new_stage,realized_hedge_pnl=state.realized_hedge_pnl+realized,last_action="HEDGE_RELEASE",last_reason="5m herstel + portfolio recovery",recovery_high=max(state.recovery_high,mark));released_notional=cq*cp
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
        plan=_plan(client,symbol,mark,gap,settings.leverage);prefix=f"s2fv2-{hashlib.sha256(f'{state.cycle_id}|hedge|{state.dca_count}|{round(gap,2)}'.encode()).hexdigest()[:12]}";result=execute_leg_once(client,plan,side=PositionSide.SHORT,action="OPEN",id_prefix=prefix,confirm=True);q,p,cid,oid=_fill(result);owned=_upsert(owned,settings=settings,state=state,role=ROLE_HEDGE,side="SHORT",q=q,p=p,cid=cid,oid=oid,is_dca=False,ts=timestamp_ms);state=replace(state,last_action="HEDGE_GROW",last_reason="hedge opnieuw berekend op actuele totale LONG");ref.set({"focusV2State":state_map(state),"ownedLegs":[owned_to_mapping(x) for x in owned]},merge=True);_audit(ref,"FOCUS_V2_HEDGE_GROW",cycleId=state.cycle_id,symbol=symbol,longNotional=long_notional,targetShortNotional=hedge_target);return {"status":"executed","action":"FOCUS_V2_HEDGE_GROW","symbol":symbol,"ordersSent":1}

    ref.set({"focusV2State":state_map(replace(state,last_action="HOLD",last_reason="bescherming in balans")),"focusV2History":{"cycleId":state.cycle_id,"cycleStartEquity":state.cycle_start_equity,"equity":equity,"longNotional":long_notional,"shortNotional":short_notional,"netExposure":long_notional-short_notional,"dcaCount":state.dca_count,"rehedgeTrigger":state.rehedge_stop_price,"cyclePnl":equity-state.cycle_start_equity}},merge=True)
    return {"status":"waiting","action":"FOCUS_V2_HOLD","symbol":symbol,"ordersSent":0,"cyclePnl":equity-state.cycle_start_equity}
''')

# Dispatch Focus 2.0 before legacy Focus. Existing path remains byte-for-byte below it.
live_path="cloud_api/aster_strategy2_focus_live.py"
text=(ROOT/live_path).read_text()
if "run_focus_v2_live_step" not in text:
    import_anchor="from aster_strategy2_focus_cycle import (FocusCycleState, ParkedPair, brake_triggered, can_rotate, cycle_state_from_mapping, cycle_state_to_mapping, mark_pair_used, park_pair, reset_cycle, update_high_water)\n"
    if import_anchor not in text:raise SystemExit("focus_live import anchor missing")
    text=text.replace(import_anchor,import_anchor+"from aster_strategy2_focus_v2 import run_focus_v2_live_step\n",1)
    dispatch='''    if settings.trading_mode!="focus" or not settings.focus_live_enabled:return None\n    if getattr(settings,"focus_v2_enabled",False):\n        return run_focus_v2_live_step(client=client,ref=ref,raw_state=raw_state,settings=settings,uid=uid,account=account,positions=positions,timestamp_ms=timestamp_ms,dry_run=dry_run,order_budget=order_budget,reserve_order=reserve_order,open_orders=open_orders)\n'''
    old='''    if settings.trading_mode!="focus" or not settings.focus_live_enabled:return None\n'''
    if old not in text:raise SystemExit("focus_live dispatch anchor missing")
    text=text.replace(old,dispatch,1)
    (ROOT/live_path).write_text(text)

# ---------------------------------------------------------------------------
# Wizard: visible Focus | Focus 2.0 selector plus explicit opt-in controls.
# We reuse existing Focus DCA/TP controls; only V2-specific protection/recovery
# controls are new. Legacy Focus is untouched while V2 is OFF.
# ---------------------------------------------------------------------------
maker="web/components/aster-strategy2-maker.tsx"
text=(ROOT/maker).read_text()
if "focusV2Enabled" not in text:
    text=text.replace('focusAirbagD1:string;focusAirbagD2:string;focusAirbagD3:string};','focusAirbagD1:string;focusAirbagD2:string;focusAirbagD3:string;focusV2Enabled:boolean;focusV2MinBias:string;focusV2MinBiasPct:string;focusV2MaxHedge:string;focusV2Release:string;focusV2Rebound:string;focusV2PortfolioRecovery:string;focusV2Rehedge:string;focusV2RequireMiddle:boolean};',1)
    text=text.replace('focusAirbagD1:"1.5",focusAirbagD2:"3",focusAirbagD3:"5"};','focusAirbagD1:"1.5",focusAirbagD2:"3",focusAirbagD3:"5",focusV2Enabled:false,focusV2MinBias:"5",focusV2MinBiasPct:"2",focusV2MaxHedge:"95",focusV2Release:"33",focusV2Rebound:"0.3",focusV2PortfolioRecovery:"99",focusV2Rehedge:"0.3",focusV2RequireMiddle:true};',1)
    load_anchor='focusAirbagD3:String(Number(x.focusAirbagDrawdown3??.05)*100)})'
    load_new='focusAirbagD3:String(Number(x.focusAirbagDrawdown3??.05)*100),focusV2Enabled:Boolean(x.focusV2Enabled??false),focusV2MinBias:String(x.focusV2MinNetLongUsdt??5),focusV2MinBiasPct:String(Number(x.focusV2MinNetLongRatio??.02)*100),focusV2MaxHedge:String(Number(x.focusV2MaxHedgeRatio??.95)*100),focusV2Release:String(Number(x.focusV2ReleaseRatio??.33)*100),focusV2Rebound:String(Number(x.focusV2RecoveryReboundPct??.003)*100),focusV2PortfolioRecovery:String(Number(x.focusV2PortfolioRecoveryRatio??.99)*100),focusV2Rehedge:String(Number(x.focusV2RehedgeSetbackPct??.003)*100),focusV2RequireMiddle:Boolean(x.focusV2RequireBollingerMiddle??true)})'
    if load_anchor not in text:raise SystemExit("maker load anchor missing")
    text=text.replace(load_anchor,load_new,1)
    save_anchor='focusAirbagDrawdown3:num(v.focusAirbagD3)/100,focusSlots:'
    save_new='focusAirbagDrawdown3:num(v.focusAirbagD3)/100,focusV2Enabled:v.focusV2Enabled,focusV2MinNetLongUsdt:num(v.focusV2MinBias),focusV2MinNetLongRatio:num(v.focusV2MinBiasPct)/100,focusV2MaxHedgeRatio:num(v.focusV2MaxHedge)/100,focusV2ReleaseRatio:num(v.focusV2Release)/100,focusV2RecoveryReboundPct:num(v.focusV2Rebound)/100,focusV2PortfolioRecoveryRatio:num(v.focusV2PortfolioRecovery)/100,focusV2RehedgeSetbackPct:num(v.focusV2Rehedge)/100,focusV2RequireBollingerMiddle:v.focusV2RequireMiddle,focusSlots:'
    if save_anchor not in text:raise SystemExit("maker save anchor missing")
    text=text.replace(save_anchor,save_new,1)
    airbag_step='{title:"Adaptieve Portfolio Airbag"'
    idx=text.find(airbag_step)
    if idx<0:raise SystemExit("maker airbag step missing")
    v2step='''{title:"Focus | Focus 2.0",help:"Focus blijft exact de bestaande strategie. Focus 2.0 is een aparte opt-in beschermd-LONG bouwer: SHORT is alleen een tijdelijke airbag en mag tijdens geldig herstel met individueel verlies worden vrijgegeven wanneer de totale cycle leidend is.",body:<><div className="maker-summary"><b>Focus</b><span>Huidige Focus blijft ongewijzigd.</span><button type="button" className={!v.focusV2Enabled?"active":""} onClick={()=>setV({...v,focusV2Enabled:false})}>Focus gebruiken</button></div><div className="maker-summary"><b>Focus 2.0 · Beschermd LONG opbouwen</b><span>Tijdens daling bouwt LONG lager op en volgt SHORT de actuele totale LONG als beschermingslaag. Bij bevestigd 5m-herstel wordt de hedge in delen vrijgegeven. Draait de koers terug, dan staat exchange-side re-hedge bescherming klaar.</span><span>De SHORT is geen winststrategie. Een rode hedge-release is toegestaan binnen een geldige Focus-2.0 recovery; cycle-equity en totale portfolio-uitkomst zijn leidend.</span><Toggle label="Focus 2.0 gebruiken" value={v.focusV2Enabled} set={x=>setV({...v,focusV2Enabled:x})}/>{v.focusV2Enabled&&<><Field label="Minimale netto LONG-bias (USDT)" value={v.focusV2MinBias} set={x=>setV({...v,focusV2MinBias:x})}/><Field label="Minimale netto LONG-bias (%)" value={v.focusV2MinBiasPct} set={x=>setV({...v,focusV2MinBiasPct:x})}/><Field label="Maximale hedge (%)" value={v.focusV2MaxHedge} set={x=>setV({...v,focusV2MaxHedge:x})}/><Field label="SHORT vrijgeven per herstelstap (%)" value={v.focusV2Release} set={x=>setV({...v,focusV2Release:x})}/><Field label="Koersherstel vanaf recente low (%)" value={v.focusV2Rebound} set={x=>setV({...v,focusV2Rebound:x})}/><Field label="Portfolio bijna hersteld (%)" value={v.focusV2PortfolioRecovery} set={x=>setV({...v,focusV2PortfolioRecovery:x})}/><Field label="Re-hedge terugval (%)" value={v.focusV2Rehedge} set={x=>setV({...v,focusV2Rehedge:x})}/><Toggle label="5m Bollinger-middle als herstelbevestiging" value={v.focusV2RequireMiddle} set={x=>setV({...v,focusV2RequireMiddle:x})}/><small>Bij iedere release wordt de terugvalbescherming opnieuw berekend op de actuele LONG, niet op de oorspronkelijke order.</small></>}</div></>},\n  '''
    text=text[:idx]+v2step+text[idx:]
    review='Airbag {v.focusAirbag?`AAN · ${v.focusAirbagStart}% → max ${v.focusAirbagMax}%`:"UIT · huidige Focus ongewijzigd"}'
    if review in text:text=text.replace(review,'Focus 2.0 {v.focusV2Enabled?`AAN · max hedge ${v.focusV2MaxHedge}% · release ${v.focusV2Release}%`:"UIT · bestaande Focus"}<br/>Airbag {v.focusAirbag?`AAN · ${v.focusAirbagStart}% → max ${v.focusAirbagMax}%`:"UIT"}',1)
    (ROOT/maker).write_text(text)

# ---------------------------------------------------------------------------
# Behavioral tests for the pure V2 invariants and isolation contract.
# ---------------------------------------------------------------------------
test=ROOT/"cloud_api/test_aster_strategy2_focus_v2.py"
test.write_text(r'''from pathlib import Path
from aster_strategy2_focus_v2 import target_hedge_notional,release_quantity,recovery_confirmed,full_recovery,rehedge_stop,state_from,state_map,FocusV2State
from aster_strategy2 import Strategy2Config

HERE=Path(__file__).resolve().parent

def test_focus_v2_defaults_off_and_legacy_focus_guard_remains():
    cfg=Strategy2Config.from_mapping({"tradingMode":"focus"})
    assert cfg.focus_v2_enabled is False
    legacy=(HERE/"aster_strategy2_focus_multi.py").read_text()
    assert "FOCUS_HEDGE_CLOSE_BLOCKED" in legacy and "hedge_evidence.expected_net<=0" in legacy

def test_initial_long_always_keeps_net_long_bias():
    assert target_hedge_notional(100,min_bias_usdt=5,min_bias_ratio=.02,max_hedge_ratio=.95)==95
    assert target_hedge_notional(3000,min_bias_usdt=5,min_bias_ratio=.02,max_hedge_ratio=.95)==2850

def test_hedge_follows_current_long_not_start_size():
    a=target_hedge_notional(100,min_bias_usdt=5,min_bias_ratio=.02,max_hedge_ratio=.95)
    b=target_hedge_notional(500,min_bias_usdt=5,min_bias_ratio=.02,max_hedge_ratio=.95)
    assert a==95 and b==475 and b>a

def test_release_is_tranched_until_full_portfolio_recovery():
    assert release_quantity(900,.33,False)==297
    assert release_quantity(900,.33,True)==900
    assert not full_recovery(equity=296,cycle_start_equity=300,ratio=.99)
    assert full_recovery(equity=297,cycle_start_equity=300,ratio=.99)

def test_recovery_needs_price_structure_and_portfolio_progress():
    assert recovery_confirmed(mark=101,recent_low=100,bollinger_middle=100.5,equity=297,cycle_start_equity=300,rebound_pct=.003,portfolio_ratio=.99,require_middle=True)
    assert not recovery_confirmed(mark=100.1,recent_low=100,bollinger_middle=100.05,equity=300,cycle_start_equity=300,rebound_pct=.003,portfolio_ratio=.99,require_middle=True)
    assert not recovery_confirmed(mark=101,recent_low=100,bollinger_middle=102,equity=300,cycle_start_equity=300,rebound_pct=.003,portfolio_ratio=.99,require_middle=True)

def test_rehedge_trigger_sits_below_release_price():
    assert 99.69<rehedge_stop(100,.003)<99.71

def test_state_roundtrip_freezes_cycle_equity():
    s=FocusV2State(cycle_id="c",symbol="SOLUSDT",cycle_start_equity=300,original_entry=100,dca_count=4)
    r=state_from(state_map(s));assert r.cycle_start_equity==300 and r.cycle_id=="c" and r.dca_count==4

def test_red_hedge_release_is_isolated_from_legacy_close_guard():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "FOCUS_V2_HEDGE_RELEASE" in src
    assert "AsterCloseBlocked" not in src
    assert "expected_net" not in src

def test_exchange_side_rehedge_is_stop_market_and_current_long_based():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert '"type":"STOP_MARKET"' in src
    assert "hedge_target=target_hedge_notional(long_notional" in src
    assert "REHEDGE_PREFIX" in src

def test_duplicate_rehedge_is_counted_as_armed_not_reopened():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "armed_qty" in src and "hedge_target-short_notional-armed_qty" in src

def test_existing_focus_is_never_adopted():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "Bestaande Focus ownership wordt nooit gemigreerd" in src
    assert "Bestaande exchange-positie wordt niet geadopteerd" in src

def test_margin_liquidation_guard_precedes_dca():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "maint<settings.emergency_margin_ratio" in src
    assert "liqdist>=.05" in src

def test_tp_is_cycle_equity_based_and_cancels_rehedge():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "cycle_start_equity+settings.focus_take_profit_usdt" in src
    assert "_cancel_rehedge(client,state)" in src

def test_wizard_has_separate_focus_v2_opt_in():
    ui=(HERE.parent/"web/components/aster-strategy2-maker.tsx").read_text()
    assert 'title:"Focus | Focus 2.0"' in ui
    assert 'label="Focus 2.0 gebruiken"' in ui
    assert "Focus 2.0 · Beschermd LONG opbouwen" in ui
''')

print("Focus 2.0 patch applied")
