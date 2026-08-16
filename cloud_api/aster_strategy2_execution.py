"""Execution adapter for Strategy-2 decisions.

The adapter is deliberately thin: it consumes decisions from the same pure
engine used by paper tests and delegates idempotency/fill confirmation to the
shared Aster execution layer.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any,Callable
import hashlib
from aster_gateway import PositionSide
from aster_execution import PairExecutionPlan,execute_pair_once,execute_leg_once
from aster_close_guard import CloseEvidence
from aster_strategy2 import Decision
from aster_strategy2_state import OwnedLeg

@dataclass(frozen=True)
class ExecutionContext:
    strategy_id:str;cycle_id:str;config_version:int;ownership:OwnedLeg|None;exchange_reconciled:bool;confirm:bool
    account_uid:str="";close_fee_rate:float=.0005;slippage_rate:float=.001
    audit:Callable[[dict[str,Any]],None]|None=None

def execute_decision(client:Any,decision:Decision,plan:PairExecutionPlan,context:ExecutionContext,*,risk_approved:Callable[[float],bool])->list[dict]:
    if not context.confirm:raise ValueError("Persoonlijke bevestiging ontbreekt")
    if not context.exchange_reconciled:raise RuntimeError("Exchange-reconciliation is niet voltooid")
    if decision.kind not in {"OPEN_PAIR","ADD_DCA","FULL_TP","PARTIAL_TP","PROTECTION_INCREASE","EMERGENCY_REDUCE","CLOSE_PROTECTION"}:return []
    prefix=f"s2-{context.strategy_id}-{context.cycle_id}-v{context.config_version}"
    if len(prefix)>22: prefix=f"s2-{hashlib.sha256(prefix.encode()).hexdigest()[:10]}-v{context.config_version}"
    if decision.kind=="OPEN_PAIR":
        return execute_pair_once(client,plan,id_prefix=prefix,confirm=True,risk_approved=risk_approved)
    if context.ownership is None or context.ownership.strategy_id!=context.strategy_id or context.ownership.cycle_id!=context.cycle_id:
        raise RuntimeError("Strategy-2-ownership is niet bewezen; risicoverhogende of sluitactie geblokkeerd")
    side=PositionSide(decision.side)
    if decision.kind in {"ADD_DCA","PROTECTION_INCREASE"}:
        if not risk_approved(float(plan.notional_per_leg)/max(1,plan.leverage)):raise ValueError("Portfolio Risk Engine blokkeert deze order")
        return [execute_leg_once(client,plan,side=side,action="OPEN",id_prefix=prefix,confirm=True)]
    close_notional=decision.notional
    if close_notional<=0:raise ValueError("Sluitbedrag ontbreekt")
    ratio=min(1.0,close_notional/max(context.ownership.quantity*float(plan.notional_per_leg/max(plan.quantity,Decimal('0.00000001'))),.00000001))
    close_plan=PairExecutionPlan(plan.symbol,max(Decimal("0"),plan.quantity*Decimal(str(ratio))),Decimal(str(close_notional)),plan.leverage)
    mark=float(plan.notional_per_leg/max(plan.quantity,Decimal("0.00000001")))
    gross=((mark-context.ownership.weighted_entry) if decision.side=="LONG" else
           (context.ownership.weighted_entry-mark))*float(close_plan.quantity)
    evidence=CloseEvidence(
        account_uid=context.account_uid,symbol=plan.symbol,side=decision.side,
        caller=f"strategy2:{decision.kind}",reason=decision.reason,quantity=float(close_plan.quantity),
        entry_price=context.ownership.weighted_entry,mark_price=mark,gross_pnl=gross,
        entry_fees=context.ownership.fees*ratio,close_fee=close_notional*context.close_fee_rate,
        funding=context.ownership.funding*ratio,slippage_buffer=close_notional*context.slippage_rate,
        ownership_reliable=True,fills_reliable=bool(context.ownership.fill_ids),prices_reliable=mark>0,
        costs_reliable=context.ownership.costs_updated_at_ms>0,
    )
    return [execute_leg_once(client,close_plan,side=side,action="CLOSE",id_prefix=prefix,confirm=True,
        close_evidence=evidence,close_audit=context.audit)]
