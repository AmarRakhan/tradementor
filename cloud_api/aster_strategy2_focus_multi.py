"""Manual Multi-Focus live runtime.

This module is activated only when Strategy2Config.focus_slots is non-empty.
Legacy single-Focus remains in aster_strategy2_focus_live.py.  Every configured
slot owns one unique Aster symbol, one explicit Hedge-Mode side and one leverage
policy.  All exchange mutations still flow through execute_leg_once and the
Strategy-2 transactional reserve callback.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, Callable
import hashlib
import math
import time

from aster_close_guard import CloseEvidence
from aster_execution import NewPositionLeverageBlocked, PairExecutionPlan, execute_leg_once, plan_pair, contract_brackets
from aster_gateway import AsterAutomationConfig, AsterOrderIntent, ContractRules, LeverageBracket, PositionSide, maximum_allowed_leverage
from aster_strategy2 import Strategy2Config
from aster_strategy2_focus import dca_drop_sequence, dca_notional_sequence
from aster_strategy2_runtime import active_position_map, owned_from_mapping, owned_to_mapping
from aster_strategy2_state import OwnedLeg


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result=float(value)
    except (TypeError,ValueError):
        return default
    return result if math.isfinite(result) else default


def _audit(ref: Any, event: str, *, slot_id: str, symbol: str, side: str, reason: str = "", **details: Any) -> None:
    try:
        ref.collection("audit").add({"event":event,"strategyId":"aster-strategy-2","slotId":slot_id,
            "symbol":symbol,"side":side,"reason":reason,"details":details,"timestampMs":int(time.time()*1000)})
    except Exception:
        pass


def _owned(raw: dict[str, Any]) -> list[OwnedLeg]:
    result=[]
    for row in raw.get("ownedLegs",()) if isinstance(raw.get("ownedLegs"),list) else ():
        try: result.append(owned_from_mapping(row))
        except (TypeError,ValueError): pass
    return result


def _slot_role(slot_id: str) -> str:
    return f"FOCUS_SLOT:{slot_id}"


def _slot_owned(owned: list[OwnedLeg], slot_id: str) -> OwnedLeg | None:
    role=_slot_role(slot_id)
    matches=[x for x in owned if str(x.role).upper()==role.upper()]
    if len(matches)>1:
        raise RuntimeError(f"{slot_id}: dubbele Multi-Focus ownership")
    return matches[0] if matches else None


def _migrate_legacy_focus_leg(owned:list[OwnedLeg],raw_state:dict[str,Any],*,slot_id:str,symbol:str,side:str,row:dict[str,Any],timestamp_ms:int)->tuple[list[OwnedLeg],OwnedLeg|None,dict[str,Any]]:
    legacy_state=raw_state.get("focusLiveState") if isinstance(raw_state.get("focusLiveState"),dict) else {}
    legacy_cycle=str(legacy_state.get("cycleId","")).strip()
    legacy_pair=str(legacy_state.get("activePair","")).upper().strip()
    matches=[x for x in owned if str(x.role).upper()=="FOCUS" and x.symbol==symbol and x.side==side]
    qty=abs(_f(row.get("positionAmt")));entry=_f(row.get("entryPrice"))
    if len(matches)!=1 or legacy_pair!=symbol or not legacy_cycle or matches[0].cycle_id!=legacy_cycle or qty<=0 or entry<=0:
        return owned,None,legacy_state
    legacy=matches[0]
    migrated=replace(legacy,role=_slot_role(slot_id),quantity=qty,weighted_entry=entry,last_order_at_ms=max(legacy.last_order_at_ms,timestamp_ms))
    return [migrated if x is legacy else x for x in owned],migrated,legacy_state


def _hedge_role(slot_id:str)->str:
    return f"FOCUS_SLOT_HEDGE:{slot_id}"


def _slot_hedge_owned(owned:list[OwnedLeg],slot_id:str)->OwnedLeg|None:
    role=_hedge_role(slot_id)
    matches=[x for x in owned if str(x.role).upper()==role.upper()]
    if len(matches)>1: raise RuntimeError(f"{slot_id}: dubbele Multi-Focus hedge ownership")
    return matches[0] if matches else None


def _opposite(side:str)->str:
    return "SHORT" if side=="LONG" else "LONG"


def _position(positions: list[dict[str,Any]], symbol: str, side: str) -> dict[str,Any] | None:
    return active_position_map(positions).get((symbol.upper(),side.upper()))


def _exchange_max_leverage(client: Any, symbol: str, notional: float) -> int:
    rows=contract_brackets(client,[],symbol)
    brackets=[LeverageBracket.from_mapping(x) for x in rows]
    maximum=maximum_allowed_leverage(Decimal(str(max(0.01,notional))),brackets)
    if maximum < 1:
        raise ValueError(f"{symbol}: Aster leverage-cap ontbreekt")
    return int(maximum)


def resolve_slot_leverage(client: Any, slot: dict[str,Any], settings: Strategy2Config, *, existing_leverage:int|None=None) -> tuple[int,int]:
    symbol=str(slot.get("pair",slot.get("symbol",""))).upper().strip()
    mode=str(slot.get("leverageMode","minimum")).lower()
    configured=max(1,int(_f(slot.get("leverage"),settings.leverage)))
    notional=max(0.01,_f(slot.get("startNotional"),settings.focus_start_order_notional))
    maximum=_exchange_max_leverage(client,symbol,notional)
    # Never rewrite contract leverage underneath an already-open Aster position.
    # Existing exchange truth is authoritative as long as it satisfies the slot policy.
    if existing_leverage is not None:
        current=max(1,int(existing_leverage))
        if mode=="exact":
            if current!=configured: raise ValueError(f"{symbol}: bestaande positie staat op {current}x maar Exact vereist {configured}x")
            return current,maximum
        if current<configured: raise ValueError(f"{symbol}: bestaande positie staat op {current}x, onder minimum {configured}x")
        return current,maximum
    if mode=="exact":
        if configured>maximum: raise ValueError(f"{symbol}: exact {configured}x wordt niet ondersteund; Aster max is {maximum}x")
        return configured,maximum
    if configured>maximum: raise ValueError(f"{symbol}: minimum {configured}x wordt niet ondersteund; Aster max is {maximum}x")
    return maximum,maximum


def _state_map(raw_state: dict[str,Any]) -> dict[str,dict[str,Any]]:
    rows=raw_state.get("focusLiveSlots")
    if not isinstance(rows,list): return {}
    return {str(x.get("slotId","")):dict(x) for x in rows if isinstance(x,dict) and str(x.get("slotId",""))}


def _empty_state(slot_id:str,symbol:str,side:str,mode:str,configured:int,effective:int,maximum:int)->dict[str,Any]:
    return {"slotId":slot_id,"pair":symbol,"side":side,"status":"READY","cycleId":"","originalEntry":0.0,
        "weightedEntry":0.0,"quantity":0.0,"notional":0.0,"usedMargin":0.0,"dcaCount":0,"nextDcaTrigger":0.0,
        "createdAt":0,"realizedPnl":0.0,"leverageMode":mode,"configuredLeverage":configured,"effectiveLeverage":effective,
        "exchangeMaxLeverage":maximum,"pendingAction":"","recoveryStatus":"RECONCILED","lastReconciledAt":int(time.time()*1000)}


def _next_trigger(settings:Strategy2Config, *, side:str, original:float, dca_count:int)->float:
    if original<=0:return 0.0
    if settings.focus_dca_unlimited:
        if settings.focus_dca_mode!="fixed" or not 0<settings.focus_dca_distance<1:return 0.0
        step=max(0,int(dca_count))+1
        factor=(1-settings.focus_dca_distance)**step if side=="LONG" else (1+settings.focus_dca_distance)**step
        return original*factor
    if dca_count>=settings.focus_max_dca:return 0.0
    levels=dca_drop_sequence(distance_pct=settings.focus_dca_distance,count=settings.focus_max_dca,
        mode=settings.focus_dca_mode,custom_levels=settings.focus_dca_custom_levels)
    if dca_count>=len(levels):return 0.0
    distance=levels[dca_count]
    return original*(1-distance) if side=="LONG" else original*(1+distance)


def _dca_notional(settings:Strategy2Config,dca_count:int)->float:
    if settings.focus_dca_amount_mode=="linear":
        return settings.focus_dca_notional+settings.focus_dca_increment*max(0,int(dca_count))
    try:value=settings.focus_dca_notional*(settings.focus_dca_multiplier**max(0,int(dca_count)))
    except OverflowError:return float("inf")
    return value if math.isfinite(value) else float("inf")


def _gross_pnl(side:str,entry:float,mark:float,quantity:float)->float:
    return (mark-entry)*quantity if side=="LONG" else (entry-mark)*quantity


def _close_evidence(client:Any,*,uid:str,leg:OwnedLeg,mark:float,reason:str,target_usdt:float=0.0)->CloseEvidence:
    trades=client.user_trades(leg.symbol,limit=500);income=client.income_history(limit=500)
    relevant=[x for x in trades if isinstance(x,dict) and str(x.get("symbol","")).upper()==leg.symbol
        and str(x.get("positionSide","")).upper()==leg.side and int(_f(x.get("time",x.get("timestamp",0))))>=leg.created_at_ms]
    entry_fees=sum(abs(_f(x.get("commission"))) for x in relevant)
    funding=sum(_f(x.get("income")) for x in income if isinstance(x,dict) and str(x.get("symbol","")).upper()==leg.symbol
        and str(x.get("incomeType","")).upper()=="FUNDING_FEE" and int(_f(x.get("time",0)))>=leg.created_at_ms)
    notional=leg.quantity*mark
    return CloseEvidence(uid,leg.symbol,leg.side,"strategy2:MULTI_FOCUS",reason,leg.quantity,leg.weighted_entry,mark,
        _gross_pnl(leg.side,leg.weighted_entry,mark,leg.quantity),entry_fees,notional*.0005,funding,notional*.001,
        ownership_reliable=True,fills_reliable=bool(relevant),prices_reliable=mark>0,costs_reliable=True,
        minimum_positive_buffer=target_usdt if target_usdt>0 else None)


def _confirmed_fill(result:dict[str,Any])->tuple[float,float,str,str]:
    row=result.get("result") if isinstance(result.get("result"),dict) else {}
    quantity=abs(_f(row.get("executedQty")));price=_f(row.get("avgPrice"))
    if quantity<=0 or price<=0: raise RuntimeError("Multi-Focus order mist bevestigde fill")
    intent=str(row.get("clientOrderId","")).strip();fill=str(row.get("orderId",intent)).strip()
    return quantity,price,intent,fill


def _plan(client:Any,symbol:str,mark:float,notional:float,leverage:int,positions:list[dict[str,Any]])->PairExecutionPlan:
    info=client.public_exchange_info();row=next((x for x in info.get("symbols",()) if isinstance(x,dict) and str(x.get("symbol","")).upper()==symbol),None)
    if row is None: raise ValueError(f"{symbol}: niet tradable op Aster Futures")
    brackets=contract_brackets(client,[],symbol)
    existing=sum(abs(_f(x.get("positionAmt")))*(_f(x.get("markPrice")) or _f(x.get("entryPrice"))) for x in positions if str(x.get("symbol","")).upper()==symbol)
    return plan_pair(row,brackets,mark,notional,accepted_leverage=leverage,existing_contract_notional=existing)


def run_multi_focus_live_step(*,client:Any,ref:Any,raw_state:dict[str,Any],settings:Strategy2Config,uid:str,
                              account:dict[str,Any],positions:list[dict[str,Any]],timestamp_ms:int,dry_run:bool=False,
                              order_budget:int|None=None,reserve_order:Callable[[Any,dict[str,Any]],None]|None=None,
                              open_orders:list[dict[str,Any]]|None=None)->dict[str,Any]:
    states=_state_map(raw_state);owned=_owned(raw_state);orders_sent=0;actions=[]
    remaining=max(0,int(order_budget)) if order_budget is not None else 15
    prices={str(x.get("symbol","")).upper():_f(x.get("price")) for x in client.ticker_prices() if isinstance(x,dict)}
    working_positions=list(positions)
    equity=_f(account.get("totalMarginBalance"),_f(account.get("totalWalletBalance")))
    available_remaining=max(0.0,_f(account.get("availableBalance")))
    maint_ratio=_f(account.get("totalMaintMargin"))/equity if equity>0 else 1.0
    strategy_margin_used=0.0
    for row in working_positions:
        qty=abs(_f(row.get("positionAmt"))); mark=_f(row.get("markPrice")) or _f(row.get("entryPrice")); lev=max(1.0,_f(row.get("leverage"),settings.leverage))
        if qty>0 and mark>0: strategy_margin_used+=qty*mark/lev
    strategy_margin_remaining=max(0.0,equity*settings.strategy_budget-strategy_margin_used)

    # Portfolio Handrem: one newly triggered brake parks one active slot at a time.
    # Protection has queue priority; after confirmed park the high-water baseline
    # is reset to current equity, so healthy sibling slots continue next scan.
    brake_block=False;high=equity;drop=0.0;pct=0.0
    if settings.focus_portfolio_brake_mode!="off" and settings.focus_portfolio_brake_value>0:
        prior=_f(raw_state.get("multiFocusHighWaterEquity"),equity)
        high=max(prior,equity);ref.set({"multiFocusHighWaterEquity":high},merge=True)
        drop=max(0.0,high-equity);pct=drop/high if high>0 else 0.0
        brake_block=(drop>=settings.focus_portfolio_brake_value if settings.focus_portfolio_brake_mode=="usd" else pct>=settings.focus_portfolio_brake_value)
    if brake_block:
        candidates=[]
        for index,slot_raw in enumerate(settings.focus_slots,1):
            slot=dict(slot_raw);sid=str(slot.get("slotId",f"slot-{index}"));symbol=str(slot.get("pair",slot.get("symbol",""))).upper();side=str(slot.get("side","LONG")).upper()
            leg=_slot_owned(owned,sid);hedge=_slot_hedge_owned(owned,sid);row=_position(working_positions,symbol,side)
            if leg and row and not hedge:
                mark=_f(row.get("markPrice")) or prices.get(symbol,0.0);qty=abs(_f(row.get("positionAmt")))
                pnl=_gross_pnl(side,leg.weighted_entry,mark,qty) if mark>0 else 0.0
                candidates.append((pnl,index,slot,sid,symbol,side,leg,row,mark,qty))
        if candidates:
            # Park the weakest active slot first.
            _,index,slot,sid,symbol,side,leg,row,mark,qty=min(candidates,key=lambda x:x[0])
            effective,maximum=resolve_slot_leverage(client,slot,settings);opp=_opposite(side);opp_row=_position(working_positions,symbol,opp);opp_qty=abs(_f((opp_row or {}).get("positionAmt")))
            need=max(0.0,qty-opp_qty)
            _audit(ref,"FOCUS_BRAKE_TRIGGERED",slot_id=sid,symbol=symbol,side=side,reason="portfolio high-water drawdown",drawdownUsd=drop,drawdownPct=pct)
            if need<=max(qty,1e-12)*.005:
                hedge_leg=OwnedLeg(settings.strategy_id,"strategy2",symbol,opp,leg.cycle_id,settings.version,opp_qty,_f((opp_row or {}).get("entryPrice")),0,_hedge_role(sid),(),(),(),timestamp_ms,last_order_at_ms=timestamp_ms)
                owned.append(hedge_leg);st=states.get(sid) or _empty_state(sid,symbol,side,str(slot.get("leverageMode","minimum")),int(_f(slot.get("leverage"),settings.leverage)),effective,maximum);st.update({"status":"PARKED","parkedAt":timestamp_ms,"hedgeSide":opp,"hedgeQuantity":opp_qty});states[sid]=st
                ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"focusLiveSlots":list(states.values()),"multiFocusHighWaterEquity":equity,"lastReason":"FOCUS_PARKED"},merge=True)
                _audit(ref,"FOCUS_PARKED",slot_id=sid,symbol=symbol,side=side,reason="bestaande hedge exchange-bevestigd",hedgeSide=opp,hedgeQuantity=opp_qty)
                return {"status":"executed","action":"FOCUS_PARKED","symbol":symbol,"side":side,"ordersSent":0}
            if dry_run or settings.mode!="live":
                return {"status":"simulated","action":"FOCUS_HEDGE","symbol":symbol,"side":opp,"ordersSent":0,"hedgeQuantity":need}
            if remaining<=0:return {"status":"budget-exhausted","action":"FOCUS_HEDGE","ordersSent":0}
            hedge_margin=need*mark/max(1,effective)
            if hedge_margin*1.05>available_remaining:return {"status":"waiting","action":"FOCUS_PAIR_SKIPPED_MARGIN","symbol":symbol,"ordersSent":0,"reason":"onvoldoende margin voor handremhedge"}
            plan=_plan(client,symbol,mark,need*mark,effective,working_positions);prefix=f"s2mf-h-{hashlib.sha256(f'{uid}|{sid}|{leg.cycle_id}|HEDGE'.encode()).hexdigest()[:10]}"
            def reserve_hedge(intent:Any)->None:
                if reserve_order: reserve_order(intent,{"kind":"FOCUS_HEDGE","slotId":sid,"cycleId":leg.cycle_id,"leverage":effective,"marginUsd":hedge_margin,"riskReducing":False})
            _audit(ref,"FOCUS_HEDGE_REQUESTED",slot_id=sid,symbol=symbol,side=opp,reason="Multi-Focus portfolio handrem",quantity=need,effectiveLeverage=effective)
            result=execute_leg_once(client,plan,side=PositionSide(opp),action="OPEN",id_prefix=prefix,confirm=True,before_submit=reserve_hedge,new_position_leverage=effective)
            hq,hp,intent_id,fill_id=_confirmed_fill(result);fresh=client.position_risk(symbol);active_qty=abs(_f((_position(fresh,symbol,side) or {}).get("positionAmt")));hedged_qty=abs(_f((_position(fresh,symbol,opp) or {}).get("positionAmt")))
            if abs(active_qty-hedged_qty)>max(active_qty,hedged_qty,1e-12)*.005:
                _audit(ref,"FOCUS_HEDGE_CONFIRMED",slot_id=sid,symbol=symbol,side=opp,reason="partial hedge; correction required",activeQuantity=active_qty,hedgeQuantity=hedged_qty)
                return {"status":"reconciling","action":"FOCUS_HEDGE_CORRECTION","symbol":symbol,"ordersSent":1}
            hedge_leg=OwnedLeg(settings.strategy_id,"strategy2",symbol,opp,leg.cycle_id,settings.version,hedged_qty,hp,0,_hedge_role(sid),(intent_id,) if intent_id else (), (fill_id,) if fill_id else (),(),timestamp_ms,last_order_at_ms=timestamp_ms)
            owned.append(hedge_leg);st=states.get(sid) or _empty_state(sid,symbol,side,str(slot.get("leverageMode","minimum")),int(_f(slot.get("leverage"),settings.leverage)),effective,maximum);st.update({"status":"PARKED","parkedAt":timestamp_ms,"hedgeSide":opp,"hedgeQuantity":hedged_qty});states[sid]=st
            ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"focusLiveSlots":list(states.values()),"multiFocusHighWaterEquity":equity,"focusLiveOrdersSent":1,"lastReason":"FOCUS_PARKED"},merge=True)
            _audit(ref,"FOCUS_HEDGE_CONFIRMED",slot_id=sid,symbol=symbol,side=opp,reason="delta-neutraal bevestigd",activeQuantity=active_qty,hedgeQuantity=hedged_qty)
            _audit(ref,"FOCUS_PARKED",slot_id=sid,symbol=symbol,side=side,reason="handremhedge bevestigd; slot geparkeerd",hedgeSide=opp,hedgeQuantity=hedged_qty)
            return {"status":"executed","action":"FOCUS_PARKED","symbol":symbol,"side":side,"ordersSent":1,"hedgeQuantity":hedged_qty}

    # Across sibling slots preserve Strategy-2 action priority: likely TP/close
    # candidates first, then active management/DCA, then brand-new entries.
    configured_slots=list(enumerate(settings.focus_slots,1))
    def slot_priority(item:tuple[int,dict[str,Any]])->tuple[int,int]:
        index,raw_slot=item;slot=dict(raw_slot);sid=str(slot.get("slotId",f"slot-{index}"));symbol=str(slot.get("pair",slot.get("symbol",""))).upper();side=str(slot.get("side","LONG")).upper()
        leg=_slot_owned(owned,sid);row=_position(working_positions,symbol,side)
        if leg and row:
            mark=_f(row.get("markPrice")) or prices.get(symbol,0.0);entry=leg.weighted_entry
            pnl_pct=((mark/entry)-1) if side=="LONG" and entry>0 else ((entry/mark)-1) if side=="SHORT" and mark>0 else 0.0
            tp_mode=str(slot.get("tpMode",settings.focus_take_profit_mode)).lower()
            if tp_mode=="percent" and pnl_pct>=settings.focus_minimum_profit_pct:return (0,index)
            return (1,index)
        return (2,index)
    configured_slots.sort(key=slot_priority)
    for index,slot_raw in configured_slots:
        slot=dict(slot_raw);slot_id=str(slot.get("slotId",f"slot-{index}")).strip() or f"slot-{index}"
        symbol=str(slot.get("pair",slot.get("symbol",""))).upper().strip();side=str(slot.get("side","LONG")).upper()
        mode=str(slot.get("leverageMode","minimum")).lower();configured=max(1,int(_f(slot.get("leverage"),settings.leverage)))
        start_notional=max(0.0,_f(slot.get("startNotional"),settings.focus_start_order_notional))
        row=_position(working_positions,symbol,side)
        current_leverage=(max(1,int(_f(row.get("leverage")))) if row is not None and _f(row.get("leverage"))>0 else None)
        try: effective,maximum=resolve_slot_leverage(client,slot,settings,existing_leverage=current_leverage)
        except ValueError as exc:
            _audit(ref,"FOCUS_SLOT_SKIPPED_EXACT_LEVERAGE" if mode=="exact" else "FOCUS_SLOT_SKIPPED_MIN_LEVERAGE",
                slot_id=slot_id,symbol=symbol,side=side,reason=str(exc),configuredLeverage=configured)
            current=states.get(slot_id) or _empty_state(slot_id,symbol,side,mode,configured,0,0);current.update({"status":"BLOCKED","recoveryStatus":str(exc)})
            states[slot_id]=current;actions.append({"slotId":slot_id,"action":"LEVERAGE_BLOCKED","reason":str(exc)});continue
        _audit(ref,"FOCUS_SLOT_LEVERAGE_RESOLVED",slot_id=slot_id,symbol=symbol,side=side,reason="leverage policy resolved",
            leverageMode=mode,configuredLeverage=configured,effectiveLeverage=effective,exchangeMaxLeverage=maximum)
        state=states.get(slot_id) or _empty_state(slot_id,symbol,side,mode,configured,effective,maximum)
        state.update({"pair":symbol,"side":side,"leverageMode":mode,"configuredLeverage":configured,"effectiveLeverage":effective,"exchangeMaxLeverage":maximum})
        leg=_slot_owned(owned,slot_id);hedge_leg=_slot_hedge_owned(owned,slot_id)
        if hedge_leg is not None:
            hedge_side=_opposite(side);hedge_row=_position(working_positions,symbol,hedge_side);active_qty=abs(_f((row or {}).get("positionAmt")));hedge_qty=abs(_f((hedge_row or {}).get("positionAmt")))
            diff=active_qty-hedge_qty
            tolerance=max(active_qty,hedge_qty,1e-12)*.005
            if active_qty>0 and abs(diff)<=tolerance:
                state.update({"status":"PARKED","hedgeSide":hedge_side,"hedgeQuantity":hedge_qty,"recoveryStatus":"PARKED_RECONCILED","lastReconciledAt":timestamp_ms});states[slot_id]=state
                _audit(ref,"FOCUS_SLOT_RECONCILED",slot_id=slot_id,symbol=symbol,side=side,reason="geparkeerde hedge exchange-bevestigd",hedgeQuantity=hedge_qty)
                continue
            if active_qty<=0 and hedge_qty<=0:
                owned=[x for x in owned if x.role not in {_slot_role(slot_id),_hedge_role(slot_id)}]
                state=_empty_state(slot_id,symbol,side,mode,configured,effective,maximum);states[slot_id]=state
                _audit(ref,"FOCUS_SLOT_RECONCILED",slot_id=slot_id,symbol=symbol,side=side,reason="parked slot exchange-confirmed flat")
                continue
            if dry_run or settings.mode!="live":
                state.update({"status":"RECONCILING","recoveryStatus":"hedge-correctie simulatie vereist","lastReconciledAt":timestamp_ms});states[slot_id]=state
                return {"status":"simulated","action":"FOCUS_HEDGE_CORRECTION","slotId":slot_id,"symbol":symbol,"ordersSent":0,"difference":diff}
            if remaining<=0:
                state.update({"status":"RECONCILING","pendingAction":"ORDER_BUDGET","lastReconciledAt":timestamp_ms});states[slot_id]=state
                return {"status":"budget-exhausted","action":"FOCUS_HEDGE_CORRECTION","slotId":slot_id,"symbol":symbol,"ordersSent":0}
            if any(isinstance(x,dict) and str(x.get("symbol","")).upper()==symbol for x in (open_orders or [])):
                state.update({"status":"RECONCILING","pendingAction":"OPEN_ORDER_PENDING","lastReconciledAt":timestamp_ms});states[slot_id]=state
                return {"status":"waiting","action":"FOCUS_HEDGE_PENDING","slotId":slot_id,"symbol":symbol,"ordersSent":0}
            correction_qty=abs(diff);mark=_f((row or hedge_row or {}).get("markPrice")) or prices.get(symbol,0.0)
            if correction_qty<=0 or mark<=0:
                state.update({"status":"RECONCILING","recoveryStatus":"hedge-correctie mist betrouwbare quantity/prijs","lastReconciledAt":timestamp_ms});states[slot_id]=state
                continue
            correction_action="OPEN" if diff>0 else "CLOSE"
            correction_side=hedge_side
            correction_margin=correction_qty*mark/max(1,effective) if correction_action=="OPEN" else 0.0
            if correction_action=="OPEN" and correction_margin*1.05>available_remaining:
                state.update({"status":"RECONCILING","pendingAction":"MARGIN","lastReconciledAt":timestamp_ms});states[slot_id]=state
                _audit(ref,"FOCUS_SLOT_SKIPPED_MARGIN",slot_id=slot_id,symbol=symbol,side=correction_side,reason="onvoldoende margin voor hedge-correctie",requiredMargin=correction_margin)
                return {"status":"waiting","action":"FOCUS_PAIR_SKIPPED_MARGIN","slotId":slot_id,"symbol":symbol,"ordersSent":0}
            plan=_plan(client,symbol,mark,correction_qty*mark,effective,working_positions)
            prefix=f"s2mf-hc-{hashlib.sha256(f'{uid}|{slot_id}|{hedge_leg.cycle_id}|{correction_action}|{round(correction_qty,12)}'.encode()).hexdigest()[:9]}"
            def reserve_correction(intent:Any)->None:
                if reserve_order: reserve_order(intent,{"kind":"FOCUS_HEDGE_CORRECTION","slotId":slot_id,"cycleId":hedge_leg.cycle_id,"leverage":effective,"marginUsd":correction_margin,"riskReducing":correction_action=="CLOSE"})
            _audit(ref,"FOCUS_HEDGE_REQUESTED",slot_id=slot_id,symbol=symbol,side=correction_side,reason="parked hedge correction",quantity=correction_qty,action=correction_action)
            if correction_action=="OPEN":
                result=execute_leg_once(client,plan,side=PositionSide(correction_side),action="OPEN",id_prefix=prefix,confirm=True,before_submit=reserve_correction,new_position_leverage=effective)
            else:
                # Protection correction is not a profit-taking exit. It may reduce
                # an oversized hedge even when that hedge leg itself is negative.
                intent=AsterOrderIntent(prefix,symbol,PositionSide(correction_side),plan.quantity,"CLOSE")
                reserve_correction(intent)
                raw_result,_recovered=client.submit_order_once(intent,config=AsterAutomationConfig(enabled=True,mode="live"),confirm=True,hedge_mode_confirmed=True,risk_approved=True)
                if not isinstance(raw_result,dict): raise RuntimeError("hedge-correctie gaf geen geldige Aster response")
                result={"result":raw_result}
            cq,cp,intent_id,fill_id=_confirmed_fill(result)
            fresh=client.position_risk(symbol);new_active=abs(_f((_position(fresh,symbol,side) or {}).get("positionAmt")));new_hedge=abs(_f((_position(fresh,symbol,hedge_side) or {}).get("positionAmt")))
            if abs(new_active-new_hedge)>max(new_active,new_hedge,1e-12)*.005:
                state.update({"status":"RECONCILING","recoveryStatus":"hedge-correctie fill nog niet delta-neutraal","lastReconciledAt":timestamp_ms});states[slot_id]=state
                return {"status":"reconciling","action":"FOCUS_HEDGE_CORRECTION","slotId":slot_id,"symbol":symbol,"ordersSent":1}
            updated_hedge=replace(hedge_leg,quantity=new_hedge,weighted_entry=_f((_position(fresh,symbol,hedge_side) or {}).get("entryPrice"),cp),intent_ids=tuple(dict.fromkeys((*hedge_leg.intent_ids,*((intent_id,) if intent_id else ())))),fill_ids=tuple(dict.fromkeys((*hedge_leg.fill_ids,*((fill_id,) if fill_id else ())))),last_order_at_ms=timestamp_ms)
            owned=[updated_hedge if x.role==_hedge_role(slot_id) else x for x in owned]
            state.update({"status":"PARKED","hedgeSide":hedge_side,"hedgeQuantity":new_hedge,"recoveryStatus":"PARKED_RECONCILED","lastReconciledAt":timestamp_ms,"pendingAction":""});states[slot_id]=state
            ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"focusLiveSlots":list(states.values()),"focusLiveOrdersSent":1,"lastReason":"FOCUS_RECONCILED"},merge=True)
            _audit(ref,"FOCUS_SLOT_RECONCILED",slot_id=slot_id,symbol=symbol,side=side,reason="parked hedge correction exchange-bevestigd",activeQuantity=new_active,hedgeQuantity=new_hedge)
            return {"status":"executed","action":"FOCUS_HEDGE_CORRECTION","slotId":slot_id,"symbol":symbol,"ordersSent":1}
        # Reconcile persisted ownership against exchange truth.
        if leg and row is None:
            owned=[x for x in owned if x is not leg];leg=None;state=_empty_state(slot_id,symbol,side,mode,configured,effective,maximum)
            _audit(ref,"FOCUS_SLOT_RECONCILED",slot_id=slot_id,symbol=symbol,side=side,reason="exchange confirmed flat")
        elif leg and row is not None:
            qty=abs(_f(row.get("positionAmt")));entry=_f(row.get("entryPrice"));mark=_f(row.get("markPrice")) or prices.get(symbol,0.0)
            if qty<=0 or entry<=0: state.update({"status":"RECONCILING","recoveryStatus":"ongeldige exchange position truth"});states[slot_id]=state;continue
            leg=replace(leg,quantity=qty,weighted_entry=entry,last_order_at_ms=max(leg.last_order_at_ms,timestamp_ms))
            owned=[leg if x.role==_slot_role(slot_id) else x for x in owned]
            state.update({"status":"ACTIVE","cycleId":leg.cycle_id,"originalEntry":_f(state.get("originalEntry"),entry) or entry,
                "weightedEntry":entry,"quantity":qty,"notional":qty*entry,"usedMargin":qty*mark/max(1,effective),"dcaCount":leg.dca_count,
                "nextDcaTrigger":_next_trigger(settings,side=side,original=_f(state.get("originalEntry"),entry) or entry,dca_count=leg.dca_count),
                "recoveryStatus":"RECONCILED","lastReconciledAt":timestamp_ms})
        elif row is not None:
            # Backward-compatible migration: an already proven legacy single-Focus
            # leg may become slot-1 ownership only when symbol, side and cycle all
            # match the persisted legacy Focus state and live Aster position.
            qty=abs(_f(row.get("positionAmt")));entry=_f(row.get("entryPrice"));mark=_f(row.get("markPrice")) or prices.get(symbol,0.0)
            owned,migrated,legacy_state=_migrate_legacy_focus_leg(owned,raw_state,slot_id=slot_id,symbol=symbol,side=side,row=row,timestamp_ms=timestamp_ms)
            if migrated is not None:
                leg=migrated;legacy_cycle=leg.cycle_id;original=_f(legacy_state.get("originalEntry"),entry) or entry
                state.update({"status":"ACTIVE","cycleId":legacy_cycle,"createdAt":int(_f(legacy_state.get("openedAt"),leg.created_at_ms)) or leg.created_at_ms,
                    "originalEntry":original,"weightedEntry":entry,"quantity":qty,"notional":qty*entry,"usedMargin":qty*mark/max(1,effective),
                    "dcaCount":leg.dca_count,"nextDcaTrigger":_next_trigger(settings,side=side,original=original,dca_count=leg.dca_count),
                    "realizedPnl":_f(legacy_state.get("realizedPnl")),"recoveryStatus":"MIGRATED_FROM_SINGLE_FOCUS","lastReconciledAt":timestamp_ms})
                _audit(ref,"FOCUS_SLOT_RECONCILED",slot_id=slot_id,symbol=symbol,side=side,reason="legacy single-Focus ownership veilig gemigreerd naar Multi-Focus slot",cycleId=legacy_cycle,dcaNumber=leg.dca_count)
            else:
                # Recover only when the persisted slot cycle plus actual Aster fills prove ownership.
                cycle=str(state.get("cycleId","")).strip();created=int(_f(state.get("createdAt")))
                proven=[]
                if cycle and qty>0 and entry>0:
                    try:
                        proven=[x for x in client.user_trades(symbol,limit=500) if isinstance(x,dict)
                            and str(x.get("symbol","")).upper()==symbol and str(x.get("positionSide","")).upper()==side
                            and (created<=0 or int(_f(x.get("time",x.get("timestamp",0))))>=created)]
                    except Exception: proven=[]
                if proven:
                    leg=OwnedLeg(settings.strategy_id,"strategy2",symbol,side,cycle,settings.version,qty,entry,int(_f(state.get("dcaCount"))),_slot_role(slot_id),
                        (),tuple(str(x.get("id",x.get("tradeId",x.get("orderId","")))) for x in proven if str(x.get("id",x.get("tradeId",x.get("orderId",""))))),(),created or timestamp_ms,last_order_at_ms=timestamp_ms)
                    owned.append(leg);state.update({"status":"ACTIVE","weightedEntry":entry,"quantity":qty,"notional":qty*entry,"recoveryStatus":"RECOVERED_FROM_ASTER_FILLS","lastReconciledAt":timestamp_ms})
                    _audit(ref,"FOCUS_SLOT_RECONCILED",slot_id=slot_id,symbol=symbol,side=side,reason="ownership hersteld uit persisted cycle + Aster fills")
                else:
                    state.update({"status":"RECONCILING","recoveryStatus":"exchange exposure zonder bewezen Multi-Focus ownership"})
                    states[slot_id]=state;actions.append({"slotId":slot_id,"action":"RECONCILING"});continue
        mark=_f((row or {}).get("markPrice")) or prices.get(symbol,0.0)
        if mark<=0:
            state.update({"status":"WAITING","recoveryStatus":"geen betrouwbare actuele prijs"});states[slot_id]=state;continue
        if any(isinstance(x,dict) and str(x.get("symbol","")).upper()==symbol for x in (open_orders or [])):
            state.update({"status":"WAITING","pendingAction":"OPEN_ORDER_PENDING"});states[slot_id]=state
            _audit(ref,"FOCUS_SLOT_OPEN_ORDER_PENDING",slot_id=slot_id,symbol=symbol,side=side,reason="open Aster order")
            continue
        action="";notional=0.0;evidence=None
        if leg is None:
            if brake_block: state.update({"status":"BRAKE","pendingAction":""});states[slot_id]=state;continue
            action="OPEN";notional=start_notional
        else:
            entry=leg.weighted_entry;qty=leg.quantity
            pnl_pct=((mark/entry)-1) if side=="LONG" else ((entry/mark)-1)
            tp_mode=str(slot.get("tpMode",settings.focus_take_profit_mode)).lower()
            tp_usdt=max(0.0,_f(slot.get("tpTargetUsdt"),settings.focus_take_profit_usdt))
            if tp_mode=="usdt":
                try:
                    evidence=_close_evidence(client,uid=uid,leg=leg,mark=mark,reason=f"netto USDT target {tp_usdt:.8g}",target_usdt=tp_usdt)
                except Exception as exc:
                    state.update({"status":"WAITING","recoveryStatus":f"TP kostendata onbetrouwbaar: {exc}"});states[slot_id]=state;continue
                if evidence.expected_net>=max(0.01,tp_usdt): action="CLOSE"
            elif pnl_pct>=settings.focus_minimum_profit_pct:
                try:evidence=_close_evidence(client,uid=uid,leg=leg,mark=mark,reason=f"TP {settings.focus_minimum_profit_pct*100:.4g}%")
                except Exception as exc:
                    state.update({"status":"WAITING","recoveryStatus":f"TP kostendata onbetrouwbaar: {exc}"});states[slot_id]=state;continue
                action="CLOSE"
            if not action and settings.focus_dca_enabled and (settings.focus_dca_unlimited or leg.dca_count<settings.focus_max_dca) and not brake_block:
                trigger=_next_trigger(settings,side=side,original=_f(state.get("originalEntry"),entry) or entry,dca_count=leg.dca_count)
                if trigger>0 and ((side=="LONG" and mark<=trigger) or (side=="SHORT" and mark>=trigger)):
                    action="DCA";notional=_dca_notional(settings,leg.dca_count)
        if not action:
            states[slot_id]=state;continue
        if dry_run or settings.mode!="live":
            actions.append({"slotId":slot_id,"action":action,"symbol":symbol,"side":side,"simulated":True});states[slot_id]=state;continue
        if remaining<=0: state.update({"status":"WAITING","pendingAction":"ORDER_BUDGET"});states[slot_id]=state;continue
        if action in {"OPEN","DCA"}:
            required=notional/max(1,effective)
            current_slot_notional=_f(state.get("notional"))
            if current_slot_notional+notional>settings.focus_max_budget_usd+1e-9:
                state.update({"status":"WAITING","pendingAction":"FOCUS_BUDGET"});states[slot_id]=state
                _audit(ref,"FOCUS_SLOT_SKIPPED_MARGIN",slot_id=slot_id,symbol=symbol,side=side,reason="Focus-budget bereikt",proposedNotional=notional)
                continue
            liq=_f((row or {}).get("liquidationPrice"));liq_distance=abs(mark-liq)/mark if liq>0 and mark>0 else 1.0
            if action=="DCA" and (liq_distance<.05 or maint_ratio>=settings.emergency_margin_ratio):
                state.update({"status":"WAITING","pendingAction":"RISK"});states[slot_id]=state
                _audit(ref,"FOCUS_SLOT_SKIPPED_MARGIN",slot_id=slot_id,symbol=symbol,side=side,reason="liquidation/maintenance risk blokkeert DCA",liquidationDistance=liq_distance,maintenanceMarginRatio=maint_ratio)
                continue
            if required*1.05>available_remaining or required>strategy_margin_remaining+1e-9:
                state.update({"status":"WAITING","pendingAction":"MARGIN"});states[slot_id]=state
                _audit(ref,"FOCUS_SLOT_SKIPPED_MARGIN",slot_id=slot_id,symbol=symbol,side=side,reason="onvoldoende available/Strategy-2 margin",requiredMargin=required,availableRemaining=available_remaining,strategyMarginRemaining=strategy_margin_remaining)
                continue
            plan=_plan(client,symbol,mark,notional,effective,working_positions)
            cycle=state.get("cycleId") or f"mfocus-{hashlib.sha256(f'{uid}|{slot_id}|{symbol}|{side}|{timestamp_ms}'.encode()).hexdigest()[:16]}"
            dca_no=(leg.dca_count+1) if leg else 0
            prefix=f"s2mf-{hashlib.sha256(f'{uid}|{slot_id}|{cycle}|{action}|{dca_no}'.encode()).hexdigest()[:12]}"
            def reserve(intent:Any, *, _action=action,_cycle=cycle,_dca=dca_no,_lev=effective,_margin=required)->None:
                if reserve_order: reserve_order(intent,{"kind":f"FOCUS_SLOT_{_action}","slotId":slot_id,"cycleId":_cycle,"leverage":_lev,"marginUsd":_margin,"dcaNumber":_dca or None})
            try:
                result=execute_leg_once(client,plan,side=PositionSide(side),action="OPEN",id_prefix=prefix,confirm=True,before_submit=reserve,new_position_leverage=effective)
            except NewPositionLeverageBlocked as exc:
                state.update({"status":"BLOCKED","pendingAction":"","recoveryStatus":exc.reason_code,"lastReconciledAt":timestamp_ms});states[slot_id]=state
                _audit(ref,"FOCUS_SLOT_SKIPPED_MIN_LEVERAGE",slot_id=slot_id,symbol=symbol,side=side,reason=str(exc),configuredLeverage=configured,effectiveLeverage=effective)
                actions.append({"slotId":slot_id,"action":"LEVERAGE_BLOCKED","symbol":symbol,"side":side,"reason":exc.reason_code})
                continue
            q,p,intent_id,fill_id=_confirmed_fill(result);filled=q*p
            if leg is None:
                leg=OwnedLeg(settings.strategy_id,"strategy2",symbol,side,cycle,settings.version,q,p,0,_slot_role(slot_id),
                    (intent_id,) if intent_id else (), (fill_id,) if fill_id else (),(),timestamp_ms,last_order_at_ms=timestamp_ms)
                owned.append(leg);original=p
                _audit(ref,"FOCUS_SLOT_ENTRY_OPENED",slot_id=slot_id,symbol=symbol,side=side,reason="manual Multi-Focus entry",effectiveLeverage=effective)
            else:
                total=leg.quantity+q;avg=(leg.quantity*leg.weighted_entry+q*p)/total
                leg=replace(leg,quantity=total,weighted_entry=avg,dca_count=leg.dca_count+1,
                    intent_ids=tuple(dict.fromkeys((*leg.intent_ids,*((intent_id,) if intent_id else ())))),fill_ids=tuple(dict.fromkeys((*leg.fill_ids,*((fill_id,) if fill_id else ())))),last_order_at_ms=timestamp_ms)
                owned=[leg if x.role==_slot_role(slot_id) else x for x in owned];original=_f(state.get("originalEntry"),p) or p
                _audit(ref,"FOCUS_SLOT_DCA",slot_id=slot_id,symbol=symbol,side=side,reason="DCA trigger",dcaNumber=leg.dca_count,effectiveLeverage=effective)
            state.update({"status":"ACTIVE","cycleId":cycle,"createdAt":int(_f(state.get("createdAt"))) or timestamp_ms,"originalEntry":original,"weightedEntry":leg.weighted_entry,"quantity":leg.quantity,
                "notional":leg.quantity*leg.weighted_entry,"usedMargin":leg.quantity*mark/max(1,effective),"dcaCount":leg.dca_count,
                "nextDcaTrigger":_next_trigger(settings,side=side,original=original,dca_count=leg.dca_count),"pendingAction":"","lastReconciledAt":timestamp_ms})
            available_remaining=max(0.0,available_remaining-required);strategy_margin_remaining=max(0.0,strategy_margin_remaining-required)
        else:
            assert leg is not None and evidence is not None
            rules=ContractRules.from_exchange_info(next(x for x in client.public_exchange_info().get("symbols",()) if str(x.get("symbol","")).upper()==symbol))
            close_qty=rules.market_quantity(Decimal(str(leg.quantity)),Decimal(str(mark)))
            plan=PairExecutionPlan(symbol,close_qty,close_qty*Decimal(str(mark)),effective,rules.tick_size,rules.market_quantity_step,rules.market_min_quantity,rules.min_notional)
            _audit(ref,"FOCUS_SLOT_TP_TARGET_REACHED",slot_id=slot_id,symbol=symbol,side=side,reason=evidence.reason,expectedNet=evidence.expected_net)
            prefix=f"s2mf-{hashlib.sha256(f'{uid}|{slot_id}|{leg.cycle_id}|TP_CLOSE'.encode()).hexdigest()[:12]}"
            def reserve_close(intent:Any)->None:
                if reserve_order: reserve_order(intent,{"kind":"FOCUS_SLOT_TP_CLOSE","slotId":slot_id,"cycleId":leg.cycle_id,"leverage":effective,"marginUsd":0.0,"riskReducing":True})
            _audit(ref,"FOCUS_SLOT_CLOSE_REQUESTED",slot_id=slot_id,symbol=symbol,side=side,reason=evidence.reason,expectedNet=evidence.expected_net)
            result=execute_leg_once(client,plan,side=PositionSide(side),action="CLOSE",id_prefix=prefix,confirm=True,close_evidence=evidence,
                close_audit=lambda event:ref.collection("audit").add(event),before_submit=reserve_close)
            q,p,_,_=_confirmed_fill(result);realized=_gross_pnl(side,leg.weighted_entry,p,q)
            owned=[x for x in owned if x.role!=_slot_role(slot_id)]
            state=_empty_state(slot_id,symbol,side,mode,configured,effective,maximum);state["realizedPnl"]=_f(states.get(slot_id,{}).get("realizedPnl"))+realized;state["status"]="RESTART_READY"
            _audit(ref,"FOCUS_SLOT_CLOSE_CONFIRMED",slot_id=slot_id,symbol=symbol,side=side,reason=evidence.reason,realizedPnl=realized)
            _audit(ref,"FOCUS_SLOT_RESTARTED",slot_id=slot_id,symbol=symbol,side=side,reason="slot blijft geconfigureerd; volgende scan opent nieuwe cycle")
        states[slot_id]=state;orders_sent+=1;remaining-=1;actions.append({"slotId":slot_id,"action":action,"symbol":symbol,"side":side,"ordersSent":1})
    ordered=[states.get(str(slot.get("slotId",f"slot-{i}"))) for i,slot in enumerate(settings.focus_slots,1)]
    ordered=[x for x in ordered if isinstance(x,dict)]
    ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"focusLiveSlots":ordered,"focusLiveAt":time.time(),
        "focusLiveOrdersSent":orders_sent,"phase":"FOCUS_LIVE","lastReason":"MULTI_FOCUS"},merge=True)
    return {"status":"executed" if orders_sent else "waiting","action":"FOCUS_MULTI" if orders_sent else "FOCUS_HOLD",
        "ordersSent":orders_sent,"actions":actions,"slots":ordered}
