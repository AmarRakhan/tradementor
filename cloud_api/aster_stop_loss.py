from __future__ import annotations

"""Server-side Stoploss gate for Multi BB.

The gate runs before Portfolio TP, Profit Lock, Smart Rescue, ordinary TP and
DCA.  It is intentionally inert unless the user explicitly enables Stoploss.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
import hashlib
import math

from aster_execution import PairExecutionPlan, execute_leg_once
from aster_gateway import PositionSide


@dataclass(frozen=True)
class StopLossGateResult:
    handled: bool
    report: dict[str, Any]
    raw_state: dict[str, Any]
    account: dict[str, Any]
    positions: list[dict[str, Any]]
    open_orders: list[dict[str, Any]]
    orders_sent: int = 0


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _position_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", row.get("side", ""))).upper().strip()
        qty = abs(_f(row.get("positionAmt", row.get("quantity"))))
        if symbol and side in {"LONG", "SHORT"} and qty > 0:
            result[f"{symbol}|{side}"] = row
    return result


def _position_pnl(row: dict[str, Any], *, side: str, entry: float, mark: float, qty: float) -> float:
    for key in ("unRealizedProfit", "unrealizedProfit", "unrealizedPnl", "unrealizedPnL"):
        if key in row:
            raw = row.get(key)
            try:
                value = float(raw)
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(value):
                return value
    return (mark - entry) * qty if side == "LONG" else (entry - mark) * qty


def _loss_percent(*, side: str, entry: float, mark: float) -> float:
    if entry <= 0:
        return 0.0
    # Keep the exact same unleveraged price-return basis used by per-trade TP:
    # LONG compares mark/entry downward; SHORT compares mark/entry upward.
    return max(0.0, ((entry - mark) / entry if side == "LONG" else (mark - entry) / entry) * 100.0)


def _close_plan(row: dict[str, Any]) -> PairExecutionPlan:
    qty = abs(_f(row.get("positionAmt", row.get("quantity"))))
    mark = _f(row.get("markPrice"), _f(row.get("entryPrice")))
    leverage = max(1, _i(row.get("leverage"), 1))
    return PairExecutionPlan(str(row.get("symbol", "")).upper(), Decimal(str(qty)),
                             Decimal(str(qty * mark)), leverage)


def _before(before_order: Any, intent: Any, metadata: dict[str, Any]) -> None:
    if before_order is None:
        return
    try:
        before_order(intent, metadata)
    except TypeError:
        before_order(intent)


def _audit(ref: Any, payload: dict[str, Any]) -> None:
    ref.collection("audit").add({**payload, "timestamp": datetime.now(timezone.utc)})


def _dependent_cycle_keys(*, key: str, state: dict[str, Any], settings: Any,
                          pmap: dict[str, dict[str, Any]]) -> list[str]:
    """Return safe close order for one Stoploss trigger.

    Normal LONG/SHORT seats stay independent. Profit Lock and the legacy
    asymmetric hedge are one coupled cycle, so their SHORT is closed before
    LONG to avoid leaving a naked hedge.
    """
    symbol, side = key.split("|", 1)
    if bool(getattr(settings, "profit_lock_ladder_enabled", False)):
        short_key = f"{symbol}|SHORT"; long_key = f"{symbol}|LONG"
        result = []
        if short_key in pmap and isinstance(state.get(short_key), dict) and state[short_key].get("profitLockHedge"):
            result.append(short_key)
        if long_key in pmap:
            result.append(long_key)
        return result or [key]
    st = state.get(key) if isinstance(state.get(key), dict) else {}
    asymmetric = bool(st.get("asymmetricHedge"))
    if not asymmetric:
        counterpart = state.get(f"{symbol}|{'SHORT' if side == 'LONG' else 'LONG'}")
        asymmetric = isinstance(counterpart, dict) and bool(counterpart.get("asymmetricHedge"))
    if asymmetric:
        short_key = f"{symbol}|SHORT"; long_key = f"{symbol}|LONG"
        return [candidate for candidate in (short_key, long_key) if candidate in pmap]
    return [key]


def run_stop_loss_gate(*, client: Any, ref: Any, raw_state: dict[str, Any], settings: Any,
                       uid: str, account: dict[str, Any], positions: list[dict[str, Any]],
                       open_orders: list[dict[str, Any]], timestamp_ms: int,
                       dry_run: bool = False, order_budget: int | None = None,
                       before_order: Any = None) -> StopLossGateResult:
    """Evaluate explicitly configured loss exits before all other strategy actions."""
    state = dict(raw_state.get("multiBbPositions") or {})
    if not bool(getattr(settings, "stop_loss_enabled", False)):
        return StopLossGateResult(False, {"enabled": False, "actions": []}, raw_state,
                                  account, positions, open_orders, 0)

    mode = str(getattr(settings, "stop_loss_mode", "PERCENT")).upper()
    long_limit = _f(getattr(settings, "stop_loss_long", 0.0))
    short_limit = _f(getattr(settings, "stop_loss_short", 0.0))
    pmap = _position_map(positions)
    order_keys = {(str(row.get("symbol", "")).upper(), str(row.get("positionSide", "")).upper())
                  for row in open_orders or []}
    budget = max(0, 15 if order_budget is None else int(order_budget))
    actions: list[dict[str, Any]] = []
    triggered: list[dict[str, Any]] = []

    for key, st in list(state.items()):
        row = pmap.get(key)
        if row is None or not isinstance(st, dict):
            continue
        symbol, side = key.split("|", 1)
        if side not in {"LONG", "SHORT"}:
            continue
        entry = _f(row.get("entryPrice")); mark = _f(row.get("markPrice"), entry)
        qty = abs(_f(row.get("positionAmt")))
        if entry <= 0 or mark <= 0 or qty <= 0:
            continue
        pnl = _position_pnl(row, side=side, entry=entry, mark=mark, qty=qty)
        loss_usd = max(0.0, -pnl)
        loss_pct = _loss_percent(side=side, entry=entry, mark=mark)
        limit = long_limit if side == "LONG" else short_limit
        due = limit > 0 and (loss_usd >= limit if mode == "USD" else loss_pct >= limit)
        if not due:
            continue
        trigger = {"kind": "STOP_LOSS_TRIGGERED", "symbol": symbol, "side": side,
                   "mode": mode, "limit": limit, "pnlUsd": pnl,
                   "lossUsd": loss_usd, "lossPercent": loss_pct, "quantity": qty}
        actions.append(trigger); triggered.append({**trigger, "key": key})

    if not triggered:
        return StopLossGateResult(False, {"enabled": True, "mode": mode, "actions": []},
                                  raw_state, account, positions, open_orders, 0)

    if dry_run:
        for trigger in triggered:
            close_keys = _dependent_cycle_keys(key=trigger["key"], state=state, settings=settings, pmap=pmap)
            actions.append({"kind": "STOP_LOSS_WOULD_CLOSE", "symbol": trigger["symbol"],
                            "triggerSide": trigger["side"], "legs": close_keys})
        report = {"enabled": True, "mode": mode, "status": "SIMULATED",
                  "ordersSent": 0, "actions": actions[-100:]}
        return StopLossGateResult(True, report, raw_state, account, positions, open_orders, 0)

    sent = 0
    processed: set[str] = set()
    for trigger in triggered:
        if sent >= budget:
            actions.append({"kind": "STOP_LOSS_WAIT", "symbol": trigger["symbol"],
                            "side": trigger["side"], "reason": "ORDER_BUDGET"})
            break
        close_keys = _dependent_cycle_keys(key=trigger["key"], state=state, settings=settings, pmap=pmap)
        if any((candidate.split("|", 1)[0], candidate.split("|", 1)[1]) in order_keys for candidate in close_keys):
            actions.append({"kind": "STOP_LOSS_WAIT", "symbol": trigger["symbol"],
                            "side": trigger["side"], "reason": "OPEN_ORDER_ON_CYCLE"})
            continue

        cycle_id = str((state.get(trigger["key"]) or {}).get("cycleId") or
                       hashlib.sha256(f"{uid}|{trigger['key']}".encode()).hexdigest()[:16])
        for close_key in close_keys:
            if close_key in processed:
                continue
            processed.add(close_key)
            close_symbol, close_side = close_key.split("|", 1)
            residual = pmap.get(close_key)
            attempt = 0
            close_failed = False
            while residual is not None and attempt < 3 and sent < budget:
                plan = _close_plan(residual)
                if plan.quantity <= 0 or plan.notional_per_leg <= 0:
                    break
                stable = hashlib.sha256(f"{uid}|{cycle_id}|{close_key}|{attempt}".encode()).hexdigest()[:12]
                metadata = {"kind": "STOP_LOSS", "symbol": close_symbol, "side": close_side,
                            "triggerSide": trigger["side"], "cycleId": cycle_id,
                            "mode": mode, "limit": trigger["limit"]}
                try:
                    result = execute_leg_once(
                        client, plan, side=PositionSide(close_side), action="CLOSE",
                        id_prefix=f"mbb-sl-{stable}", confirm=True,
                        automatic_loss_exit_authorized=True,
                        before_submit=lambda intent, _m=metadata: _before(before_order, intent, _m),
                        fill_poll_attempts=3, fill_poll_delay_seconds=0.15,
                    )
                    sent += 1
                    fill = result.get("result") if isinstance(result, dict) else {}
                    fill = fill if isinstance(fill, dict) else {}
                    _audit(ref, {"event": "MULTI_BB_STOP_LOSS_CLOSE", "symbol": close_symbol,
                                 "side": close_side, "triggerSide": trigger["side"],
                                 "stopLossMode": mode, "stopLossValue": trigger["limit"],
                                 "triggerPnlUsd": trigger["pnlUsd"],
                                 "triggerLossPercent": trigger["lossPercent"],
                                 "quantity": float(plan.quantity),
                                 "orderId": fill.get("orderId") or fill.get("clientOrderId"),
                                 "fillStatus": fill.get("status"),
                                 "result": "submitted-confirmed", "attempt": attempt})
                except Exception as exc:
                    sent += 1
                    close_failed = True
                    actions.append({"kind": "STOP_LOSS_ERROR", "symbol": close_symbol,
                                    "side": close_side, "reason": str(exc)})
                    _audit(ref, {"event": "MULTI_BB_STOP_LOSS_ERROR", "symbol": close_symbol,
                                 "side": close_side, "triggerSide": trigger["side"],
                                 "stopLossMode": mode, "stopLossValue": trigger["limit"],
                                 "triggerPnlUsd": trigger["pnlUsd"],
                                 "triggerLossPercent": trigger["lossPercent"],
                                 "quantity": float(plan.quantity), "result": "error",
                                 "error": str(exc)[:500], "attempt": attempt})
                    break
                fresh = _position_map(client.position_risk(close_symbol))
                residual = fresh.get(close_key)
                pmap = {**pmap, **fresh}
                if residual is None:
                    pmap.pop(close_key, None)
                    state.pop(close_key, None)
                    actions.append({"kind": "STOP_LOSS_CLOSED", "symbol": close_symbol,
                                    "side": close_side, "triggerSide": trigger["side"]})
                    break
                actions.append({"kind": "STOP_LOSS_PARTIAL_FILL", "symbol": close_symbol,
                                "side": close_side, "remainingQty": abs(_f(residual.get("positionAmt")))})
                attempt += 1
            if close_failed or residual is not None:
                actions.append({"kind": "STOP_LOSS_RECONCILING", "symbol": close_symbol,
                                "side": close_side, "reason": "RESIDUAL_POSITION"})
                # Never close a paired LONG while its dependent SHORT could still
                # be open. A later tick resumes with the same deterministic IDs.
                break

    fresh_positions = client.position_risk() if sent else positions
    fresh_orders = client.open_orders() if sent else open_orders
    fresh_account = client.account_information() if sent else account
    report = {"enabled": True, "mode": mode,
              "status": "EXECUTED" if any(a.get("kind") == "STOP_LOSS_CLOSED" for a in actions) else "WAITING",
              "ordersSent": sent, "actions": actions[-100:]}
    ref.set({"multiBbPositions": state, "stopLossReport": report, "phase": "RUNNING",
             "lastReason": "Stoploss heeft uitvoeringsprioriteit; overige trading wacht op de volgende scan",
             "updatedAt": datetime.now(timezone.utc)}, merge=True)
    return StopLossGateResult(True, report, {**raw_state, "multiBbPositions": state, "stopLossReport": report},
                              fresh_account, fresh_positions, fresh_orders, sent)
