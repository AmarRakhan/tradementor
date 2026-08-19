"""Deterministic per-account Money Grabber scan planner.

The planner never performs I/O. Production and shadow adapters must provide a
fresh reconciled snapshot and persist the returned state before execution.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
import hashlib

from aster_strategy2 import Strategy2Config
from money_grabber import (Intent, NetValueEvidence, ProtectedPair, Round,
    normal_action_allowed, observe_round_target, plan_pair_close, plan_protection)

MAX_ORDERS_PER_SCAN=15


@dataclass(frozen=True)
class Position:
    symbol:str
    side:str
    notional:float
    weighted_entry:float
    mark_price:float
    unrealized_pnl:float=0.0
    funding:float=0.0
    paid_fees:float=0.0
    expected_exit_fees:float=0.0
    slippage_buffer:float=0.0
    reliable:bool=True


@dataclass(frozen=True)
class ScanSnapshot:
    account_id:str
    scan_id:str
    round:Round
    pairs:tuple[ProtectedPair,...]
    positions:tuple[Position,...]
    net_value:NetValueEvidence
    hedge_mode:bool
    ownership_reliable:bool
    exchange_reliable:bool
    orders_known:bool
    contracts_known:bool
    protection_margin_sufficient:bool
    close_buffer:float=.0


@dataclass(frozen=True)
class ScanPlan:
    round:Round
    pairs:tuple[ProtectedPair,...]
    intents:tuple[Intent,...]
    blocked_symbols:frozenset[str]
    orders_used:int
    orders_remaining:int
    reasons:tuple[str,...]


def _intent_id(snapshot:ScanSnapshot,kind:str,symbol:str="",step:str="") -> str:
    material="|".join((snapshot.account_id,snapshot.round.round_id,snapshot.scan_id,kind,symbol,step))
    return "mg-"+hashlib.sha256(material.encode()).hexdigest()[:28]


def _position(snapshot:ScanSnapshot,symbol:str,side:str)->Position|None:
    return next((x for x in snapshot.positions if x.symbol==symbol and x.side==side),None)


def plan_scan(config:Strategy2Config,snapshot:ScanSnapshot)->ScanPlan:
    """Plan at most fifteen exchange requests in strict safety order."""
    if not config.money_grabber_enabled or snapshot.round.status=="CLOSED":
        return ScanPlan(snapshot.round,snapshot.pairs,(),frozenset(),0,MAX_ORDERS_PER_SCAN,
            ("Money Grabber staat uit; bestaand Strategy-2-gedrag blijft ongewijzigd",))
    safety=all((snapshot.hedge_mode,snapshot.ownership_reliable,snapshot.exchange_reliable,
        snapshot.orders_known,snapshot.contracts_known))
    if not safety:
        return ScanPlan(snapshot.round,snapshot.pairs,(),frozenset(x.symbol for x in snapshot.pairs),0,
            MAX_ORDERS_PER_SCAN,("Verse exchange-, ownership-, order-, contract- of Hedge-Mode-data ontbreekt",))
    round_state,round_intent=observe_round_target(snapshot.round,snapshot.net_value,
        close_buffer=snapshot.close_buffer,intent_id=_intent_id(snapshot,"CLOSE_ALL_ROUND"))
    blocked=frozenset(x.symbol for x in snapshot.pairs if not normal_action_allowed(x,"DCA"))
    if round_intent is not None:
        return ScanPlan(round_state,snapshot.pairs,(round_intent,),
            frozenset(x.symbol for x in snapshot.positions),1,MAX_ORDERS_PER_SCAN-1,
            ("Rondedoel dubbel bewezen; alle normale risicoacties zijn geblokkeerd",))
    intents:list[Intent]=[];pairs=list(snapshot.pairs);reasons=[]
    by_symbol={x.symbol:x for x in pairs}
    # Priority 1: required first/full protection on free or partial symbols.
    for pos in snapshot.positions:
        if len(intents)>=MAX_ORDERS_PER_SCAN:break
        pair=by_symbol.get(pos.symbol)
        if pair is None:
            pair=ProtectedPair(snapshot.account_id,snapshot.round.round_id,pos.symbol,pos.side)
        if pos.side!=pair.original_side:continue
        intent=plan_protection(pair=pair,original_notional=pos.notional,
            weighted_entry=pos.weighted_entry,mark_price=pos.mark_price,
            first_threshold=config.money_grabber_first_threshold,
            first_ratio=config.money_grabber_first_ratio,
            full_threshold=config.money_grabber_full_threshold,
            full_ratio=config.money_grabber_full_ratio,hedge_mode=snapshot.hedge_mode,
            ownership_reliable=snapshot.ownership_reliable,exchange_reliable=snapshot.exchange_reliable,
            orders_known=snapshot.orders_known,contract_known=snapshot.contracts_known,
            margin_sufficient=snapshot.protection_margin_sufficient,
            intent_id=_intent_id(snapshot,"PROTECT",pos.symbol,str(pair.protection_notional)))
        if intent:
            intents.append(intent);by_symbol[pos.symbol]=replace(pair,status=("FULL_PROTECTION_PENDING"
                if intent.target_notional+pair.protection_notional>=pos.notional*config.money_grabber_full_ratio-1e-8
                else "PROTECTION_PENDING"),intent_id=intent.intent_id,original_notional=pos.notional)
    # Priority 3: protected pair whose combined expected result is net positive.
    for symbol,pair in list(by_symbol.items()):
        if len(intents)>=MAX_ORDERS_PER_SCAN:break
        if pair.status not in {"PARTIAL_PROTECTION","LOCKED"}:continue
        original=_position(snapshot,symbol,pair.original_side);protection=_position(snapshot,symbol,pair.protection_side)
        if not original or not protection:reasons.append(f"{symbol}: gekoppelde kant ontbreekt; recovery vereist");continue
        intent=plan_pair_close(pair=pair,original_pnl=original.unrealized_pnl,
            protection_pnl=protection.unrealized_pnl,funding=original.funding+protection.funding,
            paid_fees=original.paid_fees+protection.paid_fees,
            expected_exit_fees=original.expected_exit_fees+protection.expected_exit_fees,
            slippage_buffer=original.slippage_buffer+protection.slippage_buffer,other_costs=0,
            minimum_buffer=.01,reliable=original.reliable and protection.reliable,
            intent_id=_intent_id(snapshot,"PAIR_CLOSE",symbol))
        if intent:intents.append(intent);by_symbol[symbol]=replace(pair,status="PAIR_CLOSE_PENDING",intent_id=intent.intent_id)
    pairs=tuple(by_symbol[x] for x in sorted(by_symbol))
    blocked=frozenset(x.symbol for x in pairs if not normal_action_allowed(x,"DCA"))
    return ScanPlan(round_state,pairs,tuple(intents),blocked,len(intents),
        MAX_ORDERS_PER_SCAN-len(intents),tuple(reasons or ("Money Grabber-scan veilig gepland",)))


def shadow_report(plan:ScanPlan)->dict[str,Any]:
    return {"readOnly":True,"ordersSent":0,"maximumOrders":MAX_ORDERS_PER_SCAN,
        "wouldSendCount":plan.orders_used,"remainingBudget":plan.orders_remaining,
        "roundStatus":plan.round.status,"blockedSymbols":sorted(plan.blocked_symbols),
        "actions":[{"kind":x.kind,"intentId":x.intent_id,"symbol":x.symbol,"side":x.side,
            "targetNotional":x.target_notional} for x in plan.intents],"reasons":list(plan.reasons)}
