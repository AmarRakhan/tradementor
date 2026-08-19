"""Aster execution adapter for already validated Money Grabber intents."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from aster_execution import PairExecutionPlan, execute_close_all, execute_leg_once
from aster_gateway import AsterAutomationConfig, AsterOrderIntent, PositionSide
from money_grabber import Intent, ProtectedPair


def _confirmed(result: dict[str, Any]) -> bool:
    return str(result.get("status", "")).upper() == "FILLED" and float(
        result.get("executedQty", result.get("origQty", 0)) or 0) > 0


def execute_protection(client: Any, *, intent: Intent, pair: ProtectedPair,
                       quantity: Decimal, hedge_mode_confirmed: bool,
                       ownership_reconciled: bool, orders_known: bool,
                       margin_sufficient: bool,
                       before_submit: Callable[[AsterOrderIntent], None] | None = None) -> dict[str, Any]:
    """Open only the same-symbol opposite leg; never use this for a normal entry."""
    if intent.kind != "PAIR_PROTECTION_RISK_REDUCING": raise ValueError("Geen protection-intentie")
    if intent.account_id != pair.account_id or intent.round_id != pair.round_id \
            or intent.symbol != pair.symbol or intent.side != pair.protection_side:
        raise ValueError("Protection-ownership, symbool of richting klopt niet")
    if not all((hedge_mode_confirmed, ownership_reconciled, orders_known, margin_sufficient)):
        raise ValueError("Protection-order fail-closed: veiligheidsbewijs is onvolledig")
    order = AsterOrderIntent(intent.intent_id, pair.symbol, PositionSide(intent.side), quantity, "OPEN")
    if before_submit: before_submit(order)
    result, recovered = client.submit_order_once(order,
        config=AsterAutomationConfig(enabled=True, mode="live"), confirm=True,
        hedge_mode_confirmed=True, risk_approved=True)
    if not _confirmed(result): raise RuntimeError("Protection-fill is niet definitief door Aster bevestigd")
    return {"side":intent.side,"action":"OPEN_PROTECTION","result":result,"recovered":recovered}


def execute_pair_close(client: Any, *, intent: Intent, pair: ProtectedPair,
                       original_plan: PairExecutionPlan, protection_plan: PairExecutionPlan,
                       exchange_reconciled: bool) -> list[dict[str, Any]]:
    if intent.kind != "CLOSE_PROTECTED_PAIR" or not intent.reduce_only:
        raise ValueError("Geen gevalideerde gezamenlijke paarsluiting")
    if intent.account_id != pair.account_id or intent.round_id != pair.round_id or intent.symbol != pair.symbol:
        raise ValueError("Paarsluiting hoort niet bij dit account, deze ronde en dit symbool")
    if not exchange_reconciled: raise ValueError("Paarsluiting vereist verse exchange-reconciliatie")
    # `explicit_loss_confirmation` authorizes the execution primitive to bypass
    # the individual-profit guard. The Money Grabber domain has already proven
    # the pair as one positive net unit. Aster Hedge Mode deliberately receives
    # no reduceOnly field: CLOSE + positionSide is the exchange contract.
    return execute_close_all(client, [
        (original_plan, PositionSide(pair.original_side)),
        (protection_plan, PositionSide(pair.protection_side)),
    ], id_prefix=intent.intent_id, confirm=True, explicit_loss_confirmation=True)


def execute_round_close(client: Any, *, intent: Intent,
                        plans: list[tuple[PairExecutionPlan, PositionSide]],
                        exchange_reconciled: bool, orders_cancelled: bool) -> list[dict[str, Any]]:
    if intent.kind != "CLOSE_ALL_ROUND" or not intent.reduce_only:
        raise ValueError("Geen gevalideerde rondeafsluiting")
    if not exchange_reconciled or not orders_cancelled:
        raise ValueError("Rondeafsluiting vereist reconciliatie en bevestigde orderannulering")
    return execute_close_all(client, plans, id_prefix=intent.intent_id, confirm=True,
                             explicit_loss_confirmation=True)
