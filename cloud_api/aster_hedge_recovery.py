"""Pure portfolio hedge-recovery helpers for Aster.

This module contains no network calls and never submits orders.  It is the
single calculation layer shared by live preview, execution validation and unit
tests for the interactive Hedge Dekking flow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import math

from aster_profit_close import position_notional


DEFAULT_TARGET_PERCENT = 80.0
DEFAULT_HEALTHY_MIN_PERCENT = 70.0
DEFAULT_HEALTHY_MAX_PERCENT = 90.0
DEFAULT_MAX_CORRECTION_PERCENT = 10.0
ALLOWED_ACTIONS = {"OPEN_SHORT", "OPEN_LONG", "CLOSE_SHORT", "CLOSE_LONG"}


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def normalize_settings(raw: dict[str, Any] | None) -> dict[str, float]:
    value = raw or {}
    target = _finite(value.get("targetPercent"))
    low = _finite(value.get("healthyMinPercent"))
    high = _finite(value.get("healthyMaxPercent"))
    step = _finite(value.get("maxCorrectionPercent"))
    target = DEFAULT_TARGET_PERCENT if target is None else target
    low = DEFAULT_HEALTHY_MIN_PERCENT if low is None else low
    high = DEFAULT_HEALTHY_MAX_PERCENT if high is None else high
    step = DEFAULT_MAX_CORRECTION_PERCENT if step is None else step
    if not 1 <= target <= 200:
        raise ValueError("Hedge-doel moet tussen 1% en 200% liggen")
    if not 0 <= low <= 200 or not 0 <= high <= 250 or low >= high:
        raise ValueError("Hedge-doelzone is ongeldig")
    if not low <= target <= high:
        raise ValueError("Hedge-doel moet binnen de ingestelde doelzone liggen")
    if not 1 <= step <= 100:
        raise ValueError("Maximale correctie per stap moet tussen 1% en 100% liggen")
    return {
        "targetPercent": round(target, 6),
        "healthyMinPercent": round(low, 6),
        "healthyMaxPercent": round(high, 6),
        "maxCorrectionPercent": round(step, 6),
    }


def position_side(row: dict[str, Any]) -> str | None:
    side = str(row.get("positionSide") or row.get("side") or "").upper().strip()
    if side in {"LONG", "SHORT"}:
        return side
    amount = _finite(row.get("positionAmt"))
    if side in {"", "BOTH"} and amount:
        return "LONG" if amount > 0 else "SHORT"
    return None


def position_quantity(row: dict[str, Any]) -> float:
    for key in ("quantity", "positionAmt"):
        value = _finite(row.get(key))
        if value is not None:
            return abs(value)
    return 0.0


def hedge_status(coverage: float | None, settings: dict[str, float], long_exposure: float, short_exposure: float) -> str:
    if coverage is None:
        return "above_target" if long_exposure <= 0 < short_exposure else "unavailable"
    if coverage < settings["healthyMinPercent"]:
        return "below_target"
    if coverage > settings["healthyMaxPercent"]:
        return "above_target"
    return "within_target"


def exposure_values(long_exposure: float, short_exposure: float, settings: dict[str, float], *,
                    reliable: bool = True, open_position_count: int = 0,
                    long_position_count: int = 0, short_position_count: int = 0,
                    invalid_open_count: int = 0) -> dict[str, Any]:
    long_value = max(0.0, float(long_exposure))
    short_value = max(0.0, float(short_exposure))
    net = long_value - short_value
    coverage = (short_value / long_value * 100.0) if long_value > 0 else None
    net_side = "FLAT" if abs(net) < 1e-9 else ("LONG" if net > 0 else "SHORT")
    return {
        "reliable": bool(reliable),
        "longExposureUsd": round(long_value, 8),
        "shortExposureUsd": round(short_value, 8),
        "netExposureUsd": round(net, 8),
        "netSide": net_side,
        "hedgeCoveragePercent": round(coverage, 6) if coverage is not None else None,
        "status": hedge_status(coverage, settings, long_value, short_value),
        "openPositionCount": int(open_position_count),
        "longPositionCount": int(long_position_count),
        "shortPositionCount": int(short_position_count),
        "invalidOpenCount": int(invalid_open_count),
    }


def portfolio_exposure(rows: Iterable[dict[str, Any]], settings: dict[str, float]) -> dict[str, Any]:
    long_exposure = short_exposure = 0.0
    open_count = long_count = short_count = invalid = 0
    for row in rows:
        if position_quantity(row) <= 0:
            continue
        open_count += 1
        side = position_side(row)
        notional = position_notional(row)
        if side not in {"LONG", "SHORT"} or notional is None or notional <= 0:
            invalid += 1
            continue
        if side == "LONG":
            long_exposure += notional
            long_count += 1
        else:
            short_exposure += notional
            short_count += 1
    return exposure_values(long_exposure, short_exposure, settings,
        reliable=invalid == 0, open_position_count=open_count,
        long_position_count=long_count, short_position_count=short_count,
        invalid_open_count=invalid)


_ORIGINAL_MARGIN_KEYS = (
    "startMarginUsd", "startMargin", "originalMarginUsd", "originalMargin",
    "initialStartMarginUsd", "initialStartMargin", "entryMarginUsd",
)


def explicit_original_start_margin(row: dict[str, Any]) -> float | None:
    """Read only explicit original-seat margin fields; never infer from DCA-expanded notional."""
    for key in _ORIGINAL_MARGIN_KEYS:
        value = _finite(row.get(key))
        if value is not None and value > 0:
            return value
    return None


def average_start_margin(rows: Iterable[dict[str, Any]], side: str, fallback_margin: float) -> dict[str, Any]:
    normalized = str(side).upper().strip()
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("Zijde moet LONG of SHORT zijn")
    margins = [explicit_original_start_margin(row) for row in rows if position_side(row) == normalized and position_quantity(row) > 0]
    proven = [value for value in margins if value is not None and value > 0]
    if proven:
        average = sum(proven) / len(proven)
        return {"marginUsd": round(average, 8), "source": "same_side_original_average", "sampleCount": len(proven)}
    fallback = _finite(fallback_margin)
    if fallback is None or fallback <= 0:
        raise ValueError(f"Geen betrouwbare {normalized} startmargin beschikbaar")
    return {"marginUsd": round(fallback, 8), "source": "configured_same_side_fallback", "sampleCount": 0}


def strategy_fallback_start_margin(raw: dict[str, Any] | None, side: str) -> float:
    value = raw or {}
    normalized = str(side).upper().strip()
    side_prefix = "long" if normalized == "LONG" else "short"
    for key in (f"{side_prefix}StartMargin", f"{side_prefix}StartMarginUsd", "startMargin", "startMarginUsd"):
        candidate = _finite(value.get(key))
        if candidate is not None and candidate > 0:
            return candidate
    base_notional = _finite(value.get("baseNotional")) or 0.0
    leverage = _finite(value.get("leverage")) or 0.0
    if base_notional > 0 and leverage > 0:
        return base_notional / leverage
    # Focus simple-mode stores amounts as margin only when explicitly flagged.
    if bool(value.get("focusV2AmountsAreMargin")):
        candidate = _finite(value.get("focusStartOrderNotional"))
        if candidate is not None and candidate > 0:
            return candidate
    raise ValueError(f"Geen veilige geconfigureerde {normalized} startmargin gevonden")


def recommended_actions(status: str) -> dict[str, str | None]:
    if status == "below_target":
        return {"recommended": "OPEN_SHORT", "alternative": "CLOSE_LONG"}
    if status == "above_target":
        return {"recommended": "CLOSE_SHORT", "alternative": "OPEN_LONG"}
    return {"recommended": None, "alternative": None}


def step_target_percent(coverage: float | None, settings: dict[str, float]) -> float | None:
    if coverage is None:
        return None
    target = settings["targetPercent"]
    step = settings["maxCorrectionPercent"]
    if coverage < target:
        return min(target, coverage + step)
    if coverage > target:
        return max(target, coverage - step)
    return target


def apply_notional_impact(before: dict[str, Any], action: str, planned_notional_usd: float,
                         settings: dict[str, float], *, seat_count: int = 0) -> dict[str, Any]:
    normalized = str(action).upper().strip()
    if normalized not in ALLOWED_ACTIONS:
        raise ValueError("Onbekende hedge-herstelactie")
    amount = max(0.0, float(planned_notional_usd))
    long_value = float(before["longExposureUsd"])
    short_value = float(before["shortExposureUsd"])
    long_count = int(before.get("longPositionCount", 0))
    short_count = int(before.get("shortPositionCount", 0))
    if normalized == "OPEN_LONG":
        long_value += amount; long_count += seat_count
    elif normalized == "OPEN_SHORT":
        short_value += amount; short_count += seat_count
    elif normalized == "CLOSE_LONG":
        long_value = max(0.0, long_value - amount); long_count = max(0, long_count - seat_count)
    elif normalized == "CLOSE_SHORT":
        short_value = max(0.0, short_value - amount); short_count = max(0, short_count - seat_count)
    return exposure_values(long_value, short_value, settings,
        reliable=bool(before.get("reliable", True)), open_position_count=long_count + short_count,
        long_position_count=long_count, short_position_count=short_count,
        invalid_open_count=int(before.get("invalidOpenCount", 0)))


def validate_recovery_direction(before_status: str, action: str) -> None:
    normalized = str(action).upper().strip()
    allowed = recommended_actions(before_status)
    if normalized not in {allowed["recommended"], allowed["alternative"]}:
        if before_status == "within_target":
            raise ValueError("Hedge ligt binnen de doelzone; herstelactie is niet nodig")
        raise ValueError("Deze actie beweegt niet in de herstelrichting voor de actuele hedge-status")


def ranked_close_candidates(rows: Iterable[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    normalized = str(side).upper().strip()
    result: list[dict[str, Any]] = []
    for row in rows:
        if position_side(row) != normalized or position_quantity(row) <= 0:
            continue
        notional = position_notional(row)
        if notional is None or notional <= 0:
            continue
        pnl = _finite(row.get("unRealizedProfit"))
        if pnl is None:
            pnl = _finite(row.get("unrealizedPnl"))
        result.append({
            "symbol": str(row.get("symbol", "")).upper(),
            "side": normalized,
            "quantity": position_quantity(row),
            "notionalUsd": round(notional, 8),
            "unrealizedPnlUsd": round(pnl or 0.0, 8),
        })
    # Prefer profitable legs, then smaller notional for a gentler correction.
    result.sort(key=lambda item: (-item["unrealizedPnlUsd"], item["notionalUsd"], item["symbol"]))
    return result
