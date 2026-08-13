from __future__ import annotations

from collections.abc import Callable
from typing import Any


def run_confirmed_batch(
    tick: Callable[[], dict[str, Any]], maximum_orders: int = 10
) -> dict[str, Any]:
    """Run sequential ticks and stop on the first non-OK exchange outcome."""
    results: list[dict[str, Any]] = []
    orders_sent = 0
    for _ in range(max(1, min(int(maximum_orders), 10))):
        result = tick()
        results.append(result)
        orders_sent += int(result.get("ordersSent") or 0)
        if str(result.get("status", "")).lower() != "ok":
            break
    return {
        "ordersSent": orders_sent,
        "ticks": len(results),
        "last": results[-1] if results else {},
        "stopped": bool(results and str(results[-1].get("status", "")).lower() != "ok"),
    }
