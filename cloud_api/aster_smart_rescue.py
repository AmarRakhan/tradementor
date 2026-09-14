from __future__ import annotations

"""Pure Smart Rescue DCA math and persistent state transitions.

The actual Aster order submission remains in ``aster_multi_bb.py`` so the
existing canonical execution, leverage-tier and portfolio guards remain the
only live order path.  This module deliberately contains no exchange I/O.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation, getcontext
import math
from typing import Any

getcontext().prec = 64

SMART_RESCUE_VERSION = 1
MAX_DCA_COUNT = 500
MAX_DISPLAY_USD = Decimal("1000000000000000")

DEFAULT_RESCUE_RANGE_PERCENT = 10.0
DEFAULT_DCA_COUNT = 10
DEFAULT_ORDER_GROWTH_MULTIPLIER = 1.35
DEFAULT_TRAILING_RECOVERY_PERCENT = 0.30


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)
    return out if out.is_finite() else Decimal(default)


def validate_config(*, rescue_range_percent: float, dca_count: int,
                    order_growth_multiplier: float,
                    trailing_recovery_percent: float) -> None:
    if not math.isfinite(rescue_range_percent) or not 0 < rescue_range_percent < 100:
        raise ValueError("Smart Rescue bereik moet groter dan 0% en kleiner dan 100% zijn")
    if not 1 <= int(dca_count) <= MAX_DCA_COUNT:
        raise ValueError(f"Smart Rescue aantal DCA's moet tussen 1 en {MAX_DCA_COUNT} liggen")
    if not math.isfinite(order_growth_multiplier) or order_growth_multiplier < 1:
        raise ValueError("Smart Rescue ordergroei moet minimaal 1,00x zijn")
    if not math.isfinite(trailing_recovery_percent) or not 0 <= trailing_recovery_percent < 100:
        raise ValueError("Smart Rescue herstelpercentage moet tussen 0% en 100% liggen")


def level_drop_percent(rescue_range_percent: float, index: int, dca_count: int) -> float:
    """Progressive level curve; final level is forced exactly to the range."""
    if index < 1 or index > dca_count:
        raise ValueError("Smart Rescue level-index ligt buiten de ladder")
    if index == dca_count:
        return float(rescue_range_percent)
    return float(rescue_range_percent) * math.pow(index / dca_count, 1.5)


def order_margin_decimal(start_margin_usd: Any, multiplier: Any, index: int) -> Decimal:
    """Geometric DCA amount without float overflow."""
    start = _decimal(start_margin_usd)
    growth = _decimal(multiplier, "1")
    if start <= 0 or growth < 1 or index < 1:
        raise ValueError("Ongeldige Smart Rescue orderberekening")
    return start * (growth ** int(index))


def display_number(value: Decimal) -> tuple[float, bool]:
    """Return a finite UI number plus a flag when the exact value was capped."""
    if value.copy_abs() > MAX_DISPLAY_USD:
        return float(MAX_DISPLAY_USD.copy_sign(value)), True
    return float(value), False


def build_levels(*, initial_entry_price: float, rescue_range_percent: float,
                 dca_count: int, start_margin_usd: float,
                 order_growth_multiplier: float) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    for index in range(1, dca_count + 1):
        drop = level_drop_percent(rescue_range_percent, index, dca_count)
        trigger = initial_entry_price * (1 - drop / 100.0)
        exact_margin = order_margin_decimal(start_margin_usd, order_growth_multiplier, index)
        margin, capped = display_number(exact_margin)
        levels.append({
            "index": index,
            "dropPercent": drop,
            "triggerPrice": trigger,
            "orderMarginUsd": margin,
            "orderMarginExact": format(exact_margin, "f") if capped else None,
            "amountDisplayCapped": capped,
            "status": "PENDING",
        })
    return levels


def build_position_state(*, initial_entry_price: float, start_margin_usd: float,
                         rescue_range_percent: float, dca_count: int,
                         order_growth_multiplier: float,
                         trailing_recovery_percent: float,
                         config_version: int) -> dict[str, Any]:
    validate_config(
        rescue_range_percent=rescue_range_percent,
        dca_count=dca_count,
        order_growth_multiplier=order_growth_multiplier,
        trailing_recovery_percent=trailing_recovery_percent,
    )
    if not math.isfinite(initial_entry_price) or initial_entry_price <= 0:
        raise ValueError("Smart Rescue initial entry moet positief zijn")
    if not math.isfinite(start_margin_usd) or start_margin_usd <= 0:
        raise ValueError("Smart Rescue startmargin moet positief zijn")
    return {
        "version": SMART_RESCUE_VERSION,
        "configVersion": int(config_version),
        "initialEntryPrice": float(initial_entry_price),
        "startMarginUsd": float(start_margin_usd),
        "rescueRangePercent": float(rescue_range_percent),
        "dcaCountConfigured": int(dca_count),
        "orderGrowthMultiplier": float(order_growth_multiplier),
        "trailingRecoveryPercent": float(trailing_recovery_percent),
        "levels": build_levels(
            initial_entry_price=float(initial_entry_price),
            rescue_range_percent=float(rescue_range_percent),
            dca_count=int(dca_count),
            start_margin_usd=float(start_margin_usd),
            order_growth_multiplier=float(order_growth_multiplier),
        ),
        "armedIndex": None,
        "localLow": None,
        "recoveryTriggerPrice": None,
        "filledCount": 0,
        "skippedCount": 0,
        "cumulativeActualMarginUsd": float(start_margin_usd),
        "lastDecision": "IDLE",
    }


def _level_map(state: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(row.get("index", 0)): row for row in state.get("levels", []) if isinstance(row, dict) and int(row.get("index", 0)) > 0}


def advance_state(raw_state: dict[str, Any], *, mark_price: float) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Advance ARMED/local-low state and return at most one executable rescue.

    Deepest eligible level wins.  Crossing deeper levels before a recovery turns
    shallower unfilled levels into SKIPPED and moves the single ARMED pointer.
    """
    state = deepcopy(raw_state)
    if not math.isfinite(mark_price) or mark_price <= 0:
        return state, None
    levels = state.get("levels") if isinstance(state.get("levels"), list) else []
    level_by_index = _level_map(state)
    if not levels:
        return state, None

    armed_index = int(state.get("armedIndex") or 0)
    pending_crossed = [
        int(row.get("index", 0)) for row in levels
        if str(row.get("status", "PENDING")) == "PENDING"
        and mark_price <= _finite(row.get("triggerPrice"), -1)
    ]
    deepest = max(pending_crossed, default=0)

    if deepest > armed_index:
        if armed_index and armed_index in level_by_index and level_by_index[armed_index].get("status") == "ARMED":
            level_by_index[armed_index]["status"] = "SKIPPED"
        for index in pending_crossed:
            if index < deepest and index in level_by_index:
                level_by_index[index]["status"] = "SKIPPED"
        if deepest in level_by_index:
            level_by_index[deepest]["status"] = "ARMED"
        state["armedIndex"] = deepest
        state["localLow"] = mark_price
        state["lastDecision"] = f"ARMED_{deepest}"
        armed_index = deepest

    if armed_index <= 0 or armed_index not in level_by_index:
        state["skippedCount"] = sum(1 for row in levels if row.get("status") == "SKIPPED")
        return state, None

    armed = level_by_index[armed_index]
    if armed.get("status") != "ARMED":
        state["armedIndex"] = None
        state["localLow"] = None
        state["recoveryTriggerPrice"] = None
        return state, None

    local_low = _finite(state.get("localLow"), mark_price)
    local_low = min(local_low if local_low > 0 else mark_price, mark_price)
    state["localLow"] = local_low
    recovery_percent = max(0.0, _finite(state.get("trailingRecoveryPercent")))
    recovery_trigger = local_low * (1 + recovery_percent / 100.0)
    state["recoveryTriggerPrice"] = recovery_trigger
    state["skippedCount"] = sum(1 for row in levels if row.get("status") == "SKIPPED")

    if mark_price + max(1e-12, mark_price * 1e-12) < recovery_trigger:
        state["lastDecision"] = f"TRAILING_{armed_index}"
        return state, None

    state["lastDecision"] = f"RECOVERY_READY_{armed_index}"
    return state, {
        "levelIndex": armed_index,
        "triggerPrice": _finite(armed.get("triggerPrice")),
        "localLow": local_low,
        "recoveryTriggerPrice": recovery_trigger,
        "orderMarginUsd": _finite(armed.get("orderMarginUsd")),
        "orderMarginExact": armed.get("orderMarginExact"),
        "amountDisplayCapped": bool(armed.get("amountDisplayCapped")),
    }


def apply_fill(raw_state: dict[str, Any], *, level_index: int, fill_price: float,
               fill_qty: float, actual_margin_usd: float, order_id: str | None,
               timestamp_ms: int) -> dict[str, Any]:
    state = deepcopy(raw_state)
    levels = state.get("levels") if isinstance(state.get("levels"), list) else []
    for row in levels:
        if int(row.get("index", 0)) == int(level_index):
            row.update({
                "status": "FILLED",
                "actualFillPrice": float(fill_price),
                "actualFillQty": float(fill_qty),
                "actualMarginUsd": float(actual_margin_usd),
                "fillId": order_id,
                "filledAtMs": int(timestamp_ms),
            })
            break
    state["armedIndex"] = None
    state["localLow"] = None
    state["recoveryTriggerPrice"] = None
    state["filledCount"] = sum(1 for row in levels if row.get("status") == "FILLED")
    state["skippedCount"] = sum(1 for row in levels if row.get("status") == "SKIPPED")
    state["cumulativeActualMarginUsd"] = max(0.0, _finite(state.get("cumulativeActualMarginUsd"))) + max(0.0, float(actual_margin_usd))
    state["lastFillIndex"] = int(level_index)
    state["lastFillPrice"] = float(fill_price)
    state["lastFillQty"] = float(fill_qty)
    state["lastFillId"] = order_id
    state["lastDecision"] = f"FILLED_{level_index}"
    state["updatedAtMs"] = int(timestamp_ms)
    return state


def apply_failure(raw_state: dict[str, Any], *, level_index: int, reason: str,
                  timestamp_ms: int, terminal: bool = False) -> dict[str, Any]:
    state = deepcopy(raw_state)
    if terminal:
        for row in state.get("levels", []):
            if isinstance(row, dict) and int(row.get("index", 0)) == int(level_index):
                row["status"] = "FAILED"
                break
        state["armedIndex"] = None
        state["localLow"] = None
        state["recoveryTriggerPrice"] = None
    state["lastFailureIndex"] = int(level_index)
    state["lastFailureReason"] = str(reason)[:500]
    state["lastFailureAtMs"] = int(timestamp_ms)
    state["lastDecision"] = f"FAILED_{level_index}" if terminal else f"RETRY_{level_index}"
    return state


def preview_ladder(*, initial_entry_price: float, start_margin_usd: float,
                   leverage: float, rescue_range_percent: float, dca_count: int,
                   order_growth_multiplier: float) -> dict[str, Any]:
    """Deterministic trigger-fill preview used by tests/API/UI parity checks."""
    levels = build_levels(
        initial_entry_price=initial_entry_price,
        rescue_range_percent=rescue_range_percent,
        dca_count=dca_count,
        start_margin_usd=start_margin_usd,
        order_growth_multiplier=order_growth_multiplier,
    )
    leverage_d = _decimal(leverage, "1")
    start_margin_d = _decimal(start_margin_usd)
    entry_d = _decimal(initial_entry_price)
    total_margin = start_margin_d
    total_notional = start_margin_d * leverage_d
    total_qty = total_notional / entry_d
    rows: list[dict[str, Any]] = []
    capped_any = False
    for level in levels:
        price_d = _decimal(level["triggerPrice"])
        margin_d = order_margin_decimal(start_margin_usd, order_growth_multiplier, int(level["index"]))
        notional_d = margin_d * leverage_d
        qty_d = notional_d / price_d
        total_margin += margin_d
        total_notional += notional_d
        total_qty += qty_d
        avg_d = total_notional / total_qty
        pnl_d = total_qty * (price_d - avg_d)
        recovery_d = (avg_d / price_d - Decimal(1)) * Decimal(100)
        margin_v, margin_cap = display_number(margin_d)
        total_margin_v, total_margin_cap = display_number(total_margin)
        total_notional_v, total_notional_cap = display_number(total_notional)
        capped_any = capped_any or margin_cap or total_margin_cap or total_notional_cap
        rows.append({
            **level,
            "orderMarginUsd": margin_v,
            "cumulativeMarginUsd": total_margin_v,
            "cumulativeNotionalUsd": total_notional_v,
            "averageEntryPrice": float(avg_d),
            "unrealizedPnlUsd": float(pnl_d) if abs(pnl_d) <= MAX_DISPLAY_USD else float(MAX_DISPLAY_USD.copy_sign(pnl_d)),
            "breakEvenPrice": float(avg_d),
            "recoveryToBreakEvenPercent": float(recovery_d),
            "displayCapped": margin_cap or total_margin_cap or total_notional_cap,
        })
    max_margin_v, max_margin_cap = display_number(total_margin)
    deepest = rows[-1] if rows else None
    return {
        "rows": rows,
        "maxMarginUsd": max_margin_v,
        "maxMarginExact": format(total_margin, "f") if max_margin_cap else None,
        "displayCapped": capped_any or max_margin_cap,
        "finalBreakEvenPrice": deepest.get("breakEvenPrice") if deepest else initial_entry_price,
        "finalRecoveryToBreakEvenPercent": deepest.get("recoveryToBreakEvenPercent") if deepest else 0.0,
    }
