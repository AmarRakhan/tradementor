"""Strict live execution boundary for Strategy 3.

The pure Strategy-3 engine is also used by paper simulation.  This module is
the only translation layer allowed to turn an engine decision into an Aster
intent.  It reuses the shared idempotent, fill-confirming Aster executor while
keeping Strategy-3 ownership and client-order ids separate from Strategy 2.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
from typing import Any, Callable

from aster_execution import PairExecutionPlan, execute_leg_once
from aster_gateway import PositionSide
from aster_strategy2_state import OwnedLeg
from aster_strategy3 import Decision


STRATEGY3_ID = "aster-strategy-3"


@dataclass(frozen=True)
class Strategy3ExecutionContext:
    cycle_id: str
    config_version: int
    ownership: OwnedLeg | None
    exchange_reconciled: bool
    confirm: bool
    live_gate_open: bool
    strategy_id: str = STRATEGY3_ID


def _prefix(context: Strategy3ExecutionContext, decision: Decision) -> str:
    raw = f"s3-{context.strategy_id}-{context.cycle_id}-v{context.config_version}-{decision.kind.lower()}"
    return raw if len(raw) <= 22 else f"s3-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def _require_owned(context: Strategy3ExecutionContext, plan: PairExecutionPlan, side: str) -> OwnedLeg:
    leg = context.ownership
    if (
        leg is None
        or leg.strategy_id != STRATEGY3_ID
        or leg.engine_type != "strategy3"
        or leg.cycle_id != context.cycle_id
        or leg.symbol != plan.symbol
        or leg.side != side
    ):
        raise RuntimeError("Strategy-3-ownership is niet exact bewezen; order geblokkeerd")
    return leg


def execute_strategy3_decision(
    client: Any,
    decision: Decision,
    plan: PairExecutionPlan,
    context: Strategy3ExecutionContext,
    *,
    risk_approved: Callable[[float], bool],
) -> list[dict[str, Any]]:
    """Execute one already-approved decision, never a scheduler policy.

    UNKNOWN/time-out handling remains inside ``submit_order_once`` and the
    shared fill confirmer.  This function never retries an order.
    """
    if not context.confirm:
        raise ValueError("Persoonlijke bevestiging voor Strategy 3 ontbreekt")
    if not context.live_gate_open:
        raise RuntimeError("Strategy 3 live-gate staat centraal dicht")
    if not context.exchange_reconciled:
        raise RuntimeError("Exchange-reconciliation is niet voltooid")
    if context.strategy_id != STRATEGY3_ID:
        raise RuntimeError("Ongeldige Strategy-3-identiteit")
    if decision.kind in {"HOLD", "ARM_TRAILING", "ASSIGN_PROTECTION"}:
        return []
    if decision.kind not in {"OPEN_BASE", "ADD_DCA", "FULL_TP", "TRAILING_TP", "PARTIAL_TP"}:
        raise RuntimeError(f"Niet-vrijgegeven Strategy-3-beslissing: {decision.kind}")

    side = PositionSide(decision.side)
    prefix = _prefix(context, decision)
    if decision.kind == "OPEN_BASE":
        required = float(plan.notional_per_leg) / max(1, plan.leverage)
        if not risk_approved(required):
            raise ValueError("Portfolio Risk Engine blokkeert de basisorder")
        return [execute_leg_once(client, plan, side=side, action="OPEN", id_prefix=prefix, confirm=True)]

    owned = _require_owned(context, plan, decision.side)
    if decision.kind == "ADD_DCA":
        required = float(plan.notional_per_leg) / max(1, plan.leverage)
        if not risk_approved(required):
            raise ValueError("Portfolio Risk Engine blokkeert de DCA-order")
        return [execute_leg_once(client, plan, side=side, action="OPEN", id_prefix=prefix, confirm=True)]

    if decision.notional <= 0:
        raise ValueError("Sluitbedrag ontbreekt")
    unit_price = float(plan.notional_per_leg / max(plan.quantity, Decimal("0.00000001")))
    owned_notional = max(owned.quantity * unit_price, 0.00000001)
    ratio = min(1.0, decision.notional / owned_notional)
    close_plan = PairExecutionPlan(
        plan.symbol,
        max(Decimal("0"), plan.quantity * Decimal(str(ratio))),
        Decimal(str(decision.notional)),
        plan.leverage,
    )
    return [execute_leg_once(client, close_plan, side=side, action="CLOSE", id_prefix=prefix, confirm=True)]
