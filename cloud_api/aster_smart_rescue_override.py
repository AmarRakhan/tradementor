from __future__ import annotations

"""Safe active-cycle extensions for Smart Rescue.

This module is deliberately exchange-I/O free. It only appends future levels to
an already persisted Smart Rescue snapshot. Historical levels are never rebuilt.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation, getcontext
import math
from typing import Any

getcontext().prec = 64
MAX_DCA_COUNT = 500
MAX_HISTORY = 20


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _d(value: Any, default: str = "0") -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)
    return out if out.is_finite() else Decimal(default)


def _levels(smart: dict[str, Any]) -> list[dict[str, Any]]:
    return [deepcopy(row) for row in smart.get("levels", []) if isinstance(row, dict) and _i(row.get("index")) > 0]


def _current_total(smart: dict[str, Any], levels: list[dict[str, Any]]) -> int:
    return max(_i(smart.get("dcaCountConfigured")), max((_i(row.get("index")) for row in levels), default=0))


def _deepest_drop(smart: dict[str, Any], levels: list[dict[str, Any]]) -> float:
    return max(_f(smart.get("rescueRangePercent")), max((_f(row.get("dropPercent")) for row in levels), default=0.0))


def _last_margin(smart: dict[str, Any], levels: list[dict[str, Any]]) -> Decimal:
    if levels:
        value = _d(levels[-1].get("orderMarginUsd"))
        if value > 0:
            return value
    start = _d(smart.get("startMarginUsd"))
    growth = _d(smart.get("orderGrowthMultiplier"), "1")
    total = _current_total(smart, levels)
    if start <= 0 or growth < 1:
        raise ValueError("Bestaande Smart Rescue ordergrootte is ongeldig")
    return start * (growth ** total)


def extend_future_levels(
    smart_state: dict[str, Any], *, new_total_dca: int, new_rescue_range_percent: float,
    future_growth_multiplier: float, timestamp_ms: int,
) -> dict[str, Any]:
    """Append future levels while preserving every existing level byte-for-byte.

    The existing ladder, including FILLED/SKIPPED/ARMED states and fill metadata,
    remains untouched. New levels continue from the previous deepest configured
    drop and stay anchored to the cycle's original ``initialEntryPrice``.
    """
    smart = deepcopy(smart_state)
    levels = _levels(smart)
    old_total = _current_total(smart, levels)
    old_range = _deepest_drop(smart, levels)
    total = _i(new_total_dca)
    target_range = _f(new_rescue_range_percent)
    growth = _f(future_growth_multiplier)
    entry = _f(smart.get("initialEntryPrice"))

    if old_total < 1 or not levels:
        raise ValueError("Actieve Smart Rescue-ladder ontbreekt of is onvolledig")
    if not old_total < total <= MAX_DCA_COUNT:
        raise ValueError(f"Nieuw totaal DCA's moet groter zijn dan {old_total} en maximaal {MAX_DCA_COUNT}")
    if not math.isfinite(target_range) or not old_range < target_range < 100:
        raise ValueError(f"Nieuw rescue bereik moet dieper zijn dan de huidige {old_range:.2f}% en kleiner dan 100%")
    if not math.isfinite(growth) or growth < 1:
        raise ValueError("Ordergroei vanaf volgende stap moet minimaal 1,00x zijn")
    if entry <= 0:
        raise ValueError("Oorspronkelijke Smart Rescue-entry ontbreekt")

    extra = total - old_total
    last_margin = _last_margin(smart, levels)
    growth_d = _d(growth, "1")
    appended: list[dict[str, Any]] = []
    for offset in range(1, extra + 1):
        fraction = offset / extra
        drop = target_range if offset == extra else old_range + (target_range - old_range) * math.pow(fraction, 1.5)
        exact_margin = last_margin * (growth_d ** offset)
        margin = float(exact_margin)
        if not math.isfinite(margin):
            raise ValueError("Nieuwe Smart Rescue ordergrootte wordt te groot om betrouwbaar uit te voeren")
        appended.append({
            "index": old_total + offset,
            "dropPercent": float(drop),
            "triggerPrice": entry * (1 - float(drop) / 100.0),
            "orderMarginUsd": margin,
            "orderMarginExact": None,
            "amountDisplayCapped": False,
            "status": "PENDING",
            "extensionVersion": _i(smart.get("extensionVersion")) + 1,
        })

    # Preserve old objects exactly; only append new future definitions.
    smart["levels"] = levels + appended
    smart["dcaCountConfigured"] = total
    smart["rescueRangePercent"] = target_range
    smart["futureOrderGrowthMultiplier"] = growth
    smart["extensionVersion"] = _i(smart.get("extensionVersion")) + 1
    smart["lastExtensionAtMs"] = int(timestamp_ms)
    history = [deepcopy(row) for row in smart.get("extensionHistory", []) if isinstance(row, dict)]
    history.append({
        "version": smart["extensionVersion"],
        "timestampMs": int(timestamp_ms),
        "fromTotalDca": old_total,
        "toTotalDca": total,
        "fromRangePercent": old_range,
        "toRangePercent": target_range,
        "futureGrowthMultiplier": growth,
        "addedSteps": extra,
    })
    smart["extensionHistory"] = history[-MAX_HISTORY:]
    return smart


def active_cycle_summary(*, smart_state: dict[str, Any], outer_state: dict[str, Any], position: dict[str, Any]) -> dict[str, Any]:
    smart = deepcopy(smart_state)
    levels = _levels(smart)
    total = _current_total(smart, levels)
    filled = sum(1 for row in levels if str(row.get("status")) == "FILLED")
    skipped = sum(1 for row in levels if str(row.get("status")) == "SKIPPED")
    remaining = sum(1 for row in levels if str(row.get("status")) in {"PENDING", "ARMED"})
    entry = _f(position.get("entryPrice"), _f(outer_state.get("lastKnownEntry")))
    mark = _f(position.get("markPrice"), entry)
    qty = abs(_f(position.get("positionAmt"), _f(outer_state.get("lastKnownQty"))))
    leverage = max(1, _i(position.get("leverage"), _i(outer_state.get("leverage"), 1)))
    break_even_now = (entry / mark - 1) * 100 if entry > 0 and mark > 0 else 0.0
    actual_margin = max(0.0, _f(smart.get("cumulativeActualMarginUsd"), _f(smart.get("startMarginUsd"))))
    future_margin = sum(max(0.0, _f(row.get("orderMarginUsd"))) for row in levels if str(row.get("status")) in {"PENDING", "ARMED"})
    return {
        "cycleId": str(outer_state.get("cycleId") or ""),
        "dcaTotal": total,
        "rescueRangePercent": _deepest_drop(smart, levels),
        "filledCount": filled,
        "skippedCount": skipped,
        "remainingCount": remaining,
        "breakEvenNowPercent": break_even_now,
        "maxAllocationUsd": actual_margin + future_margin,
        "actualMarginUsd": actual_margin,
        "futurePlannedMarginUsd": future_margin,
        "orderGrowthMultiplier": _f(smart.get("futureOrderGrowthMultiplier"), _f(smart.get("orderGrowthMultiplier"), 1.0)),
        "extensionVersion": _i(smart.get("extensionVersion")),
        "position": {"entryPrice": entry, "markPrice": mark, "quantity": qty, "leverage": leverage},
        "levels": levels,
    }


def extension_preview(*, smart_state: dict[str, Any], outer_state: dict[str, Any], position: dict[str, Any],
                      new_total_dca: int, new_rescue_range_percent: float, future_growth_multiplier: float,
                      timestamp_ms: int = 0) -> dict[str, Any]:
    extended = extend_future_levels(smart_state, new_total_dca=new_total_dca,
        new_rescue_range_percent=new_rescue_range_percent, future_growth_multiplier=future_growth_multiplier,
        timestamp_ms=timestamp_ms)
    summary = active_cycle_summary(smart_state=extended, outer_state=outer_state, position=position)
    pos = summary["position"]
    qty = max(0.0, _f(pos.get("quantity")))
    avg = _f(pos.get("entryPrice"))
    leverage = max(1, _i(pos.get("leverage"), 1))
    total_notional = qty * avg
    rows = []
    for row in summary["levels"]:
        if str(row.get("status")) not in {"PENDING", "ARMED"}:
            continue
        trigger = _f(row.get("triggerPrice")); margin = _f(row.get("orderMarginUsd"))
        if trigger <= 0 or margin <= 0:
            continue
        add_notional = margin * leverage
        add_qty = add_notional / trigger
        total_notional += add_notional; qty += add_qty
        avg = total_notional / qty if qty > 0 else avg
        rows.append({
            "index": _i(row.get("index")), "dropPercent": _f(row.get("dropPercent")),
            "triggerPrice": trigger, "orderMarginUsd": margin,
            "averageEntryPrice": avg,
            "breakEvenPrice": avg,
            "recoveryToBreakEvenPercent": (avg / trigger - 1) * 100,
            "new": _i(row.get("index")) > _current_total(smart_state, _levels(smart_state)),
        })
    deepest = rows[-1] if rows else None
    return {**summary, "previewRows": rows,
        "finalBreakEvenPrice": deepest.get("breakEvenPrice") if deepest else avg,
        "finalRecoveryToBreakEvenPercent": deepest.get("recoveryToBreakEvenPercent") if deepest else 0.0,
        "lastNewDcaDropPercent": _f(new_rescue_range_percent)}
