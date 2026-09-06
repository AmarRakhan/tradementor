"""Portfolio Take Profit cycle gate for the Multi BB runtime.

This module deliberately sits *in front of* the proven Multi BB engine.  It
never changes the asymmetric hedge state machine.  In PORTFOLIO mode it
preempts every scanner/DCA/per-position TP action, closes exchange exposure,
confirms flat, records real exchange equity and only then permits a clean new
cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
import hashlib
import math
import time

from aster_execution import PairExecutionPlan, execute_leg_once
from aster_gateway import PositionSide


PORTFOLIO_TP_EXECUTING = "PORTFOLIO_TP_EXECUTING"
FLAT_CONFIRMING = "FLAT_CONFIRMING"
FLAT_CONFIRMED = "FLAT_CONFIRMED"
RESTARTING = "RESTARTING"
RUNNING = "RUNNING"
ACTIVE_EXIT_STATES = {PORTFOLIO_TP_EXECUTING, FLAT_CONFIRMING, RESTARTING}


class PortfolioCycleOrderBlocked(RuntimeError):
    """A stale worker tried to submit an order forbidden by the current cycle."""


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def exchange_equity(account: dict[str, Any] | None) -> float:
    """Read the authoritative joined-margin account equity from Aster payloads."""
    row = account or {}
    for key in ("totalMarginBalance", "marginBalance", "equity", "totalWalletBalance", "walletBalance"):
        value = _f(row.get(key))
        if value > 0:
            return value
    return 0.0


def target_equity(cycle_start_equity: float, portfolio_tp_percent: float) -> float:
    start = _f(cycle_start_equity)
    pct = _f(portfolio_tp_percent)
    if start <= 0:
        return 0.0
    return start * (1.0 + pct / 100.0)


def _new_cycle(uid: str, *, equity: float, portfolio_tp_percent: float, timestamp_ms: int) -> dict[str, Any]:
    seed = f"{uid}|portfolio-cycle|{timestamp_ms}|{equity:.12f}"
    cycle_id = hashlib.sha256(seed.encode()).hexdigest()[:20]
    return {
        "cycleId": cycle_id,
        "cycleStartEquity": equity,
        "targetEquity": target_equity(equity, portfolio_tp_percent),
        "cycleEndEquity": None,
        "cycleStatus": RUNNING,
        "portfolioTpTriggeredAt": None,
        "flatConfirmedAt": None,
        "restartStartedAt": None,
        "startedAtMs": timestamp_ms,
        "updatedAtMs": timestamp_ms,
    }


def ensure_cycle(raw_state: dict[str, Any], *, uid: str, current_equity: float,
                 portfolio_tp_percent: float, timestamp_ms: int) -> tuple[dict[str, Any], bool]:
    """Return a durable cycle without ever rebasing an already valid baseline."""
    existing = raw_state.get("multiBbCycle") if isinstance(raw_state.get("multiBbCycle"), dict) else {}
    start = _f(existing.get("cycleStartEquity"))
    cycle_id = str(existing.get("cycleId") or "").strip()
    if start > 0 and cycle_id:
        cycle = dict(existing)
        cycle["targetEquity"] = target_equity(start, portfolio_tp_percent)
        cycle.setdefault("cycleStatus", RUNNING)
        cycle["updatedAtMs"] = timestamp_ms
        return cycle, False
    # Legacy active accounts cannot reconstruct a pre-deployment baseline from
    # exchange truth.  Seed it exactly once from current exchange equity without
    # touching positions, DCA counts or per-leg cycle ids.
    cycle = _new_cycle(uid, equity=current_equity, portfolio_tp_percent=portfolio_tp_percent, timestamp_ms=timestamp_ms)
    cycle["baselineSource"] = "CYCLE_START" if not raw_state.get("multiBbPositions") else "MIGRATION_CURRENT_EXCHANGE_EQUITY"
    return cycle, True


def portfolio_cycle_snapshot(cycle: dict[str, Any], *, mode: str, current_equity: float,
                             portfolio_tp_percent: float) -> dict[str, Any]:
    start = _f(cycle.get("cycleStartEquity"))
    target = target_equity(start, portfolio_tp_percent)
    current = _f(current_equity)
    distance_usd = max(0.0, target - current) if target > 0 else 0.0
    distance_pct = distance_usd / current * 100 if current > 0 else 0.0
    return {
        "cycleId": str(cycle.get("cycleId") or ""),
        "cycleStartEquity": start,
        "takeProfitMode": mode,
        "portfolioTpPercent": portfolio_tp_percent,
        "targetEquity": target,
        "currentEquity": current,
        "distanceToTargetUsd": distance_usd,
        "distanceToTargetPct": distance_pct,
        "cycleEndEquity": cycle.get("cycleEndEquity"),
        "cycleStatus": str(cycle.get("cycleStatus") or RUNNING),
        "portfolioTpTriggeredAt": cycle.get("portfolioTpTriggeredAt"),
        "flatConfirmedAt": cycle.get("flatConfirmedAt"),
        "restartStartedAt": cycle.get("restartStartedAt"),
    }


def _position_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows or []:
        side = str(row.get("positionSide", "")).upper()
        qty = abs(_f(row.get("positionAmt")))
        symbol = str(row.get("symbol", "")).upper()
        if symbol and side in {"LONG", "SHORT"} and qty > 0:
            result.append(row)
    return result


def _is_multi_bb_order(row: dict[str, Any]) -> bool:
    value = str(row.get("clientOrderId", row.get("origClientOrderId", row.get("newClientOrderId", "")))).lower()
    return value.startswith("mbb-")


def _cancel_bot_orders(client: Any, rows: list[dict[str, Any]], actions: list[dict[str, Any]]) -> int:
    cancelled = 0
    for row in rows or []:
        if not _is_multi_bb_order(row):
            continue
        symbol = str(row.get("symbol", "")).upper()
        order_id = row.get("orderId")
        client_order_id = row.get("clientOrderId") or row.get("origClientOrderId")
        client.cancel_order(symbol, order_id=order_id if order_id is not None else None,
                            client_order_id=None if order_id is not None else str(client_order_id or ""))
        cancelled += 1
        actions.append({"kind": "PORTFOLIO_TP_CANCEL_ORDER", "symbol": symbol,
                        "orderId": str(order_id or client_order_id or "")})
    return cancelled


def _close_id(uid: str, cycle_id: str, symbol: str, side: str, qty: float) -> str:
    digest = hashlib.sha256(f"{uid}|{cycle_id}|{symbol}|{side}|{qty:.12f}".encode()).hexdigest()[:12]
    return f"mbb-ptp-{digest}"


def _write_cycle(ref: Any, cycle: dict[str, Any], *, phase: str | None = None,
                 reason: str | None = None, extra: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"multiBbCycle": cycle, "updatedAt": datetime.now(timezone.utc)}
    if phase is not None:
        payload["phase"] = phase
    if reason is not None:
        payload["lastReason"] = reason
    if extra:
        payload.update(extra)
    ref.set(payload, merge=True)


def assert_order_allowed(ref: Any, intent: Any, *, client: Any | None = None) -> None:
    """Last-millisecond race guard for stale workers.

    The durable cycle state wins over any worker-local snapshot.  Per-trade TP
    closes are also rejected immediately after a mode switch to PORTFOLIO/OFF.
    """
    latest = ref.get().to_dict() or {}
    cycle = latest.get("multiBbCycle") if isinstance(latest.get("multiBbCycle"), dict) else {}
    status = str(cycle.get("cycleStatus") or RUNNING).upper()
    action = str(getattr(intent, "action", "")).upper()
    intent_id = str(getattr(intent, "intent_id", "")).lower()
    if status in ACTIVE_EXIT_STATES and not intent_id.startswith("mbb-ptp-"):
        raise PortfolioCycleOrderBlocked(f"{status}: normale Strategy-2 order geblokkeerd")
    settings = latest.get("settings") if isinstance(latest.get("settings"), dict) else {}
    mode = str(settings.get("takeProfitMode", "PER_TRADE")).upper()
    if intent_id.startswith("mbb-tp-") and mode != "PER_TRADE":
        raise PortfolioCycleOrderBlocked(f"Take Profit Mode {mode}: individuele TP geblokkeerd")
    if action == "OPEN" and mode == "PORTFOLIO" and client is not None:
        current = exchange_equity(client.account_information())
        start = _f(cycle.get("cycleStartEquity"))
        target = target_equity(start, _f(settings.get("portfolioTpPercent")))
        if start > 0 and target > 0 and current >= target:
            raise PortfolioCycleOrderBlocked("Portfolio target is bereikt; nieuwe exposure geblokkeerd")


@dataclass(frozen=True)
class PortfolioGateResult:
    handled: bool
    restart: bool
    report: dict[str, Any]
    raw_state: dict[str, Any]
    account: dict[str, Any]
    positions: list[dict[str, Any]]
    open_orders: list[dict[str, Any]]
    orders_sent: int = 0


def portfolio_cycle_gate(*, client: Any, ref: Any, raw_state: dict[str, Any], uid: str,
                         account: dict[str, Any], positions: list[dict[str, Any]],
                         open_orders: list[dict[str, Any]], timestamp_ms: int,
                         take_profit_mode: str, portfolio_tp_percent: float,
                         dry_run: bool = False, order_budget: int | None = None,
                         before_order: Any = None) -> PortfolioGateResult:
    mode = str(take_profit_mode or "PER_TRADE").upper()
    equity = exchange_equity(account)
    cycle, created = ensure_cycle(raw_state, uid=uid, current_equity=equity,
                                  portfolio_tp_percent=portfolio_tp_percent, timestamp_ms=timestamp_ms)
    cycle["targetEquity"] = target_equity(_f(cycle.get("cycleStartEquity")), portfolio_tp_percent)
    cycle["updatedAtMs"] = timestamp_ms
    snapshot = portfolio_cycle_snapshot(cycle, mode=mode, current_equity=equity,
                                        portfolio_tp_percent=portfolio_tp_percent)
    if created and not dry_run:
        _write_cycle(ref, cycle, reason="Cycle baseline vastgelegd op echte Aster-equity")

    status = str(cycle.get("cycleStatus") or RUNNING).upper()
    target = _f(cycle.get("targetEquity"))
    triggered = mode == "PORTFOLIO" and target > 0 and equity >= target
    if status == RUNNING and triggered:
        cycle.update({"cycleStatus": PORTFOLIO_TP_EXECUTING,
                      "portfolioTpTriggeredAt": datetime.now(timezone.utc),
                      "portfolioTpTriggeredAtMs": timestamp_ms,
                      "updatedAtMs": timestamp_ms})
        status = PORTFOLIO_TP_EXECUTING
        snapshot = portfolio_cycle_snapshot(cycle, mode=mode, current_equity=equity,
                                            portfolio_tp_percent=portfolio_tp_percent)
        if not dry_run:
            _write_cycle(ref, cycle, phase=PORTFOLIO_TP_EXECUTING,
                         reason=f"Portfolio TP bereikt op echte Aster-equity {equity:.8f}; volledige exit gestart")
            ref.collection("audit").add({"event": "PORTFOLIO_TP_TRIGGERED", "user": uid,
                "cycleId": cycle.get("cycleId"), "cycleStartEquity": cycle.get("cycleStartEquity"),
                "targetEquity": target, "currentEquity": equity, "timestamp": datetime.now(timezone.utc)})

    if status not in ACTIVE_EXIT_STATES:
        return PortfolioGateResult(False, False, snapshot, raw_state, account, positions, open_orders, 0)

    # From this point the portfolio exit is transactional and has absolute
    # priority even if the user changes TP mode while the exit is already live.
    actions: list[dict[str, Any]] = []
    if dry_run:
        actions.append({"kind": "PORTFOLIO_TP_WOULD_EXIT", "positions": len(_position_rows(positions)),
                        "targetEquity": target, "currentEquity": equity})
        return PortfolioGateResult(True, False, {**snapshot, "actions": actions, "ordersSent": 0},
                                   raw_state, account, positions, open_orders, 0)

    _cancel_bot_orders(client, open_orders, actions)
    fresh_orders = client.open_orders()
    remaining_bot_orders = [row for row in fresh_orders if _is_multi_bb_order(row)]
    if remaining_bot_orders:
        cycle["cycleStatus"] = FLAT_CONFIRMING
        cycle["updatedAtMs"] = timestamp_ms
        _write_cycle(ref, cycle, phase=FLAT_CONFIRMING,
                     reason="Portfolio TP: wachten totdat alle botorders geannuleerd zijn")
        report = {**portfolio_cycle_snapshot(cycle, mode=mode, current_equity=equity,
                                             portfolio_tp_percent=portfolio_tp_percent),
                  "actions": actions, "ordersSent": 0, "remainingBotOrders": len(remaining_bot_orders)}
        return PortfolioGateResult(True, False, report, raw_state, account, positions, fresh_orders, 0)

    live_positions = _position_rows(client.position_risk())
    budget = max(0, 15 if order_budget is None else int(order_budget))
    sent = 0
    for row in live_positions:
        if sent >= budget:
            break
        symbol = str(row.get("symbol", "")).upper()
        side = str(row.get("positionSide", "")).upper()
        qty = abs(_f(row.get("positionAmt")))
        mark = _f(row.get("markPrice"), _f(row.get("entryPrice")))
        leverage = max(1, _i(row.get("leverage"), 1))
        if not symbol or side not in {"LONG", "SHORT"} or qty <= 0 or mark <= 0:
            continue
        plan = PairExecutionPlan(symbol, Decimal(str(qty)), Decimal(str(qty * mark)), leverage)
        cycle_id = str(cycle.get("cycleId") or "cycle")
        prefix = _close_id(uid, cycle_id, symbol, side, qty)

        def reserve(intent: Any, *, _symbol=symbol, _side=side) -> None:
            assert_order_allowed(ref, intent, client=client)
            if before_order is not None:
                try:
                    before_order(intent, {"kind": "PORTFOLIO_TP_CLOSE", "cycleId": cycle_id,
                                          "symbol": _symbol, "side": _side, "dcaNumber": None})
                except TypeError:
                    before_order(intent)

        execute_leg_once(client, plan, side=PositionSide(side), action="CLOSE", id_prefix=prefix,
                         confirm=True, manual_loss_confirmation=True, before_submit=reserve)
        sent += 1
        actions.append({"kind": "PORTFOLIO_TP_CLOSE", "symbol": symbol, "side": side, "qty": qty})

    remaining_positions = _position_rows(client.position_risk())
    remaining_orders = client.open_orders()
    remaining_bot_orders = [row for row in remaining_orders if _is_multi_bb_order(row)]
    if remaining_positions or remaining_bot_orders:
        cycle["cycleStatus"] = FLAT_CONFIRMING
        cycle["updatedAtMs"] = int(time.time() * 1000)
        _write_cycle(ref, cycle, phase=FLAT_CONFIRMING,
                     reason=f"Portfolio TP: flat reconciliatie ({len(remaining_positions)} posities, {len(remaining_bot_orders)} botorders resterend)")
        report = {**portfolio_cycle_snapshot(cycle, mode=mode, current_equity=exchange_equity(client.account_information()),
                                             portfolio_tp_percent=portfolio_tp_percent),
                  "actions": actions[-50:], "ordersSent": sent,
                  "remainingPositions": len(remaining_positions), "remainingBotOrders": len(remaining_bot_orders)}
        ref.set({"multiBbReport": report}, merge=True)
        return PortfolioGateResult(True, False, report, raw_state, account, remaining_positions, remaining_orders, sent)

    # Exchange is truly flat. Only now may realized end-equity become the next
    # baseline. Never use the theoretical target.
    final_account = client.account_information()
    end_equity = exchange_equity(final_account)
    now = datetime.now(timezone.utc)
    cycle.update({"cycleStatus": FLAT_CONFIRMED, "cycleEndEquity": end_equity,
                  "flatConfirmedAt": now, "flatConfirmedAtMs": int(now.timestamp() * 1000),
                  "updatedAtMs": int(now.timestamp() * 1000)})
    completed_cycle = dict(cycle)
    enabled = bool((ref.get().to_dict() or {}).get("enabled", raw_state.get("enabled", False)))
    base_extra = {"multiBbPositions": {}, "multiBbLastCompletedCycle": completed_cycle}
    if not enabled:
        _write_cycle(ref, cycle, phase=FLAT_CONFIRMED,
                     reason="Portfolio TP afgerond en exchange flat; bot staat UIT dus geen herstart", extra=base_extra)
        report = {**portfolio_cycle_snapshot(cycle, mode=mode, current_equity=end_equity,
                                             portfolio_tp_percent=portfolio_tp_percent),
                  "actions": actions[-50:], "ordersSent": sent, "autoRestarted": False}
        ref.set({"multiBbReport": report}, merge=True)
        return PortfolioGateResult(True, False, report, {**raw_state, **base_extra, "multiBbCycle": cycle},
                                   final_account, [], [], sent)

    restart_ms = max(timestamp_ms + 1, int(time.time() * 1000))
    next_cycle = _new_cycle(uid, equity=end_equity, portfolio_tp_percent=portfolio_tp_percent, timestamp_ms=restart_ms)
    next_cycle["restartStartedAt"] = now
    next_cycle["restartStartedAtMs"] = restart_ms
    _write_cycle(ref, next_cycle, phase=RESTARTING,
                 reason=f"Portfolio TP flat bevestigd; nieuwe cycle start vanaf echte equity {end_equity:.8f}",
                 extra={**base_extra, "multiBbAdoptionPending": False})
    ref.collection("audit").add({"event": "PORTFOLIO_TP_FLAT_CONFIRMED", "user": uid,
        "cycleId": completed_cycle.get("cycleId"), "cycleEndEquity": end_equity,
        "nextCycleId": next_cycle.get("cycleId"), "timestamp": now})
    restart_raw = {**raw_state, **base_extra, "multiBbCycle": next_cycle,
                   "multiBbAdoptionPending": False, "phase": RESTARTING}
    report = {**portfolio_cycle_snapshot(next_cycle, mode=mode, current_equity=end_equity,
                                         portfolio_tp_percent=portfolio_tp_percent),
              "actions": actions[-50:], "ordersSent": sent, "autoRestarted": True,
              "previousCycleEndEquity": end_equity}
    return PortfolioGateResult(True, True, report, restart_raw, final_account, [], [], sent)
