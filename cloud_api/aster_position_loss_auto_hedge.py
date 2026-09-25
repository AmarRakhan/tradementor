"""Auto Hedge 2.0: exact 1:1 per-symbol protection.

The engine is deliberately exchange-truth first and strategy-agnostic:
- a normal position may trigger at open P&L <= -threshold;
- once protected, the protected side remains authoritative even after P&L recovers;
- the opposite side is reconciled to exact coin quantity, including REDUCE when over-covered;
- pending OPEN/CLOSE quantities count so duplicate orders are not stacked;
- a caller-provided generation + revision makes new logical hedge events unique while
  retries of the same logical action keep the same client order id;
- shadow mode can never submit or close an order.

Lifecycle persistence (HEDGED/RECOVERY/REHEDGE_ARMED) is owned by the API extension.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import math
import time
from typing import Any, Callable, Mapping

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
EPSILON = 1e-12


@dataclass(frozen=True)
class AutoHedgeAction:
    symbol: str
    protected_side: str
    hedge_side: str
    protected_open_pnl: float
    threshold_usd: float
    protected_qty: float
    existing_hedge_qty: float
    pending_open_qty: float
    pending_close_qty: float
    effective_hedge_qty: float
    target_qty: float
    delta_qty: float
    required_delta: float
    operation: str
    status: str
    reason: str

    @property
    def trigger_side(self) -> str:
        return self.protected_side

    @property
    def trigger_open_pnl(self) -> float:
        return self.protected_open_pnl

    @property
    def losing_side_qty(self) -> float:
        return self.protected_qty

    @property
    def existing_opposite_qty(self) -> float:
        return self.existing_hedge_qty

    @property
    def pending_opposite_qty(self) -> float:
        return self.pending_open_qty

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "triggerSide": self.protected_side,
            "protectedSide": self.protected_side,
            "hedgeSide": self.hedge_side,
            "triggerOpenPnl": self.protected_open_pnl,
            "protectedOpenPnl": self.protected_open_pnl,
            "configuredThreshold": self.threshold_usd,
            "losingSideQty": self.protected_qty,
            "protectedQty": self.protected_qty,
            "existingOppositeQty": self.existing_hedge_qty,
            "hedgeQty": self.existing_hedge_qty,
            "pendingOppositeQty": self.pending_open_qty,
            "pendingOpenQty": self.pending_open_qty,
            "pendingCloseQty": self.pending_close_qty,
            "effectiveHedgeQty": self.effective_hedge_qty,
            "targetQty": self.target_qty,
            "deltaQty": self.delta_qty,
            "requiredDelta": self.required_delta,
            "operation": self.operation,
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
        raise ValueError(
            f"Auto Hedge verliesgrens moet tussen {MIN_THRESHOLD_USD} en {MAX_THRESHOLD_USD} USD liggen"
        )
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


def position_open_pnl(row: dict[str, Any] | None) -> float:
    source = row or {}
    for key in ("unRealizedProfit", "unrealizedProfit", "unrealizedPnl", "unrealizedPnL"):
        if key in source:
            return _f(source.get(key))
    side = str(source.get("positionSide", source.get("side", ""))).upper()
    qty = abs(_f(source.get("positionAmt", source.get("quantity"))))
    entry = _f(source.get("entryPrice"))
    mark = _f(source.get("markPrice"), entry)
    return (mark - entry) * qty if side == "LONG" else (entry - mark) * qty


def position_quantity(row: dict[str, Any] | None) -> float:
    source = row or {}
    return abs(_f(source.get("positionAmt", source.get("quantity"))))


def _pending_adjustments(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, float]]:
    result: dict[tuple[str, str], dict[str, float]] = {}
    terminal = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", "")).upper().strip()
        order_side = str(row.get("side", "")).upper().strip()
        status = str(row.get("status", "NEW")).upper().strip()
        if not symbol or side not in {"LONG", "SHORT"} or status in terminal:
            continue
        original = abs(_f(row.get("origQty", row.get("quantity"))))
        executed = abs(_f(row.get("executedQty", row.get("cumQty"))))
        remaining = max(0.0, original - executed)
        if remaining <= EPSILON:
            continue
        opens = (side == "LONG" and order_side == "BUY") or (side == "SHORT" and order_side == "SELL")
        closes = (side == "LONG" and order_side == "SELL") or (side == "SHORT" and order_side == "BUY")
        if not opens and not closes:
            continue
        bucket = result.setdefault((symbol, side), {"open": 0.0, "close": 0.0})
        bucket["open" if opens else "close"] += remaining
    return result


def _build_action(
    *,
    symbol: str,
    protected_side: str,
    protected_row: dict[str, Any],
    hedge_row: dict[str, Any] | None,
    threshold: float,
    pending: Mapping[tuple[str, str], Mapping[str, float]],
) -> AutoHedgeAction:
    hedge_side = "SHORT" if protected_side == "LONG" else "LONG"
    protected_qty = position_quantity(protected_row)
    hedge_qty = position_quantity(hedge_row)
    pending_row = pending.get((symbol, hedge_side), {})
    pending_open = max(0.0, _f(pending_row.get("open")))
    pending_close = max(0.0, _f(pending_row.get("close")))
    effective = max(0.0, hedge_qty + pending_open - pending_close)
    delta = protected_qty - effective
    has_pending = pending_open > EPSILON or pending_close > EPSILON
    if abs(delta) <= EPSILON:
        operation = "HOLD"
        status = "PENDING" if has_pending else "HEDGED"
        reason = "PENDING_ORDER_RECONCILES_EXACT_1_TO_1" if has_pending else "EXACT_1_TO_1"
        delta = 0.0
    elif delta > 0:
        operation = "OPEN"
        status = "NEEDS_HEDGE"
        reason = "LOSS_THRESHOLD_REACHED_OR_PROTECTION_DRIFT"
    else:
        operation = "REDUCE"
        status = "NEEDS_REDUCE"
        reason = "OVER_HEDGED_EXACT_1_TO_1_REQUIRED"
    return AutoHedgeAction(
        symbol=symbol,
        protected_side=protected_side,
        hedge_side=hedge_side,
        protected_open_pnl=position_open_pnl(protected_row),
        threshold_usd=threshold,
        protected_qty=protected_qty,
        existing_hedge_qty=hedge_qty,
        pending_open_qty=pending_open,
        pending_close_qty=pending_close,
        effective_hedge_qty=effective,
        target_qty=protected_qty,
        delta_qty=delta,
        required_delta=abs(delta),
        operation=operation,
        status=status,
        reason=reason,
    )


def evaluate_auto_hedge(
    positions: list[dict[str, Any]],
    threshold_usd: Any,
    *,
    open_orders: list[dict[str, Any]] | None = None,
    protected_sides: Mapping[str, str] | None = None,
    skip_symbols: set[str] | None = None,
) -> list[AutoHedgeAction]:
    """Return deterministic exact-quantity decisions.

    protected_sides keeps an existing protection cycle active even after its
    protected leg recovers above the loss threshold. For symbols not present in
    that mapping, the most negative threshold-qualified leg becomes the trigger.
    A symbol is evaluated at most once per reconciliation.
    """
    threshold = normalize_threshold(threshold_usd)
    pmap = _active_positions(positions)
    pending = _pending_adjustments(open_orders or [])
    protected = {str(k).upper(): str(v).upper() for k, v in (protected_sides or {}).items()}
    skipped = {str(x).upper() for x in (skip_symbols or set())}
    symbols = sorted({symbol for symbol, _ in pmap})
    actions: list[AutoHedgeAction] = []

    for symbol in symbols:
        if symbol in skipped:
            continue
        chosen_side = protected.get(symbol)
        if chosen_side in {"LONG", "SHORT"}:
            protected_row = pmap.get((symbol, chosen_side))
            if not protected_row:
                continue
        else:
            candidates: list[tuple[float, str, dict[str, Any]]] = []
            for side in ("LONG", "SHORT"):
                row = pmap.get((symbol, side))
                if not row:
                    continue
                pnl = position_open_pnl(row)
                if pnl <= -threshold:
                    candidates.append((pnl, side, row))
            if not candidates:
                continue
            candidates.sort(key=lambda item: (item[0], item[1]))
            _, chosen_side, protected_row = candidates[0]

        hedge_side = "SHORT" if chosen_side == "LONG" else "LONG"
        actions.append(_build_action(
            symbol=symbol,
            protected_side=chosen_side,
            protected_row=protected_row,
            hedge_row=pmap.get((symbol, hedge_side)),
            threshold=threshold,
            pending=pending,
        ))
    return actions


def _exchange_rule(client: Any, symbol: str) -> ContractRules:
    info = client.public_exchange_info()
    rows = info.get("symbols", []) if isinstance(info, dict) else []
    row = next(
        (item for item in rows if isinstance(item, dict) and str(item.get("symbol", "")).upper() == symbol),
        None,
    )
    if row is None:
        raise AsterValidationError(f"{symbol}: contractregels ontbreken")
    return ContractRules.from_exchange_info(row)


def _exact_market_quantity(rule: ContractRules, requested: float, mark: float, symbol: str) -> Decimal:
    value = Decimal(str(abs(requested)))
    if value <= 0:
        raise AsterValidationError(f"{symbol}: hedge-quantity moet positief zijn")
    quantity = rule.market_quantity(value, Decimal(str(mark)))
    tolerance = max(
        Decimal("1e-12"),
        rule.market_quantity_step / Decimal("1000")
        if rule.market_quantity_step > 0 else Decimal("1e-12"),
    )
    if abs(quantity - value) > tolerance:
        raise AsterValidationError(
            f"{symbol}: exact 1:1 is niet uitvoerbaar binnen de exchange step-size "
            f"(nodig {value}, uitvoerbaar {quantity})"
        )
    return quantity


def _stable_intent(
    uid: str,
    action: AutoHedgeAction,
    quantity: Decimal,
    *,
    generation_id: str,
    revision: int,
) -> str:
    raw = (
        f"{uid}|{action.symbol}|{action.protected_side}|{action.hedge_side}|"
        f"{action.operation}|{quantity}|{generation_id}|r{int(revision)}"
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:22]
    return f"plah2-{digest}"


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
    if status == "PARTIALLY_FILLED" and abs(_f(current.get("executedQty"))) > 0:
        return current
    raise RuntimeError(f"Auto Hedge order is nog niet definitief gevuld ({status or 'ONBEKEND'})")


def _query_existing(client: Any, symbol: str, intent_id: str) -> dict[str, Any] | None:
    query = getattr(client, "query_order", None)
    if not callable(query):
        return None
    try:
        row = query(symbol, intent_id)
    except Exception:
        return None
    return row if isinstance(row, dict) and row.get("orderId") is not None else None


def _insufficient_margin(exc: Exception) -> bool:
    value = str(exc).lower()
    return any(marker in value for marker in (
        "insufficient margin", "margin is insufficient", "insufficient balance",
        "-2019", "-2027", "-5018",
    ))


def reconcile_auto_hedge(
    *,
    client: Any,
    uid: str,
    threshold_usd: Any,
    execute: bool,
    audit: Callable[[dict[str, Any]], None] | None = None,
    order_budget: int = 15,
    protected_sides: Mapping[str, str] | None = None,
    skip_symbols: set[str] | None = None,
    intent_context: Mapping[str, Mapping[str, Any]] | None = None,
    positions: list[dict[str, Any]] | None = None,
    open_orders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reconcile exchange legs and optionally submit exact OPEN/REDUCE deltas."""
    threshold = normalize_threshold(threshold_usd)
    positions = list(client.position_risk() or []) if positions is None else list(positions)
    open_orders = list(client.open_orders() or []) if open_orders is None else list(open_orders)
    actions = evaluate_auto_hedge(
        positions, threshold, open_orders=open_orders,
        protected_sides=protected_sides, skip_symbols=skip_symbols,
    )
    public_actions: list[dict[str, Any]] = []
    orders_sent = 0

    if not execute:
        return {
            "thresholdUsd": threshold,
            "mode": "SHADOW",
            "ordersSent": 0,
            "actions": [item.public_dict() for item in actions],
        }

    if not bool(client.position_mode()):
        return {
            "thresholdUsd": threshold,
            "mode": "LIVE",
            "ordersSent": 0,
            "status": "FAILED",
            "reason": "HEDGE_MODE_NOT_CONFIRMED",
            "actions": [item.public_dict() for item in actions],
        }

    contexts = intent_context or {}
    for action in actions:
        row = action.public_dict()
        if action.required_delta <= EPSILON or orders_sent >= max(0, int(order_budget)):
            public_actions.append(row)
            continue

        pmap = _active_positions(positions)
        protected_row = pmap.get((action.symbol, action.protected_side), {})
        hedge_row = pmap.get((action.symbol, action.hedge_side), {})
        mark = _f(
            protected_row.get("markPrice"),
            _f(hedge_row.get("markPrice"), _f(protected_row.get("entryPrice"), _f(hedge_row.get("entryPrice")))),
        )
        if mark <= 0:
            row.update({"status": "FAILED", "reason": "MARK_PRICE_UNAVAILABLE"})
            public_actions.append(row)
            continue

        try:
            rule = _exchange_rule(client, action.symbol)
            quantity = _exact_market_quantity(rule, action.required_delta, mark, action.symbol)
        except Exception as exc:
            row.update({
                "requestedQty": action.required_delta,
                "filledQty": 0.0,
                "status": "PRECISION_BLOCKED",
                "reason": str(exc)[:500],
            })
            if audit:
                audit({**row, "result": "PRECISION_BLOCKED"})
            public_actions.append(row)
            continue

        if action.operation == "OPEN":
            leverage = max(1, int(_f(protected_row.get("leverage"), _f(hedge_row.get("leverage"), 1))))
            available = _f((client.account_information() or {}).get("availableBalance"))
            required_margin = (float(quantity) * mark / leverage) if mark > 0 else 0.0
            if required_margin > 0 and available + 1e-9 < required_margin:
                row.update({
                    "requestedQty": float(quantity),
                    "filledQty": 0.0,
                    "status": "INSUFFICIENT_MARGIN",
                    "reason": "AVAILABLE_BALANCE_BELOW_ESTIMATED_MARGIN",
                })
                public_actions.append(row)
                if audit:
                    audit({**row, "result": "INSUFFICIENT_MARGIN"})
                continue

        context = contexts.get(action.symbol, {})
        generation_id = str(context.get("generationId") or "g0")
        revision = max(0, int(_f(context.get("revision"), 0)))
        intent_id = _stable_intent(
            uid, action, quantity, generation_id=generation_id, revision=revision,
        )
        intent = AsterOrderIntent(
            intent_id=intent_id,
            symbol=action.symbol,
            position_side=PositionSide(action.hedge_side),
            quantity=quantity,
            action="OPEN" if action.operation == "OPEN" else "CLOSE",
        )

        try:
            existing = _query_existing(client, action.symbol, intent_id)
            recovered = existing is not None
            submitted_now = False
            if existing is not None:
                result = existing
            else:
                result, recovered_from_uncertain = client.submit_order_once(
                    intent,
                    config=AsterAutomationConfig(enabled=True, mode="live"),
                    confirm=True,
                    hedge_mode_confirmed=True,
                    risk_approved=True,
                )
                recovered = bool(recovered_from_uncertain)
                submitted_now = True
            confirmed = _confirmed_fill(client, action.symbol, intent_id, result)
            if submitted_now:
                orders_sent += 1
            filled = abs(_f(confirmed.get("executedQty", confirmed.get("origQty", quantity))))
            row.update({
                "requestedQty": float(quantity),
                "filledQty": filled,
                "exchangeOrderId": confirmed.get("orderId"),
                "clientOrderId": intent_id,
                "generationId": generation_id,
                "revision": revision,
                "recovered": recovered,
                "submittedNow": submitted_now,
                "status": "HEDGED" if filled + EPSILON >= float(quantity) else "PARTIAL",
                "reason": "RECOVERED_EXISTING_INTENT" if recovered and not submitted_now else "SUBMITTED_CONFIRMED",
            })
            if audit:
                audit({**row, "result": row["status"]})
        except Exception as exc:
            row.update({
                "requestedQty": float(quantity),
                "filledQty": 0.0,
                "clientOrderId": intent_id,
                "generationId": generation_id,
                "revision": revision,
                "status": "INSUFFICIENT_MARGIN" if _insufficient_margin(exc) else "FAILED",
                "reason": str(exc)[:500],
            })
            if audit:
                audit({**row, "result": row["status"]})
        public_actions.append(row)

        if row.get("exchangeOrderId") is not None:
            positions = list(client.position_risk() or [])
            open_orders = list(client.open_orders() or [])

    final_actions = evaluate_auto_hedge(
        positions, threshold, open_orders=open_orders,
        protected_sides=protected_sides, skip_symbols=skip_symbols,
    )
    return {
        "thresholdUsd": threshold,
        "mode": "LIVE",
        "ordersSent": orders_sent,
        "actions": public_actions,
        "final": [item.public_dict() for item in final_actions],
    }
