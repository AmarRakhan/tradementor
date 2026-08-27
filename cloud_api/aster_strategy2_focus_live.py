"""Live execution adapter for Strategy-2 Focus / Coin van het moment.

Selection, DCA and exit decisions come from the exact same pure Focus planner
used by Shadow. This module only converts one already-approved Focus decision
into one idempotent Aster LONG order and persists confirmed fill truth.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, Callable
import hashlib
import math
import time

from aster_close_guard import AsterCloseBlocked, CloseEvidence
from aster_execution import PairExecutionPlan, execute_leg_once, plan_pair, planning_brackets
from aster_gateway import ContractRules, PositionSide
from aster_strategy2 import Strategy2Config
from aster_strategy2_focus import (
    FocusState, apply_focus_buy, next_dca_trigger, reset_after_full_exit,
    select_focus_pair,
)
from aster_strategy2_focus_adapter import (
    current_focus_markets, focus_state_from_mapping, focus_state_to_mapping,
)
from aster_strategy2_focus_shadow import FocusRiskSnapshot, FocusShadowInputs, plan_focus_shadow
from aster_strategy2_runtime import active_position_map, owned_from_mapping, owned_to_mapping
from aster_strategy2_state import OwnedLeg


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _owned(raw: dict[str, Any]) -> list[OwnedLeg]:
    result: list[OwnedLeg] = []
    for row in raw.get("ownedLegs", ()) if isinstance(raw.get("ownedLegs"), list) else ():
        try:
            result.append(owned_from_mapping(row))
        except (TypeError, ValueError):
            continue
    return result


def _focus_owned(owned: list[OwnedLeg]) -> list[OwnedLeg]:
    return [leg for leg in owned if str(leg.role).upper() == "FOCUS"]


def _strategy_margin(settings: Strategy2Config, owned: list[OwnedLeg], positions: list[dict[str, Any]]) -> float:
    pos = active_position_map(positions)
    total = 0.0
    for leg in owned:
        row = pos.get((leg.symbol, leg.side))
        if not row:
            continue
        quantity = abs(_f(row.get("positionAmt")))
        mark = _f(row.get("markPrice")) or _f(row.get("entryPrice"))
        leverage = max(1.0, _f(row.get("leverage"), settings.leverage))
        total += quantity * mark / leverage
    return total


def _focus_market_price(report: dict[str, Any], symbol: str, fallback: float = 0.0) -> float:
    for row in report.get("ranking", ()) if isinstance(report.get("ranking"), list) else ():
        if isinstance(row, dict) and str(row.get("symbol", "")).upper() == symbol.upper():
            price = _f(row.get("price"))
            if price > 0:
                return price
    return fallback


def _symbol_row(client: Any, symbol: str) -> dict[str, Any]:
    info = client.public_exchange_info()
    rows = info.get("symbols", ()) if isinstance(info, dict) else ()
    row = next((x for x in rows if isinstance(x, dict) and str(x.get("symbol", "")).upper() == symbol.upper()), None)
    if row is None:
        raise ValueError(f"{symbol}: contract ontbreekt in Aster exchangeInfo")
    return row


def _position_for(positions: list[dict[str, Any]], symbol: str) -> dict[str, Any] | None:
    return active_position_map(positions).get((symbol.upper(), "LONG"))


def _preflight_state(raw: dict[str, Any], positions: list[dict[str, Any]]) -> tuple[FocusState, list[OwnedLeg], bool, str]:
    state = focus_state_from_mapping(raw.get("focusLiveState"))
    owned = _owned(raw)
    focus = _focus_owned(owned)
    if len(focus) > 1:
        return state, owned, False, "Meer dan één Focus-ownershipleg gevonden; live Focus fail-closed"
    if not focus:
        if state.total_quantity > 0:
            return state, owned, False, "Focus-state heeft exposure maar bewezen Focus-ownership ontbreekt"
        return state, owned, True, "flat"
    leg = focus[0]
    row = _position_for(positions, leg.symbol)
    if row is None:
        # A reliable position snapshot proves this Focus leg is flat (manual or
        # previous confirmed close). Drop only the Focus ownership row.
        owned = [item for item in owned if item is not leg]
        state = reset_after_full_exit(state, realized_pnl=0.0,
            theoretical_portfolio_value=state.theoretical_portfolio_value)
        return state, owned, True, "Focus-leg is exchange-confirmed flat"
    quantity = abs(_f(row.get("positionAmt")))
    entry = _f(row.get("entryPrice"))
    mark = _f(row.get("markPrice")) or entry
    leverage = max(1.0, _f(row.get("leverage"), 1.0))
    if quantity <= 0 or entry <= 0:
        return state, owned, False, "Actieve Focus-positie heeft ongeldige exchange-truth"
    state = replace(state, active_pair=leg.symbol, cycle_id=leg.cycle_id,
        original_entry=state.original_entry or entry, weighted_entry=entry,
        total_quantity=quantity,
        total_notional=max(state.total_notional, quantity * entry),
        used_margin=quantity * mark / leverage,
        focus_budget_used=max(state.focus_budget_used, quantity * entry))
    return state, owned, True, "Focus-positie gereconcilieerd"


def build_focus_live_plan(*, client: Any, raw_state: dict[str, Any], settings: Strategy2Config,
                          account: dict[str, Any], positions: list[dict[str, Any]],
                          timestamp_ms: int) -> tuple[dict[str, Any], FocusState, list[OwnedLeg]]:
    state, owned, reliable, preflight_reason = _preflight_state(raw_state, positions)
    if not reliable:
        return ({"mode":"focus-live","ordersSent":0,"decision":{"kind":"HOLD","symbol":state.active_pair,
            "reason":preflight_reason,"status":"Ownership hold"},"state":focus_state_to_mapping(state),
            "ranking":[],"selectionReason":preflight_reason,"readOnly":False}, state, owned)
    markets = current_focus_markets(client, settings)
    cycle_open = bool(state.active_pair and state.total_quantity > 0 and state.weighted_entry > 0)
    selected, ranking, _ = select_focus_pair(list(markets), selection_mode=settings.focus_selection_mode,
        manual_pair=settings.focus_manual_pair, active_pair=state.active_pair, cycle_open=cycle_open,
        minimum_quote_volume=settings.minimum_quote_volume_24h_usdt,
        minimum_liquidity_score=settings.focus_min_liquidity_score)
    selected_symbol = state.active_pair or (selected.symbol if selected else "")
    remaining = 0.0
    invalid_capacity_symbols: set[str] = set()
    if selected_symbol:
        try:
            remaining = _f(client.remaining_openable_notional_value(selected_symbol, settings.leverage))
        except Exception:
            remaining = 0.0
            invalid_capacity_symbols.add(selected_symbol)
    if not cycle_open and settings.focus_selection_mode == "automatic" and remaining <= 0:
        for row in ranking:
            symbol = str(row.symbol).upper()
            if not row.eligible or symbol == selected_symbol:
                continue
            try:
                candidate_remaining = _f(client.remaining_openable_notional_value(symbol, settings.leverage))
            except Exception:
                invalid_capacity_symbols.add(symbol)
                continue
            if candidate_remaining > 0:
                selected_symbol = symbol
                remaining = candidate_remaining
                break
            invalid_capacity_symbols.add(symbol)
        if selected_symbol:
            invalid_capacity_symbols.discard(selected_symbol)
        if invalid_capacity_symbols:
            markets = tuple(m for m in markets if m.symbol.upper() not in invalid_capacity_symbols)
    equity = _f(account.get("totalMarginBalance"), _f(account.get("totalWalletBalance")))
    available = _f(account.get("availableBalance"))
    focus_keys={(leg.symbol,leg.side) for leg in _focus_owned(owned)}
    legacy_count=sum(1 for key in active_position_map(positions) if key not in focus_keys)
    focus_row=_position_for(positions, selected_symbol) if selected_symbol else None
    liquidation_distance=1.0
    if focus_row:
        mark=_f(focus_row.get("markPrice")) or _f(focus_row.get("entryPrice"));liq=_f(focus_row.get("liquidationPrice"))
        if mark>0 and liq>0:liquidation_distance=abs(mark-liq)/mark
    risk = FocusRiskSnapshot(portfolio_equity=equity, available_margin=available,
        strategy_margin_used=_strategy_margin(settings, owned, positions),
        strategy_budget_margin=max(0.0, equity * settings.strategy_budget),
        exchange_max_notional_remaining=max(0.0, remaining),
        liquidation_distance_pct=liquidation_distance,
        minimum_liquidation_distance_pct=.05,
        maintenance_margin_ratio=_f(account.get("totalMaintMargin"))/equity if equity>0 else 1.0,
        maximum_maintenance_margin_ratio=settings.emergency_margin_ratio)
    # Same pure planner as Shadow; only its execution adapter differs.
    planner_settings=replace(settings,focus_shadow_enabled=True)
    report=plan_focus_shadow(FocusShadowInputs(config=planner_settings,markets=markets,state=state,risk=risk,
        timestamp_ms=timestamp_ms,legacy_open_positions=legacy_count,
        current_strategy2_metrics={"portfolioEquity":equity,"strategyMarginUsed":risk.strategy_margin_used,
            "activePositionLegs":len(active_position_map(positions))}))
    report["mode"]="focus-live";report["readOnly"]=False;report["ordersSent"]=0;report["preflightReason"]=preflight_reason
    return report,state,owned


def _confirmed_fill(result: dict[str, Any]) -> tuple[float, float, str, str]:
    row=result.get("result") if isinstance(result.get("result"),dict) else {}
    quantity=abs(_f(row.get("executedQty")));price=_f(row.get("avgPrice"))
    if quantity<=0 or price<=0:
        raise RuntimeError("Bevestigde Focus-order mist werkelijk gevulde hoeveelheid of gemiddelde prijs")
    intent=str(row.get("clientOrderId","")).strip();fill=str(row.get("orderId",intent)).strip()
    return quantity,price,intent,fill


def _upsert_focus_owned(owned:list[OwnedLeg],*,settings:Strategy2Config,state:FocusState,quantity:float,
                        price:float,intent_id:str,fill_id:str,is_dca:bool,timestamp_ms:int)->list[OwnedLeg]:
    focus=_focus_owned(owned);existing=focus[0] if focus else None
    if existing is None:
        leg=OwnedLeg(settings.strategy_id,"strategy2",state.active_pair,"LONG",state.cycle_id,settings.version,
            quantity,price,0,"FOCUS",tuple(x for x in (intent_id,) if x),tuple(x for x in (fill_id,) if x),(),
            timestamp_ms,last_order_at_ms=timestamp_ms)
        return [*owned,leg]
    total=existing.quantity+quantity
    average=(existing.quantity*existing.weighted_entry+quantity*price)/total if total>0 else price
    updated=replace(existing,quantity=total,weighted_entry=average,dca_count=existing.dca_count+(1 if is_dca else 0),
        intent_ids=tuple(dict.fromkeys((*existing.intent_ids,*((intent_id,) if intent_id else ())))),
        fill_ids=tuple(dict.fromkeys((*existing.fill_ids,*((fill_id,) if fill_id else ())))),last_order_at_ms=timestamp_ms)
    return [updated if item is existing else item for item in owned]


def _close_evidence(client:Any,*,uid:str,leg:OwnedLeg,row:dict[str,Any],quantity:float,mark:float,reason:str)->CloseEvidence:
    try:
        trades=client.user_trades(leg.symbol,limit=500);income=client.income_history(limit=500)
    except Exception as exc:
        raise AsterCloseBlocked({"event":"AUTOMATIC_ASTER_CLOSE_BLOCKED","blockReason":f"Focus-kostendata onbetrouwbaar: {exc}","message":"Focus close fail-closed"}) from exc
    relevant=[x for x in trades if isinstance(x,dict) and str(x.get("symbol","")).upper()==leg.symbol
        and str(x.get("positionSide","")).upper()=="LONG" and int(_f(x.get("time",x.get("timestamp",0))))>=leg.created_at_ms]
    ratio=min(1.0,quantity/max(leg.quantity,1e-12));entry_fees=sum(abs(_f(x.get("commission"))) for x in relevant)*ratio
    funding=sum(_f(x.get("income")) for x in income if isinstance(x,dict) and str(x.get("symbol","")).upper()==leg.symbol
        and str(x.get("incomeType","")).upper()=="FUNDING_FEE" and int(_f(x.get("time",0)))>=leg.created_at_ms)*ratio
    notional=quantity*mark;gross=(mark-leg.weighted_entry)*quantity
    return CloseEvidence(uid,leg.symbol,"LONG","strategy2:FOCUS",reason,quantity,leg.weighted_entry,mark,gross,
        entry_fees,notional*.0005,funding,notional*.001,ownership_reliable=True,fills_reliable=bool(relevant),
        prices_reliable=mark>0,costs_reliable=True)


def run_focus_live_step(*,client:Any,ref:Any,raw_state:dict[str,Any],settings:Strategy2Config,uid:str,
                        account:dict[str,Any],positions:list[dict[str,Any]],timestamp_ms:int,
                        dry_run:bool=False,order_budget:int|None=None,reserve_order:Callable[[Any,dict[str,Any]],None]|None=None,
                        open_orders:list[dict[str,Any]]|None=None)->dict[str,Any]|None:
    if settings.trading_mode!="focus" or not settings.focus_live_enabled:return None
    report,previous,owned=build_focus_live_plan(client=client,raw_state=raw_state,settings=settings,
        account=account,positions=positions,timestamp_ms=timestamp_ms)
    planned=focus_state_from_mapping(report.get("state"));decision=report.get("decision") if isinstance(report.get("decision"),dict) else {}
    kind=str(decision.get("kind","HOLD")).upper();symbol=str(decision.get("symbol",planned.active_pair)).upper()
    if kind=="HOLD":
        ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"focusLiveState":focus_state_to_mapping(planned),
            "focusLiveReport":report,"focusLiveAt":time.time()},merge=True)
        return {"status":"waiting","action":"FOCUS_HOLD","reason":str(decision.get("reason","runner blijft open")),"ordersSent":0,"focus":report}
    if dry_run or settings.mode!="live":
        return {"status":"simulated","action":f"FOCUS_{kind}","symbol":symbol,"ordersSent":0,"focus":report}
    if order_budget is not None and order_budget<1:
        return {"status":"budget-exhausted","action":f"FOCUS_{kind}","symbol":symbol,"ordersSent":0}
    relevant_open_orders=[row for row in (open_orders or []) if isinstance(row,dict) and str(row.get("symbol","")).upper()==symbol]
    if relevant_open_orders:
        return {"status":"waiting","action":"FOCUS_OPEN_ORDER_PENDING","symbol":symbol,"ordersSent":0,
            "reason":"Bestaande open Aster-order op Focus-pair; geen tweede order verzonden"}
    market_price=_focus_market_price(report,symbol,_f((_position_for(positions,symbol) or {}).get("markPrice")))
    if market_price<=0:raise ValueError(f"{symbol}: Focus heeft geen betrouwbare actuele prijs")

    if kind in {"OPEN","DCA"}:
        if kind=="DCA" and not _focus_owned(owned):
            raise RuntimeError("Focus DCA geblokkeerd: bewezen Focus-ownership ontbreekt")
        cycle=planned.cycle_id or previous.cycle_id or f"focus-{hashlib.sha256(f'{uid}|{symbol}|{timestamp_ms}'.encode()).hexdigest()[:16]}"
        pending=replace(planned,active_pair=symbol,cycle_id=cycle,last_action=f"{kind}_PENDING",last_reason=str(decision.get("reason","")))
        ref.set({"focusLiveState":focus_state_to_mapping(pending),"focusLiveAt":time.time()},merge=True)
        symbol_row=_symbol_row(client,symbol);brackets=planning_brackets(client,[],symbol,settings.leverage)
        existing_notional=sum(abs(_f(x.get("positionAmt")))*(_f(x.get("markPrice")) or _f(x.get("entryPrice"))) for x in positions if str(x.get("symbol","")).upper()==symbol)
        plan=plan_pair(symbol_row,brackets,market_price,_f(decision.get("notional")),accepted_leverage=settings.leverage,
            existing_contract_notional=existing_notional)
        prefix=f"s2f-{hashlib.sha256(f'{uid}|{cycle}|{kind}|{previous.dca_count}'.encode()).hexdigest()[:12]}"
        def reserve(intent:Any)->None:
            if reserve_order:reserve_order(intent,{"kind":f"FOCUS_{kind}","cycleId":cycle,"leverage":settings.leverage,
                "marginUsd":float(plan.notional_per_leg)/max(1,settings.leverage),"dcaNumber":previous.dca_count+1 if kind=="DCA" else None})
        result=execute_leg_once(client,plan,side=PositionSide.LONG,action="OPEN",id_prefix=prefix,confirm=True,
            before_submit=reserve,new_position_leverage=settings.leverage)
        quantity,price,intent_id,fill_id=_confirmed_fill(result);notional=quantity*price
        state=apply_focus_buy(pending,price=price,notional=notional,leverage=settings.leverage,timestamp_ms=timestamp_ms,
            is_dca=(kind=="DCA"),reason=str(decision.get("reason","")))
        state=replace(state,next_dca_trigger=next_dca_trigger(original_entry=state.original_entry,dca_count=state.dca_count,
            max_dca=settings.focus_max_dca,distance_pct=settings.focus_dca_distance,mode=settings.focus_dca_mode))
        owned=_upsert_focus_owned(owned,settings=settings,state=state,quantity=quantity,price=price,intent_id=intent_id,
            fill_id=fill_id,is_dca=(kind=="DCA"),timestamp_ms=timestamp_ms)
        report["state"]=focus_state_to_mapping(state);report["ordersSent"]=1;report["executedFill"]={"quantity":quantity,"price":price,"notional":notional}
        ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"focusLiveState":report["state"],"focusLiveReport":report,
            "focusLiveAt":time.time(),"focusLiveOrdersSent":1,"phase":"FOCUS_LIVE","lastReason":str(decision.get("reason",""))},merge=True)
        return {"status":"executed","action":f"FOCUS_{kind}","symbol":symbol,"side":"LONG","ordersSent":1,"focus":report}

    focus=_focus_owned(owned)
    if len(focus)!=1:raise RuntimeError("Focus close geblokkeerd: exact één bewezen Focus-ownershipleg vereist")
    leg=focus[0];row=_position_for(positions,leg.symbol)
    if row is None:raise RuntimeError("Focus close geblokkeerd: exchange-positie ontbreekt")
    actual_qty=abs(_f(row.get("positionAmt")));entry=_f(row.get("entryPrice")) or leg.weighted_entry
    mark=_f(row.get("markPrice")) or market_price
    fraction=1.0 if kind=="CLOSE" else max(0.0,min(1.0,_f(decision.get("close_fraction"))))
    rules=ContractRules.from_exchange_info(_symbol_row(client,leg.symbol));requested=Decimal(str(actual_qty*fraction))
    try:close_qty=rules.market_quantity(requested,Decimal(str(mark)))
    except Exception as exc:
        if kind=="PARTIAL_TP":
            skipped=replace(planned,last_action="PARTIAL_TP_SKIPPED",last_reason=f"Partial TP overgeslagen: {exc}")
            report["state"]=focus_state_to_mapping(skipped);report["decision"]={**decision,"kind":"HOLD","reason":skipped.last_reason}
            ref.set({"focusLiveState":report["state"],"focusLiveReport":report,"focusLiveAt":time.time()},merge=True)
            return {"status":"waiting","action":"FOCUS_PARTIAL_SKIPPED","symbol":leg.symbol,"ordersSent":0,"reason":skipped.last_reason}
        raise
    remaining=Decimal(str(actual_qty))-close_qty
    if kind=="PARTIAL_TP" and remaining>0 and ((rules.market_min_quantity and remaining<rules.market_min_quantity) or (rules.min_notional and remaining*Decimal(str(mark))<rules.min_notional)):
        skipped=replace(planned,last_action="PARTIAL_TP_SKIPPED",last_reason="Partial TP overgeslagen om geen Aster-dustpositie achter te laten")
        report["state"]=focus_state_to_mapping(skipped);report["decision"]={**decision,"kind":"HOLD","reason":skipped.last_reason}
        ref.set({"focusLiveState":report["state"],"focusLiveReport":report,"focusLiveAt":time.time()},merge=True)
        return {"status":"waiting","action":"FOCUS_PARTIAL_SKIPPED","symbol":leg.symbol,"ordersSent":0,"reason":skipped.last_reason}
    notional=float(close_qty)*mark;plan=PairExecutionPlan(leg.symbol,close_qty,Decimal(str(notional)),int(_f(row.get("leverage"),settings.leverage)),
        rules.tick_size,rules.market_quantity_step,rules.market_min_quantity,rules.min_notional)
    evidence=_close_evidence(client,uid=uid,leg=leg,row=row,quantity=float(close_qty),mark=mark,reason=str(decision.get("reason","")))
    prefix=f"s2f-{hashlib.sha256(f'{uid}|{leg.cycle_id}|{kind}|{len(planned.partials_taken)}'.encode()).hexdigest()[:12]}"
    def reserve_close(intent:Any)->None:
        if reserve_order:reserve_order(intent,{"kind":f"FOCUS_{kind}","cycleId":leg.cycle_id,"leverage":plan.leverage,
            "marginUsd":0.0,"dcaNumber":None,"riskReducing":True})
    result=execute_leg_once(client,plan,side=PositionSide.LONG,action="CLOSE",id_prefix=prefix,confirm=True,
        close_evidence=evidence,close_audit=lambda event:ref.collection("audit").add(event),before_submit=reserve_close)
    closed_qty,closed_price,intent_id,fill_id=_confirmed_fill(result);realized=(closed_price-entry)*closed_qty
    if kind=="PARTIAL_TP" and closed_qty<actual_qty-1e-12:
        remain=max(0.0,actual_qty-closed_qty);ratio=remain/max(actual_qty,1e-12)
        state=replace(planned,total_quantity=remain,total_notional=previous.total_notional*ratio,
            used_margin=previous.used_margin*ratio,focus_budget_used=previous.focus_budget_used*ratio,
            realized_pnl=previous.realized_pnl+realized,last_action="PARTIAL_TP",last_reason=str(decision.get("reason","")))
        updated=replace(leg,quantity=remain,weighted_entry=entry,
            intent_ids=tuple(dict.fromkeys((*leg.intent_ids,*((intent_id,) if intent_id else ())))),
            fill_ids=tuple(dict.fromkeys((*leg.fill_ids,*((fill_id,) if fill_id else ())))),last_order_at_ms=timestamp_ms)
        owned=[updated if item is leg else item for item in owned]
    else:
        state=reset_after_full_exit(planned,realized_pnl=realized,theoretical_portfolio_value=previous.theoretical_portfolio_value+realized)
        owned=[item for item in owned if item is not leg]
    report["state"]=focus_state_to_mapping(state);report["ordersSent"]=1;report["executedFill"]={"quantity":closed_qty,"price":closed_price,"notional":closed_qty*closed_price,"realizedPnl":realized}
    ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"focusLiveState":report["state"],"focusLiveReport":report,
        "focusLiveAt":time.time(),"focusLiveOrdersSent":1,"phase":"FOCUS_LIVE","lastReason":str(decision.get("reason",""))},merge=True)
    return {"status":"executed","action":f"FOCUS_{kind}","symbol":leg.symbol,"side":"LONG","ordersSent":1,"focus":report}
