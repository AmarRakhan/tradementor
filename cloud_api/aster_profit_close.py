"""Pure selection helpers for the explicitly confirmed Aster profit bulk-close."""
from __future__ import annotations

from typing import Any, Iterable


MINIMUM_PROFIT_USD = 0.50


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


def profitable_positions(
    rows: Iterable[dict[str, Any]], minimum_profit_usd: float = MINIMUM_PROFIT_USD,
) -> list[dict[str, Any]]:
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


def profit_preview(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    positions = profitable_positions(rows)
    return {
        "eligible": positions,
        "eligibleCount": len(positions),
        "totalProfitUsd": round(sum(item["unrealizedPnl"] for item in positions), 8),
        "minimumProfitUsd": MINIMUM_PROFIT_USD,
    }
