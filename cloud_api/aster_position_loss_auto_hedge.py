"""Per-position dollar-loss Auto Hedge.

Business rule:
- evaluate every current Aster Hedge Mode leg independently;
- when one leg has open P&L <= -threshold, top up the opposite leg to the
  same exchange quantity;
- existing and pending opposite quantity counts;
- never stack beyond 1:1 and never close/unhedge here.

This module deliberately does not import any of the legacy portfolio/drawdown
hedge engines. Exchange connectivity is injected by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import math
import time
from typing import Any, Callable

from aster_gateway import (
    AsterAutomationConfig,
    AsterOrderIntent,
    AsterValidationError,
    ContractRules,
    PositionSide,
)


DEFAULT_THRESHOLD_USD = 10.0
MIN_THRESHOLD_USD = 0.01
MAX_THRESHOLD_USD = 100_000.0


@dataclass(frozen=True)
class AutoHedgeAction:
    symbol: str
    trigger_side: str
    hedge_side: str
    trigger_open_pnl: float
    threshold_usd: float
    losing_side_qty: float
    existing_opposite_qty: float
    pending_opposite_qty: float
    required_delta: float
    status: str
    reason: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "triggerSide": self.trigger_side,
            "hedgeSide": self.hedge_side,
            "triggerOpenPnl": self.trigger_open_pnl,
            "configuredThreshold": self.threshold_usd,
            "losingSideQty": self.losing_side_qty,
            "existingOppositeQty": self.existing_opposite_qty,
            "pendingOppositeQty": self.pending_opposite_qty,
            "requiredDelta": self.required_delta,
            "status": self.status,
            "reason": self.reason,
        }


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def normalize_threshold(value: Any) -> float:
    threshold = _f(value, -1.0)
    if threshold < MIN_THRESHOLD_USD or threshold > MAX_THRESHOLD_USD:
        raise ValueError(f"Auto Hedge verliesgrens moet tussen {MIN_THRESHOLD_USD} en {MAX_THRESHOLD_USD} USD liggen")
    return threshold


def _active_positions(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", row.get("side", ""))).upper().strip()
        qty = abs(_f(row.get("positionAmt", row.get("quantity"))))
        if symbol and side in {"LONG", "SHORT"} and qty > 0:
            result[(symbol, side)] = row
    return result


def _open_pnl(row: dict[str, Any]) -> float:
    for key in ("unRealizedProfit", "unrealizedProfit", "unrealizedPnl", "unrealizedPnL"):
        if key in row:
            return _f(row.get(key))
    side = str(row.get("positionSide", row.get("side", ""))).upper()
    qty = abs(_f(row.get("positionAmt", row.get("quantity"))))
    entry = _f(row.get("entryPrice"))
    mark = _f(row.get("markPrice"), entry)
    return (mark - entry) * qty if side == "LONG" else (entry - mark) * qty


def _pending_open_quantities(rows: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    result: dict[tuple[str, str], float] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", "")).upper().strip()
        order_side = str(row.get("side", "")).upper().strip()
        status = str(row.get("status", "NEW")).upper().strip()
        if not symbol or side not in {"LONG", "SHORT"} or status in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}:
            continue
        is_open = (side == "LONG" and order_side == "BUY") or (side == "SHORT" and order_side == "SELL")
        if not is_open:
            continue
        original = abs(_f(row.get("origQty", row.get("quantity"))))
        executed = abs(_f(row.get("executedQty", row.get("cumQty"))))
        remaining = max(0.0, original - executed)
        if remaining > 0:
            result[(symbol, side)] = result.get((symbol, side), 0.0) + remaining
    return result


def evaluate_auto_hedge(
    positions: list[dict[str, Any]],
    threshold_usd: Any,
    *,
    open_orders: list[dict[str, Any]] | None = None,
) -> list[AutoHedgeAction]:
    """Return deterministic exchange-truth reconciliation decisions.

    A position already below the threshold when the feature is enabled is due
    immediately; no threshold-crossing event is required.
    """
    threshold = normalize_threshold(threshold_usd)
    pmap = _active_positions(positions)
    pending = _pending_open_quantities(open_orders or [])
    actions: list[AutoHedgeAction] = []

    for (symbol, side), row in sorted(pmap.items()):
        pnl = _open_pnl(row)
        if pnl > -threshold:
            continue
        hedge_side = "SHORT" if side == "LONG" else "LONG"
        losing_qty = abs(_f(row.get("positionAmt", row.get("quantity"))))
        opposite = pmap.get((symbol, hedge_side), {})
        opposite_qty = abs(_f(opposite.get("positionAmt", opposite.get("quantity"))))
        pending_qty = pending.get((symbol, hedge_side), 0.0)
        missing_before_pending = max(0.0, losing_qty - opposite_qty)
        required = max(0.0, missing_before_pending - pending_qty)
        if missing_before_pending <= 1e-12:
            status, reason = "HEDGED", "OPPOSITE_QUANTITY_ALREADY_1_TO_1"
        elif required <= 1e-12:
            status, reason = "PENDING", "PENDING_OPEN_ORDER_COVERS_DELTA"
        else:
            status, reason = "NEEDS_HEDGE", "LOSS_THRESHOLD_REACHED"
        actions.append(AutoHedgeAction(
            symbol=symbol,
            trigger_side=side,
            hedge_side=hedge_side,
            trigger_open_pnl=pnl,
            threshold_usd=threshold,
            losing_side_qty=losing_qty,
            existing_opposite_qty=opposite_qty,
            pending_opposite_qty=pending_qty,
            required_delta=required,
            status=status,
            reason=reason,
        ))
    return actions


def _exchange_rule(client: Any, symbol: str) -> ContractRules:
    info = client.public_exchange_info()
    rows = info.get("symbols", []) if isinstance(info, dict) else []
    row = next((item for item in rows if isinstance(item, dict) and str(item.get("symbol", "")).upper() == symbol), None)
    if row is None:
        raise AsterValidationError(f"{symbol}: contractregels ontbreken")
    return ContractRules.from_exchange_info(row)


def _stable_intent(uid: str, action: AutoHedgeAction, quantity: Decimal) -> str:
    raw = f"{uid}|{action.symbol}|{action.trigger_side}|{action.hedge_side}|{quantity}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:18]
    return f"plah-{digest}"


def _confirmed_fill(client: Any, symbol: str, intent_id: str, result: dict[str, Any]) -> dict[str, Any]:
    current = result if isinstance(result, dict) else {}
    status = str(current.get("status", "")).upper()
    if status == "FILLED":
        return current
    terminal = {"CANCELED", "REJECTED", "EXPIRED"}
    if status in terminal:
        raise RuntimeError(f"Aster Auto Hedge order eindigde als {status}")
    query = getattr(client, "query_order", None)
    if not callable(query):
        if current.get("orderId") is not None and not status:
            return current
        raise RuntimeError("Auto Hedge fill kan niet worden bevestigd")
    for attempt in range(3):
        current = query(symbol, intent_id)
        status = str(current.get("status", "")).upper()
        if status == "FILLED":
            return current
        if status in terminal:
            raise RuntimeError(f"Aster Auto Hedge order eindigde als {status}")
        if attempt < 2:
            time.sleep(0.15)
    raise RuntimeError(f"Auto Hedge order is nog niet definitief gevuld ({status or 'ONBEKEND'})")


def _insufficient_margin(exc: Exception) -> bool:
    value = str(exc).lower()
    return any(marker in value for marker in (
        "insufficient margin", "margin is insufficient", "insufficient balance", "-2019", "-2027", "-5018",
    ))


def reconcile_auto_hedge(
    *,
    client: Any,
    uid: str,
    threshold_usd: Any,
    execute: bool,
    audit: Callable[[dict[str, Any]], None] | None = None,
    order_budget: int = 15,
) -> dict[str, Any]:
    """Reconcile current exchange legs and optionally submit only missing deltas.

    Live submission is still subject to AsterV3Client.live_authorized and the
    caller's global execution gate. This function never closes either side.
    """
    threshold = normalize_threshold(threshold_usd)
    positions = list(client.position_risk() or [])
    open_orders = list(client.open_orders() or [])
    actions = evaluate_auto_hedge(positions, threshold, open_orders=open_orders)
    public_actions: list[dict[str, Any]] = []
    orders_sent = 0

    if not execute:
        return {
            "thresholdUsd": threshold,
            "mode": "SHADOW",
            "ordersSent": 0,
            "actions": [item.public_dict() for item in actions],
        }

    hedge_mode = bool(client.position_mode())
    if not hedge_mode:
        return {
            "thresholdUsd": threshold,
            "mode": "LIVE",
            "ordersSent": 0,
            "status": "FAILED",
            "reason": "HEDGE_MODE_NOT_CONFIRMED",
            "actions": [item.public_dict() for item in actions],
        }

    for action in actions:
        row = action.public_dict()
        if action.required_delta <= 1e-12 or orders_sent >= max(0, int(order_budget)):
            public_actions.append(row)
            continue

        trigger_row = _active_positions(positions).get((action.symbol, action.trigger_side), {})
        mark = _f(trigger_row.get("markPrice"), _f(trigger_row.get("entryPrice")))
        leverage = max(1, int(_f(trigger_row.get("leverage"), 1)))
        available = _f((client.account_information() or {}).get("availableBalance"))
        required_margin = (action.required_delta * mark / leverage) if mark > 0 else 0.0
        if required_margin > 0 and available + 1e-9 < required_margin:
            row.update({"status": "INSUFFICIENT_MARGIN", "reason": "AVAILABLE_BALANCE_BELOW_ESTIMATED_MARGIN"})
            public_actions.append(row)
            if audit:
                audit({**row, "requestedQty": 0.0, "filledQty": 0.0, "result": "INSUFFICIENT_MARGIN"})
            continue

        try:
            rule = _exchange_rule(client, action.symbol)
            requested = Decimal(str(action.required_delta))
            quantity = rule.market_quantity(requested, Decimal(str(mark)))
            tolerance = max(Decimal("1e-12"), rule.market_quantity_step / Decimal("1000") if rule.market_quantity_step > 0 else Decimal("1e-12"))
            if abs(quantity - requested) > tolerance:
                raise AsterValidationError(f"{action.symbol}: ontbrekende hedge-quantity past niet exact op exchange step-size")
            intent_id = _stable_intent(uid, action, quantity)
            intent = AsterOrderIntent(
                intent_id=intent_id,
                symbol=action.symbol,
                position_side=PositionSide(action.hedge_side),
                quantity=quantity,
                action="OPEN",
            )
            result, recovered = client.submit_order_once(
                intent,
                config=AsterAutomationConfig(enabled=True, mode="live"),
                confirm=True,
                hedge_mode_confirmed=True,
                risk_approved=True,
            )
            confirmed = _confirmed_fill(client, action.symbol, intent_id, result)
            orders_sent += 1
            filled = abs(_f(confirmed.get("executedQty", confirmed.get("origQty", quantity))))
            row.update({
                "requestedQty": float(quantity),
                "filledQty": filled,
                "exchangeOrderId": confirmed.get("orderId"),
                "clientOrderId": intent_id,
                "recovered": recovered,
                "status": "HEDGED" if filled + 1e-12 >= float(quantity) else "PARTIAL",
                "reason": "SUBMITTED_CONFIRMED",
            })
            if audit:
                audit({**row, "result": row["status"]})
        except Exception as exc:
            row.update({
                "requestedQty": action.required_delta,
                "filledQty": 0.0,
                "status": "INSUFFICIENT_MARGIN" if _insufficient_margin(exc) else "FAILED",
                "reason": str(exc)[:500],
            })
            if audit:
                audit({**row, "result": row["status"]})
        public_actions.append(row)

        # Exchange truth wins after each submission. This prevents stale local
        # quantities from causing a second same-symbol top-up.
        if orders_sent:
            positions = list(client.position_risk() or [])
            open_orders = list(client.open_orders() or [])

    final_actions = evaluate_auto_hedge(positions, threshold, open_orders=open_orders)
    return {
        "thresholdUsd": threshold,
        "mode": "LIVE",
        "ordersSent": orders_sent,
        "actions": public_actions,
        "final": [item.public_dict() for item in final_actions],
    }
