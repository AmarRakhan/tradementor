"""Portfolio Take Profit cycle gate for the Multi BB runtime.

This module deliberately sits *in front of* the proven Multi BB engine. It
never changes the asymmetric hedge state machine. PORTFOLIO mode is additive:
normal per-position TP remains active while the portfolio target is below its
threshold. Once the portfolio target is reached, the portfolio exit preempts
scanner/DCA/per-position TP actions, closes exchange exposure, confirms flat,
records real exchange equity and only then permits a clean new cycle.
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
PORTFOLIO_TP_INPUT_MODES = {"PERCENT", "USD"}
PORTFOLIO_TP_BASE_MODES = {"CYCLE_START", "CURRENT_VALUE", "CUSTOM"}


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
    """Legacy percentage helper retained for older callers/tests."""
    start = _f(cycle_start_equity)
    pct = _f(portfolio_tp_percent)
    if start <= 0:
        return 0.0
    return start * (1.0 + pct / 100.0)


def _normalize_input_mode(value: Any) -> str:
    text = str(value or "PERCENT").strip().upper().replace("%", "PERCENT").replace("$", "USD")
    return text if text in PORTFOLIO_TP_INPUT_MODES else "PERCENT"


def _normalize_base_mode(value: Any) -> str:
    text = str(value or "CYCLE_START").strip().upper().replace("-", "_").replace(" ", "_")
    return text if text in PORTFOLIO_TP_BASE_MODES else "CYCLE_START"


def target_equity_v2(base_equity: float, input_mode: str, value: float) -> float:
    base = _f(base_equity)
    amount = _f(value)
    if base <= 0 or amount <= 0:
        return 0.0
    if _normalize_input_mode(input_mode) == "USD":
        return base + amount
    return base * (1.0 + amount / 100.0)


def _new_cycle(uid: str, *, equity: float, portfolio_tp_percent: float, timestamp_ms: int,
               portfolio_tp_input_mode: str = "PERCENT", portfolio_tp_value: float | None = None,
               portfolio_tp_base_mode: str = "CYCLE_START", portfolio_tp_custom_base_equity: float = 0.0,
               config_version: int = 0, current_long_slots: int | None = None,
               current_short_slots: int | None = None, current_maximum_positions: int | None = None) -> dict[str, Any]:
    seed = f"{uid}|portfolio-cycle|{timestamp_ms}|{equity:.12f}"
    cycle_id = hashlib.sha256(seed.encode()).hexdigest()[:20]
    input_mode = _normalize_input_mode(portfolio_tp_input_mode)
    value = _f(portfolio_tp_value, _f(portfolio_tp_percent)) if portfolio_tp_value is not None else _f(portfolio_tp_percent)
    base_mode = _normalize_base_mode(portfolio_tp_base_mode)
    custom = _f(portfolio_tp_custom_base_equity)
    base = custom if base_mode == "CUSTOM" and custom > 0 else _f(equity)
    return {
        "cycleId": cycle_id,
        "cycleStartEquity": equity,
        "baseMode": base_mode,
        "baseEquity": base,
        "customBaseEquity": custom if custom > 0 else None,
        "baseConfigVersion": int(config_version or 0),
        "cycleStartLongSlots": None if current_long_slots is None else max(0, _i(current_long_slots)),
        "cycleStartShortSlots": None if current_short_slots is None else max(0, _i(current_short_slots)),
        "cycleStartMaximumPositions": None if current_maximum_positions is None else max(0, _i(current_maximum_positions)),
        "seatSnapshotSource": "CYCLE_START" if current_long_slots is not None and current_short_slots is not None else None,
        "seatResetArmed": False,
        "seatResetTargetLongSlots": None,
        "seatResetTargetShortSlots": None,
        "seatResetTargetMaximumPositions": None,
        "seatResetTargetSource": None,
        "slotResetCompletedAt": None,
        "slotResetCompletedAtMs": None,
        "slotResetCycleId": None,
        "takeProfitInputMode": input_mode,
        "takeProfitValue": value,
        "targetEquity": target_equity_v2(base, input_mode, value),
        "cycleEndEquity": None,
        "cycleStatus": RUNNING,
        "portfolioTpTriggeredAt": None,
        "flatConfirmedAt": None,
        "restartStartedAt": None,
        "startedAtMs": timestamp_ms,
        "updatedAtMs": timestamp_ms,
    }


def ensure_cycle(raw_state: dict[str, Any], *, uid: str, current_equity: float,
                 portfolio_tp_percent: float, timestamp_ms: int,
                 portfolio_tp_input_mode: str = "PERCENT", portfolio_tp_value: float | None = None,
                 portfolio_tp_base_mode: str = "CYCLE_START", portfolio_tp_custom_base_equity: float = 0.0,
                 config_version: int = 0, current_long_slots: int | None = None,
                 current_short_slots: int | None = None, current_maximum_positions: int | None = None) -> tuple[dict[str, Any], bool]:
    """Return durable cycle state and snapshot a requested base at most once per config version."""
    existing = raw_state.get("multiBbCycle") if isinstance(raw_state.get("multiBbCycle"), dict) else {}
    start = _f(existing.get("cycleStartEquity"))
    cycle_id = str(existing.get("cycleId") or "").strip()
    input_mode = _normalize_input_mode(portfolio_tp_input_mode)
    value = _f(portfolio_tp_value, _f(portfolio_tp_percent)) if portfolio_tp_value is not None else _f(portfolio_tp_percent)
    requested_base_mode = _normalize_base_mode(portfolio_tp_base_mode)
    custom = _f(portfolio_tp_custom_base_equity)
    if start > 0 and cycle_id:
        cycle = dict(existing)
        changed = False
        prior_version = _i(cycle.get("baseConfigVersion"), 0)
        should_apply_base = "baseEquity" not in cycle or (int(config_version or 0) > 0 and prior_version != int(config_version or 0))
        if should_apply_base:
            if requested_base_mode == "CURRENT_VALUE":
                base = _f(current_equity)
            elif requested_base_mode == "CUSTOM" and custom > 0:
                base = custom
            else:
                base = start
                requested_base_mode = "CYCLE_START"
            cycle["baseMode"] = requested_base_mode
            cycle["baseEquity"] = base
            cycle["customBaseEquity"] = custom if custom > 0 else None
            cycle["baseConfigVersion"] = int(config_version or 0)
            changed = True
        else:
            base = _f(cycle.get("baseEquity"), start) or start
        new_target = target_equity_v2(base, input_mode, value)
        if abs(_f(cycle.get("targetEquity")) - new_target) > 1e-12:
            changed = True
        cycle["takeProfitInputMode"] = input_mode
        cycle["takeProfitValue"] = value
        cycle["targetEquity"] = new_target
        cycle.setdefault("baseMode", "CYCLE_START")
        cycle.setdefault("baseEquity", start)
        cycle.setdefault("cycleStatus", RUNNING)
        if cycle.get("cycleStartLongSlots") is None and current_long_slots is not None:
            cycle["cycleStartLongSlots"] = max(0, _i(current_long_slots))
            changed = True
        if cycle.get("cycleStartShortSlots") is None and current_short_slots is not None:
            cycle["cycleStartShortSlots"] = max(0, _i(current_short_slots))
            changed = True
        if cycle.get("cycleStartMaximumPositions") is None and current_maximum_positions is not None:
            cycle["cycleStartMaximumPositions"] = max(0, _i(current_maximum_positions))
            changed = True
        if cycle.get("seatSnapshotSource") is None and cycle.get("cycleStartLongSlots") is not None and cycle.get("cycleStartShortSlots") is not None:
            cycle["seatSnapshotSource"] = "MIGRATION_CURRENT_SETTINGS"
            changed = True
        cycle.setdefault("seatResetArmed", False)
        cycle.setdefault("seatResetTargetLongSlots", None)
        cycle.setdefault("seatResetTargetShortSlots", None)
        cycle.setdefault("seatResetTargetMaximumPositions", None)
        cycle.setdefault("seatResetTargetSource", None)
        cycle.setdefault("slotResetCompletedAt", None)
        cycle.setdefault("slotResetCompletedAtMs", None)
        cycle.setdefault("slotResetCycleId", None)
        cycle["updatedAtMs"] = timestamp_ms
        return cycle, changed
    # Legacy active accounts cannot reconstruct a pre-deployment baseline from
    # exchange truth. Seed it exactly once without touching positions or DCA state.
    cycle = _new_cycle(
        uid, equity=current_equity, portfolio_tp_percent=portfolio_tp_percent, timestamp_ms=timestamp_ms,
        portfolio_tp_input_mode=input_mode, portfolio_tp_value=value,
        portfolio_tp_base_mode=requested_base_mode, portfolio_tp_custom_base_equity=custom,
        config_version=config_version, current_long_slots=current_long_slots,
        current_short_slots=current_short_slots, current_maximum_positions=current_maximum_positions,
    )
    cycle["baselineSource"] = "CYCLE_START" if not raw_state.get("multiBbPositions") else "MIGRATION_CURRENT_EXCHANGE_EQUITY"
    return cycle, True


def reset_cycle_to_equity(*, uid: str, current_equity: float, portfolio_tp_percent: float,
                          timestamp_ms: int, portfolio_tp_input_mode: str = "PERCENT",
                          portfolio_tp_value: float | None = None, config_version: int = 0,
                          current_long_slots: int | None = None, current_short_slots: int | None = None,
                          current_maximum_positions: int | None = None) -> dict[str, Any]:
    """Manual reset: new portfolio cycle baseline only; never submits/cancels an order."""
    cycle = _new_cycle(
        uid, equity=_f(current_equity), portfolio_tp_percent=portfolio_tp_percent, timestamp_ms=timestamp_ms,
        portfolio_tp_input_mode=portfolio_tp_input_mode, portfolio_tp_value=portfolio_tp_value,
        portfolio_tp_base_mode="CYCLE_START", portfolio_tp_custom_base_equity=0.0,
        config_version=config_version, current_long_slots=current_long_slots,
        current_short_slots=current_short_slots, current_maximum_positions=current_maximum_positions,
    )
    cycle["baselineSource"] = "MANUAL_RESET_CURRENT_EQUITY"
    return cycle


def portfolio_cycle_snapshot(cycle: dict[str, Any], *, mode: str, current_equity: float,
                             portfolio_tp_percent: float) -> dict[str, Any]:
    start = _f(cycle.get("cycleStartEquity"))
    input_mode = _normalize_input_mode(cycle.get("takeProfitInputMode"))
    value = _f(cycle.get("takeProfitValue"), portfolio_tp_percent)
    base_mode = _normalize_base_mode(cycle.get("baseMode"))
    base = _f(cycle.get("baseEquity"), start) or start
    target = target_equity_v2(base, input_mode, value)
    current = _f(current_equity)
    distance_usd = max(0.0, target - current) if target > 0 else 0.0
    distance_pct = distance_usd / current * 100 if current > 0 else 0.0
    return {
        "cycleId": str(cycle.get("cycleId") or ""),
        "cycleStartEquity": start,
        "takeProfitMode": mode,
        "portfolioTpPercent": value if input_mode == "PERCENT" else portfolio_tp_percent,
        "takeProfitInputMode": input_mode,
        "takeProfitValue": value,
        "baseMode": base_mode,
        "baseEquity": base,
        "customBaseEquity": cycle.get("customBaseEquity"),
        "targetEquity": target,
        "currentEquity": current,
        "distanceToTargetUsd": distance_usd,
        "distanceToTargetPct": distance_pct,
        "cycleEndEquity": cycle.get("cycleEndEquity"),
        "cycleStatus": str(cycle.get("cycleStatus") or RUNNING),
        "portfolioTpTriggeredAt": cycle.get("portfolioTpTriggeredAt"),
        "flatConfirmedAt": cycle.get("flatConfirmedAt"),
        "restartStartedAt": cycle.get("restartStartedAt"),
        "cycleStartLongSlots": cycle.get("cycleStartLongSlots"),
        "cycleStartShortSlots": cycle.get("cycleStartShortSlots"),
        "cycleStartMaximumPositions": cycle.get("cycleStartMaximumPositions"),
        "seatSnapshotSource": cycle.get("seatSnapshotSource"),
        "seatResetArmed": bool(cycle.get("seatResetArmed", False)),
        "seatResetTargetLongSlots": cycle.get("seatResetTargetLongSlots"),
        "seatResetTargetShortSlots": cycle.get("seatResetTargetShortSlots"),
        "seatResetTargetMaximumPositions": cycle.get("seatResetTargetMaximumPositions"),
        "seatResetTargetSource": cycle.get("seatResetTargetSource"),
        "slotResetCompletedAt": cycle.get("slotResetCompletedAt"),
        "slotResetCompletedAtMs": cycle.get("slotResetCompletedAtMs"),
        "slotResetCycleId": cycle.get("slotResetCycleId"),
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


def _portfolio_tp_seat_reset_target(cycle: dict[str, Any], settings: dict[str, Any]) -> tuple[int | None, int | None, int | None, str | None]:
    """Resolve one immutable reset target; explicit account config wins over legacy cycle-start fallback."""
    frozen_long = cycle.get("seatResetTargetLongSlots")
    frozen_short = cycle.get("seatResetTargetShortSlots")
    if frozen_long is not None and frozen_short is not None:
        target_long = max(0, _i(frozen_long))
        target_short = max(0, _i(frozen_short))
        frozen_max = cycle.get("seatResetTargetMaximumPositions")
        target_max = target_long + target_short if frozen_max is None else max(0, _i(frozen_max))
        return target_long, target_short, target_max, str(cycle.get("seatResetTargetSource") or "FROZEN")

    configured_long = settings.get("portfolioTpResetLongSlots")
    configured_short = settings.get("portfolioTpResetShortSlots")
    if configured_long is not None and configured_short is not None:
        target_long = max(0, _i(configured_long))
        target_short = max(0, _i(configured_short))
        return target_long, target_short, target_long + target_short, "CONFIGURED"

    if cycle.get("cycleStartLongSlots") is None or cycle.get("cycleStartShortSlots") is None:
        return None, None, None, None
    target_long = max(0, _i(cycle.get("cycleStartLongSlots")))
    target_short = max(0, _i(cycle.get("cycleStartShortSlots")))
    target_max = max(1, _i(cycle.get("cycleStartMaximumPositions"), target_long + target_short or 1))
    return target_long, target_short, target_max, "LEGACY_CYCLE_START"


def portfolio_tp_seat_reset_plan(cycle: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Build an order-free seat mutation from the target frozen when Portfolio TP triggered.

    Explicit Build 470 reset targets are exact: they are never silently clamped.
    Accounts without the new fields retain the pre-Build-470 cycle-start fallback,
    including its historic capacity-clamp behavior.
    """
    current = dict(settings or {})
    cycle_id = str(cycle.get("cycleId") or "")
    target_long, target_short, target_max, target_source = _portfolio_tp_seat_reset_target(cycle, current)
    if target_long is None or target_short is None or target_max is None:
        return {"applied": False, "reason": "cycle-seat-snapshot-missing", "settings": current, "cycleId": cycle_id}

    before_long = max(0, _i(current.get("longSlots")))
    before_short = max(0, _i(current.get("shortSlots")))
    before_max = max(0, _i(current.get("maximumPositions"), before_long + before_short))
    universe = min(800, max(1, _i(current.get("universeTopN"), 30)))
    capacity = 200 if bool(current.get("manualSymbolSelectionEnabled", False)) else universe * 2
    zone_enabled = bool(current.get("zoneSoldiersEnabled", False))
    asymmetric = bool(current.get("asymmetricHedgeModeEnabled", False))
    explicit_target = target_source not in {None, "LEGACY_CYCLE_START"}
    clamped = False

    if explicit_target:
        # Saving validates this already. Re-check against current account capacity
        # because Top-N/manual-selection may have changed after the target was saved.
        if target_long + target_short != target_max:
            return {"applied": False, "reason": "configured-reset-target-total-mismatch", "settings": current, "cycleId": cycle_id,
                    "targetLongSlots": target_long, "targetShortSlots": target_short, "targetMaximumPositions": target_max}
        if target_max > capacity:
            return {"applied": False, "reason": "configured-reset-target-exceeds-current-capacity", "settings": current, "cycleId": cycle_id,
                    "targetLongSlots": target_long, "targetShortSlots": target_short, "targetMaximumPositions": target_max,
                    "currentCapacity": capacity}
        if asymmetric and target_long != target_short:
            return {"applied": False, "reason": "configured-reset-target-invalid-for-asymmetric-mode", "settings": current, "cycleId": cycle_id,
                    "targetLongSlots": target_long, "targetShortSlots": target_short, "targetMaximumPositions": target_max}
    elif zone_enabled:
        if target_max > capacity:
            target_max = capacity
            clamped = True
        target_long = min(target_long, capacity)
        target_short = min(target_short, capacity)
    else:
        total = target_long + target_short
        if total <= 0:
            return {"applied": False, "reason": "cycle-seat-snapshot-invalid", "settings": current, "cycleId": cycle_id}
        if total > capacity:
            long_ratio = target_long / total
            target_long = int(round(capacity * long_ratio))
            target_short = capacity - target_long
            clamped = True
        if asymmetric:
            pair = min(target_long, target_short, capacity // 2)
            target_long = pair
            target_short = pair
            clamped = clamped or target_long + target_short != total
        target_max = target_long + target_short

    updated = {
        **current,
        "longSlots": target_long,
        "shortSlots": target_short,
        "maximumPositions": target_max,
    }
    return {
        "applied": True,
        "reason": "clamped-to-current-capacity" if clamped else ("configured-target-restored" if explicit_target else "cycle-start-restored"),
        "settings": updated,
        "cycleId": cycle_id,
        "targetSource": target_source,
        "clamped": clamped,
        "beforeLongSlots": before_long,
        "beforeShortSlots": before_short,
        "beforeMaximumPositions": before_max,
        "targetLongSlots": target_long,
        "targetShortSlots": target_short,
        "targetMaximumPositions": target_max,
    }

def assert_order_allowed(ref: Any, intent: Any, *, client: Any | None = None) -> None:
    """Last-millisecond race guard for stale workers.

    The durable cycle state wins over any worker-local snapshot. Pair-level TP
    remains valid in PORTFOLIO mode and is blocked only when Take Profit is OFF.
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
    if intent_id.startswith("mbb-tp-") and mode == "OFF":
        raise PortfolioCycleOrderBlocked("Take Profit Mode OFF: individuele TP geblokkeerd")
    if action == "OPEN" and mode == "PORTFOLIO" and client is not None:
        current = exchange_equity(client.account_information())
        start = _f(cycle.get("cycleStartEquity"))
        base = _f(cycle.get("baseEquity"), start) or start
        input_mode = _normalize_input_mode(cycle.get("takeProfitInputMode", settings.get("portfolioTpInputMode")))
        value = _f(cycle.get("takeProfitValue"), _f(settings.get("portfolioTpValue"), _f(settings.get("portfolioTpPercent"))))
        target = _f(cycle.get("targetEquity")) or target_equity_v2(base, input_mode, value)
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
                         portfolio_tp_input_mode: str = "PERCENT", portfolio_tp_value: float | None = None,
                         portfolio_tp_base_mode: str = "CYCLE_START", portfolio_tp_custom_base_equity: float = 0.0,
                         config_version: int = 0, current_long_slots: int | None = None,
                         current_short_slots: int | None = None, current_maximum_positions: int | None = None,
                         reset_seats_after_portfolio_tp: bool = False,
                         dry_run: bool = False, order_budget: int | None = None,
                         before_order: Any = None) -> PortfolioGateResult:
    mode = str(take_profit_mode or "PER_TRADE").upper()
    equity = exchange_equity(account)
    cycle, cycle_changed = ensure_cycle(
        raw_state, uid=uid, current_equity=equity, portfolio_tp_percent=portfolio_tp_percent,
        timestamp_ms=timestamp_ms, portfolio_tp_input_mode=portfolio_tp_input_mode,
        portfolio_tp_value=portfolio_tp_value, portfolio_tp_base_mode=portfolio_tp_base_mode,
        portfolio_tp_custom_base_equity=portfolio_tp_custom_base_equity, config_version=config_version,
        current_long_slots=current_long_slots, current_short_slots=current_short_slots,
        current_maximum_positions=current_maximum_positions,
    )
    cycle["updatedAtMs"] = timestamp_ms
    snapshot = portfolio_cycle_snapshot(cycle, mode=mode, current_equity=equity,
                                        portfolio_tp_percent=portfolio_tp_percent)
    if cycle_changed and not dry_run:
        _write_cycle(ref, cycle, reason="Portfolio TP-cycle/basis server-side vastgelegd op echte Aster-equity")

    status = str(cycle.get("cycleStatus") or RUNNING).upper()
    target = _f(cycle.get("targetEquity"))
    if status == RUNNING and mode == "PORTFOLIO":
        latest = ref.get().to_dict() or {}
        latest_settings = latest.get("settings") if isinstance(latest.get("settings"), dict) else {}
        # Only an explicitly persisted mode can overrule this worker snapshot.
        # Legacy state may have no takeProfitMode field at all; in that case the
        # caller's already-normalized mode remains authoritative.
        if "takeProfitMode" in latest_settings:
            latest_mode = str(latest_settings.get("takeProfitMode") or "PER_TRADE").upper()
            if latest_mode != "PORTFOLIO":
                mode = latest_mode
            else:
                portfolio_tp_percent = _f(latest_settings.get("portfolioTpPercent"), portfolio_tp_percent)
                latest_input_mode = _normalize_input_mode(latest_settings.get("portfolioTpInputMode", portfolio_tp_input_mode))
                latest_value = _f(latest_settings.get("portfolioTpValue"), portfolio_tp_percent if latest_input_mode == "PERCENT" else _f(portfolio_tp_value))
                base = _f(cycle.get("baseEquity"), _f(cycle.get("cycleStartEquity")))
                target = target_equity_v2(base, latest_input_mode, latest_value)
                cycle["takeProfitInputMode"] = latest_input_mode
                cycle["takeProfitValue"] = latest_value
                cycle["targetEquity"] = target
    triggered = mode == "PORTFOLIO" and target > 0 and equity >= target
    if status == RUNNING and triggered:
        trigger_state = ref.get().to_dict() or {}
        trigger_settings = trigger_state.get("settings") if isinstance(trigger_state.get("settings"), dict) else {}
        seat_reset_armed = bool(trigger_settings.get("resetSeatsAfterPortfolioTp", reset_seats_after_portfolio_tp))
        reset_target_long, reset_target_short, reset_target_max, reset_target_source = _portfolio_tp_seat_reset_target(cycle, trigger_settings)
        cycle.update({"cycleStatus": PORTFOLIO_TP_EXECUTING,
                      "portfolioTpTriggeredAt": datetime.now(timezone.utc),
                      "portfolioTpTriggeredAtMs": timestamp_ms,
                      "seatResetArmed": seat_reset_armed,
                      "seatResetTargetLongSlots": reset_target_long if seat_reset_armed else None,
                      "seatResetTargetShortSlots": reset_target_short if seat_reset_armed else None,
                      "seatResetTargetMaximumPositions": reset_target_max if seat_reset_armed else None,
                      "seatResetTargetSource": reset_target_source if seat_reset_armed else None,
                      "updatedAtMs": timestamp_ms})
        status = PORTFOLIO_TP_EXECUTING
        snapshot = portfolio_cycle_snapshot(cycle, mode=mode, current_equity=equity,
                                            portfolio_tp_percent=portfolio_tp_percent)
        if not dry_run:
            _write_cycle(ref, cycle, phase=PORTFOLIO_TP_EXECUTING,
                         reason=f"Portfolio TP bereikt op echte Aster-equity {equity:.8f}; volledige exit gestart")
            audit_now = datetime.now(timezone.utc)
            ref.collection("audit").add({"event": "PORTFOLIO_TP_TRIGGERED", "user": uid, "userId": uid,
                "cycleId": cycle.get("cycleId"), "cycleStartEquity": cycle.get("cycleStartEquity"),
                "targetEquity": target, "currentEquity": equity,
                "seatResetArmed": bool(cycle.get("seatResetArmed", False)),
                "cycleStartLongSlots": cycle.get("cycleStartLongSlots"),
                "cycleStartShortSlots": cycle.get("cycleStartShortSlots"),
                "timestamp": audit_now})
            if seat_reset_armed:
                ref.collection("audit").add({
                    "event": "PORTFOLIO_TP_SEAT_RESET_ARMED", "user": uid, "userId": uid,
                    "botId": "aster-strategy-2", "cycleId": cycle.get("cycleId"),
                    "previousLongSlots": _i(trigger_settings.get("longSlots"), _i(current_long_slots)),
                    "previousShortSlots": _i(trigger_settings.get("shortSlots"), _i(current_short_slots)),
                    "targetLongSlots": cycle.get("seatResetTargetLongSlots", cycle.get("cycleStartLongSlots")),
                    "targetShortSlots": cycle.get("seatResetTargetShortSlots", cycle.get("cycleStartShortSlots")),
                    "timestamp": audit_now,
                })

    if status not in ACTIVE_EXIT_STATES:
        return PortfolioGateResult(False, False, snapshot, raw_state, account, positions, open_orders, 0)

    # From this point the portfolio exit is transactional and has absolute
    # priority even if the user changes TP mode while the exit is already live.
    actions: list[dict[str, Any]] = []
    if dry_run:
        actions.append({"kind": "PORTFOLIO_TP_WOULD_EXIT", "positions": len(_position_rows(positions)),
                        "targetEquity": target, "currentEquity": equity,
                        "seatResetArmed": bool(cycle.get("seatResetArmed", reset_seats_after_portfolio_tp)),
                        "cycleStartLongSlots": cycle.get("cycleStartLongSlots"),
                        "cycleStartShortSlots": cycle.get("cycleStartShortSlots"),
                        "seatResetTargetLongSlots": cycle.get("seatResetTargetLongSlots"),
                        "seatResetTargetShortSlots": cycle.get("seatResetTargetShortSlots"),
                        "seatResetTargetSource": cycle.get("seatResetTargetSource")})
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
    if end_equity <= 0:
        # Exchange flat is not enough to start the next cycle: the new baseline
        # must be the actual post-close account equity. If that value is
        # temporarily unavailable, stay in the transactional exit state and
        # retry on the next worker tick instead of persisting a zero/theoretical
        # baseline or letting the target chase a live value.
        wait_ms = int(time.time() * 1000)
        cycle.update({"cycleStatus": FLAT_CONFIRMING, "updatedAtMs": wait_ms})
        _write_cycle(
            ref, cycle, phase=FLAT_CONFIRMING,
            reason="Portfolio TP: exchange is flat, maar werkelijke sluitingsequity is nog niet betrouwbaar beschikbaar; nieuwe cycle wacht",
        )
        report = {
            **portfolio_cycle_snapshot(
                cycle, mode=mode, current_equity=0.0,
                portfolio_tp_percent=portfolio_tp_percent,
            ),
            "actions": actions[-50:],
            "ordersSent": sent,
            "remainingPositions": 0,
            "remainingBotOrders": 0,
            "equityPending": True,
            "autoRestarted": False,
        }
        ref.set({"multiBbReport": report}, merge=True)
        return PortfolioGateResult(
            True, False, report, {**raw_state, "multiBbCycle": cycle},
            final_account, [], remaining_orders, sent,
        )

    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    cycle.update({"cycleStatus": FLAT_CONFIRMED, "cycleEndEquity": end_equity,
                  "flatConfirmedAt": now, "flatConfirmedAtMs": now_ms, "updatedAtMs": now_ms})

    latest_after_close = ref.get().to_dict() or {}
    latest_settings_after_close = latest_after_close.get("settings") if isinstance(latest_after_close.get("settings"), dict) else {}
    seat_reset_armed = bool(cycle.get("seatResetArmed", False))
    seat_reset_report: dict[str, Any] = {
        "armed": seat_reset_armed,
        "applied": False,
        "cycleId": str(cycle.get("cycleId") or ""),
    }
    if seat_reset_armed:
        already_completed = (
            str(cycle.get("slotResetCycleId") or "") == str(cycle.get("cycleId") or "")
            and _i(cycle.get("slotResetCompletedAtMs")) > 0
        )
        if already_completed:
            seat_reset_report.update({
                "applied": True,
                "idempotentReplay": True,
                "targetLongSlots": _i(latest_settings_after_close.get("longSlots")),
                "targetShortSlots": _i(latest_settings_after_close.get("shortSlots")),
                "targetMaximumPositions": _i(latest_settings_after_close.get("maximumPositions")),
            })
        else:
            ref.collection("audit").add({
                "event": "PORTFOLIO_TP_SEAT_RESET_STARTED", "user": uid, "userId": uid,
                "botId": "aster-strategy-2", "cycleId": cycle.get("cycleId"),
                "previousLongSlots": _i(latest_settings_after_close.get("longSlots")),
                "previousShortSlots": _i(latest_settings_after_close.get("shortSlots")),
                "targetLongSlots": cycle.get("seatResetTargetLongSlots", cycle.get("cycleStartLongSlots")),
                "targetShortSlots": cycle.get("seatResetTargetShortSlots", cycle.get("cycleStartShortSlots")),
                "timestamp": now,
            })
            seat_reset_report = portfolio_tp_seat_reset_plan(cycle, latest_settings_after_close)
            seat_reset_report["armed"] = True
            if not seat_reset_report.get("applied"):
                cycle.update({
                    "cycleStatus": FLAT_CONFIRMING,
                    "seatResetError": str(seat_reset_report.get("reason") or "seat-reset-failed"),
                    "updatedAtMs": now_ms,
                })
                _write_cycle(
                    ref, cycle, phase=FLAT_CONFIRMING,
                    reason="Portfolio TP: exchange flat maar stoelreset kon niet veilig worden afgerond; entry-lock blijft actief",
                )
                ref.collection("audit").add({
                    "event": "PORTFOLIO_TP_SEAT_RESET_FAILED", "user": uid, "userId": uid,
                    "botId": "aster-strategy-2", "cycleId": cycle.get("cycleId"),
                    "previousLongSlots": _i(latest_settings_after_close.get("longSlots")),
                    "previousShortSlots": _i(latest_settings_after_close.get("shortSlots")),
                    "targetLongSlots": cycle.get("seatResetTargetLongSlots", cycle.get("cycleStartLongSlots")),
                    "targetShortSlots": cycle.get("seatResetTargetShortSlots", cycle.get("cycleStartShortSlots")),
                    "reason": seat_reset_report.get("reason"), "timestamp": now,
                })
                report = {
                    **portfolio_cycle_snapshot(cycle, mode=mode, current_equity=end_equity,
                                               portfolio_tp_percent=portfolio_tp_percent),
                    "actions": actions[-50:], "ordersSent": sent, "autoRestarted": False,
                    "seatReset": seat_reset_report, "seatResetPending": True,
                }
                ref.set({"multiBbReport": report}, merge=True)
                return PortfolioGateResult(
                    True, False, report, {**raw_state, "multiBbCycle": cycle},
                    final_account, [], remaining_orders, sent,
                )
            latest_settings_after_close = dict(seat_reset_report["settings"])
            cycle.update({
                "slotResetCompletedAt": now,
                "slotResetCompletedAtMs": now_ms,
                "slotResetCycleId": cycle.get("cycleId"),
                "seatResetError": None,
                "updatedAtMs": now_ms,
            })
            actions.append({
                "kind": "PORTFOLIO_TP_SEAT_RESET",
                "fromLongSlots": seat_reset_report.get("beforeLongSlots"),
                "fromShortSlots": seat_reset_report.get("beforeShortSlots"),
                "toLongSlots": seat_reset_report.get("targetLongSlots"),
                "toShortSlots": seat_reset_report.get("targetShortSlots"),
                "clamped": bool(seat_reset_report.get("clamped")),
            })
    else:
        seat_reset_report.update({"reason": "toggle-off"})
        ref.collection("audit").add({
            "event": "PORTFOLIO_TP_SEAT_RESET_SKIPPED", "user": uid, "userId": uid,
            "botId": "aster-strategy-2", "cycleId": cycle.get("cycleId"),
            "previousLongSlots": _i(latest_settings_after_close.get("longSlots")),
            "previousShortSlots": _i(latest_settings_after_close.get("shortSlots")),
            "targetLongSlots": cycle.get("seatResetTargetLongSlots", cycle.get("cycleStartLongSlots")),
            "targetShortSlots": cycle.get("seatResetTargetShortSlots", cycle.get("cycleStartShortSlots")),
            "reason": "toggle-off", "timestamp": now,
        })

    completed_cycle = dict(cycle)
    enabled = bool(latest_after_close.get("enabled", raw_state.get("enabled", False)))
    base_extra = {"multiBbPositions": {}, "multiBbLastCompletedCycle": completed_cycle}
    settings_extra = {"settings": latest_settings_after_close} if seat_reset_armed else {}
    if not enabled:
        if seat_reset_armed:
            _write_cycle(ref, cycle, phase=FLAT_CONFIRMED,
                         reason="Portfolio TP afgerond en exchange flat; bot staat UIT dus geen herstart",
                         extra={**base_extra, "settings": latest_settings_after_close, "monitor": False})
        else:
            _write_cycle(ref, cycle, phase=FLAT_CONFIRMED,
                         reason="Portfolio TP afgerond en exchange flat; bot staat UIT dus geen herstart",
                         extra={**base_extra, "monitor": False})
        if seat_reset_armed and seat_reset_report.get("applied") and not seat_reset_report.get("idempotentReplay"):
            ref.collection("audit").add({
                "event": "PORTFOLIO_TP_SEAT_RESET_COMPLETED", "user": uid, "userId": uid,
                "botId": "aster-strategy-2", "cycleId": completed_cycle.get("cycleId"),
                "previousLongSlots": seat_reset_report.get("beforeLongSlots"),
                "previousShortSlots": seat_reset_report.get("beforeShortSlots"),
                "targetLongSlots": seat_reset_report.get("targetLongSlots"),
                "targetShortSlots": seat_reset_report.get("targetShortSlots"),
                "clamped": bool(seat_reset_report.get("clamped")), "timestamp": now,
            })
        report = {**portfolio_cycle_snapshot(cycle, mode=mode, current_equity=end_equity,
                                             portfolio_tp_percent=portfolio_tp_percent),
                  "actions": actions[-50:], "ordersSent": sent, "autoRestarted": False,
                  "seatReset": seat_reset_report}
        ref.set({"multiBbReport": report}, merge=True)
        return PortfolioGateResult(
            True, False, report,
            {**raw_state, **base_extra, **settings_extra, "multiBbCycle": cycle},
            final_account, [], [], sent,
        )

    restart_ms = max(timestamp_ms + 1, int(time.time() * 1000))
    next_input_mode = _normalize_input_mode(latest_settings_after_close.get("portfolioTpInputMode", cycle.get("takeProfitInputMode") or portfolio_tp_input_mode))
    next_value = _f(latest_settings_after_close.get("portfolioTpValue"), _f(cycle.get("takeProfitValue"), _f(portfolio_tp_value, portfolio_tp_percent)))
    next_percent = _f(latest_settings_after_close.get("portfolioTpPercent"), portfolio_tp_percent)
    next_config_version = _i(latest_settings_after_close.get("version"), config_version)
    normalized_settings = {**latest_settings_after_close, "portfolioTpBaseMode": "CYCLE_START"}
    next_cycle = _new_cycle(
        uid, equity=end_equity, portfolio_tp_percent=next_percent, timestamp_ms=restart_ms,
        portfolio_tp_input_mode=next_input_mode,
        portfolio_tp_value=next_value,
        portfolio_tp_base_mode="CYCLE_START", config_version=next_config_version,
        current_long_slots=_i(normalized_settings.get("longSlots")),
        current_short_slots=_i(normalized_settings.get("shortSlots")),
        current_maximum_positions=_i(normalized_settings.get("maximumPositions")),
    )
    next_cycle["restartStartedAt"] = now
    next_cycle["restartStartedAtMs"] = restart_ms
    _write_cycle(ref, next_cycle, phase=RESTARTING,
                 reason=f"Portfolio TP flat bevestigd; nieuwe cycle start vanaf echte equity {end_equity:.8f}",
                 extra={**base_extra, "multiBbAdoptionPending": False, "settings": normalized_settings})
    ref.collection("audit").add({"event": "PORTFOLIO_TP_FLAT_CONFIRMED", "user": uid,
        "cycleId": completed_cycle.get("cycleId"), "cycleEndEquity": end_equity,
        "nextCycleId": next_cycle.get("cycleId"), "timestamp": now})
    if seat_reset_armed and seat_reset_report.get("applied") and not seat_reset_report.get("idempotentReplay"):
        ref.collection("audit").add({
            "event": "PORTFOLIO_TP_SEAT_RESET_COMPLETED", "user": uid, "userId": uid,
            "botId": "aster-strategy-2", "cycleId": completed_cycle.get("cycleId"),
            "previousLongSlots": seat_reset_report.get("beforeLongSlots"),
            "previousShortSlots": seat_reset_report.get("beforeShortSlots"),
            "targetLongSlots": seat_reset_report.get("targetLongSlots"),
            "targetShortSlots": seat_reset_report.get("targetShortSlots"),
            "clamped": bool(seat_reset_report.get("clamped")), "timestamp": now,
        })
    restart_raw = {**raw_state, **base_extra, "multiBbCycle": next_cycle,
                   "settings": normalized_settings, "multiBbAdoptionPending": False, "phase": RESTARTING}
    report = {**portfolio_cycle_snapshot(next_cycle, mode=mode, current_equity=end_equity,
                                         portfolio_tp_percent=portfolio_tp_percent),
              "actions": actions[-50:], "ordersSent": sent, "autoRestarted": True,
              "previousCycleEndEquity": end_equity, "seatReset": seat_reset_report}
    return PortfolioGateResult(True, True, report, restart_raw, final_account, [], [], sent)
