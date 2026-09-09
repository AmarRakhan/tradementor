"""Pure selection and hedge-exposure helpers for explicitly confirmed Aster profit closes."""
from __future__ import annotations

from typing import Any, Iterable


MINIMUM_PROFIT_USD = 0.50
HEDGE_TARGET_PERCENT = 80.0
HEDGE_HEALTHY_MIN_PERCENT = 70.0
HEDGE_HEALTHY_MAX_PERCENT = 90.0


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def position_profit(row: dict[str, Any]) -> float | None:
    for key in ("unRealizedProfit", "unrealizedPnl", "unrealizedProfit"):
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _position_side(row: dict[str, Any]) -> str | None:
    side = str(row.get("side") or row.get("positionSide") or "").upper().strip()
    if side in {"LONG", "SHORT"}:
        return side
    amount = _number(row.get("positionAmt"))
    if side in {"", "BOTH"} and amount:
        return "LONG" if amount > 0 else "SHORT"
    return None


def _position_quantity(row: dict[str, Any]) -> float:
    value = _number(row.get("quantity"))
    if value is None:
        value = _number(row.get("positionAmt"))
    return abs(value or 0.0)


def position_notional(row: dict[str, Any]) -> float | None:
    """Return absolute live mark notional for an open position without inventing prices."""
    quantity = _position_quantity(row)
    if quantity <= 0:
        return 0.0
    mark = _number(row.get("markPrice"))
    if mark is not None and mark > 0:
        return quantity * mark
    direct = _number(row.get("notional"))
    if direct is not None and direct != 0:
        return abs(direct)
    return None


def _hedge_status(coverage: float | None, long_exposure: float, short_exposure: float) -> str:
    if coverage is None:
        if long_exposure <= 0 and short_exposure > 0:
            return "above_target"
        return "unavailable"
    if coverage < HEDGE_HEALTHY_MIN_PERCENT:
        return "below_target"
    if coverage > HEDGE_HEALTHY_MAX_PERCENT:
        return "above_target"
    return "within_target"


def _exposure_values(
    long_exposure: float,
    short_exposure: float,
    *,
    reliable: bool = True,
    open_position_count: int = 0,
    invalid_open_count: int = 0,
) -> dict[str, Any]:
    long_value = max(0.0, float(long_exposure))
    short_value = max(0.0, float(short_exposure))
    net = long_value - short_value
    coverage = (short_value / long_value * 100.0) if long_value > 0 else None
    if abs(net) < 1e-9:
        net_side = "FLAT"
    else:
        net_side = "LONG" if net > 0 else "SHORT"
    return {
        "reliable": bool(reliable),
        "longExposureUsd": round(long_value, 8),
        "shortExposureUsd": round(short_value, 8),
        "netExposureUsd": round(net, 8),
        "netSide": net_side,
        "hedgeCoveragePercent": round(coverage, 6) if coverage is not None else None,
        "status": _hedge_status(coverage, long_value, short_value),
        "openPositionCount": int(open_position_count),
        "invalidOpenCount": int(invalid_open_count),
    }


def portfolio_exposure(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Canonical live LONG/SHORT mark-notional exposure from Aster position-risk rows."""
    long_exposure = 0.0
    short_exposure = 0.0
    open_count = 0
    invalid_open_count = 0
    for row in rows:
        quantity = _position_quantity(row)
        if quantity <= 0:
            continue
        open_count += 1
        side = _position_side(row)
        notional = position_notional(row)
        if side not in {"LONG", "SHORT"} or notional is None or notional <= 0:
            invalid_open_count += 1
            continue
        if side == "LONG":
            long_exposure += notional
        else:
            short_exposure += notional
    return _exposure_values(
        long_exposure,
        short_exposure,
        reliable=invalid_open_count == 0,
        open_position_count=open_count,
        invalid_open_count=invalid_open_count,
    )


def _close_impact(rows: list[dict[str, Any]], selected: list[dict[str, Any]]) -> dict[str, Any]:
    before = portfolio_exposure(rows)
    removed_long = 0.0
    removed_short = 0.0
    for row in selected:
        side = _position_side(row)
        notional = position_notional(row)
        if notional is None or notional <= 0:
            continue
        if side == "LONG":
            removed_long += notional
        elif side == "SHORT":
            removed_short += notional

    after = _exposure_values(
        max(0.0, before["longExposureUsd"] - removed_long),
        max(0.0, before["shortExposureUsd"] - removed_short),
        reliable=before["reliable"],
        open_position_count=max(0, before["openPositionCount"] - len(selected)),
        invalid_open_count=before["invalidOpenCount"],
    )

    before_coverage = before["hedgeCoveragePercent"]
    after_coverage = after["hedgeCoveragePercent"]
    impact_type = "neutral"
    protection_direction = "unchanged"
    target_distance_before = None
    target_distance_after = None
    if before_coverage is not None and after_coverage is not None:
        delta = after_coverage - before_coverage
        if delta > 0.01:
            protection_direction = "increases"
        elif delta < -0.01:
            protection_direction = "decreases"
        target_distance_before = abs(before_coverage - HEDGE_TARGET_PERCENT)
        target_distance_after = abs(after_coverage - HEDGE_TARGET_PERCENT)
        if target_distance_after + 0.05 < target_distance_before:
            impact_type = "toward_target"
        elif target_distance_after > target_distance_before + 0.05:
            impact_type = "away_from_target"

    return {
        "before": before,
        "after": after,
        "removedLongExposureUsd": round(removed_long, 8),
        "removedShortExposureUsd": round(removed_short, 8),
        "impactType": impact_type,
        "protectionDirection": protection_direction,
        "targetDistanceBefore": round(target_distance_before, 6) if target_distance_before is not None else None,
        "targetDistanceAfter": round(target_distance_after, 6) if target_distance_after is not None else None,
    }


def profitable_positions(
    rows: Iterable[dict[str, Any]], minimum_profit_usd: float = MINIMUM_PROFIT_USD,
) -> list[dict[str, Any]]:
    """Legacy Tradecentrum selector: inclusive >= threshold. Keep unchanged."""
    eligible: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", "")).upper().strip()
        quantity = abs(_number(row.get("positionAmt")) or 0.0)
        mark = _number(row.get("markPrice"))
        profit = position_profit(row)
        if symbol and side in {"LONG", "SHORT"} and quantity > 0 and mark is not None and mark > 0 and profit is not None and profit >= minimum_profit_usd:
            eligible.append({"symbol": symbol, "side": side, "quantity": quantity, "markPrice": mark, "unrealizedPnl": profit})
    return eligible


def strictly_profitable_positions(
    rows: Iterable[dict[str, Any]], *, side: str = "ALL",
    minimum_profit_usd: float = MINIMUM_PROFIT_USD,
) -> list[dict[str, Any]]:
    """Snapshot selector retained for compatibility with older tests/callers."""
    normalized_side = str(side).upper().strip()
    if normalized_side not in {"ALL", "LONG", "SHORT"}:
        raise ValueError("profit-close side must be ALL, LONG or SHORT")
    eligible: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol", "")).upper().strip()
        position_side = str(row.get("positionSide", "")).upper().strip()
        quantity = abs(_number(row.get("positionAmt")) or 0.0)
        mark = _number(row.get("markPrice"))
        profit = position_profit(row)
        if (
            symbol
            and position_side in {"LONG", "SHORT"}
            and (normalized_side == "ALL" or position_side == normalized_side)
            and quantity > 0
            and mark is not None
            and mark > 0
            and profit is not None
            and profit > minimum_profit_usd
        ):
            eligible.append({"symbol": symbol, "side": position_side, "quantity": quantity, "markPrice": mark, "unrealizedPnl": profit})
    return eligible


def profit_preview(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Canonical Tradecentrum/Snapshot preview from one exchange-truth read."""
    materialized = list(rows)
    positions = profitable_positions(materialized)
    long_positions = [item for item in positions if item["side"] == "LONG"]
    short_positions = [item for item in positions if item["side"] == "SHORT"]

    def bucket(selected: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "eligible": selected,
            "eligibleCount": len(selected),
            "totalProfitUsd": round(sum(item["unrealizedPnl"] for item in selected), 8),
            "impact": _close_impact(materialized, selected),
        }

    return {
        "eligible": positions,
        "eligibleCount": len(positions),
        "totalProfitUsd": round(sum(item["unrealizedPnl"] for item in positions), 8),
        "minimumProfitUsd": MINIMUM_PROFIT_USD,
        "comparison": "greater_than_or_equal",
        "hedgeConfig": {
            "targetPercent": HEDGE_TARGET_PERCENT,
            "healthyMinPercent": HEDGE_HEALTHY_MIN_PERCENT,
            "healthyMaxPercent": HEDGE_HEALTHY_MAX_PERCENT,
        },
        "exposure": portfolio_exposure(materialized),
        "long": bucket(long_positions),
        "short": bucket(short_positions),
        "all": bucket(positions),
    }


def strict_profit_preview(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return strict Snapshot buckets from one exchange-truth read."""
    materialized = list(rows)
    buckets: dict[str, Any] = {}
    for side, key in (("LONG", "long"), ("SHORT", "short"), ("ALL", "all")):
        positions = strictly_profitable_positions(materialized, side=side)
        buckets[key] = {
            "eligible": positions,
            "eligibleCount": len(positions),
            "totalProfitUsd": round(sum(item["unrealizedPnl"] for item in positions), 8),
        }
    return {
        **buckets,
        "minimumProfitUsd": MINIMUM_PROFIT_USD,
        "comparison": "strictly_greater_than",
    }
