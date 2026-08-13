"""Close-all orchestration that can be tested with a fake exchange."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


def execute_close_all(
    positions: Iterable[dict[str, Any]],
    cancel_reduce_only: Callable[[str], int],
    close_position: Callable[[str, float], None],
) -> dict[str, list[Any]]:
    closed: list[str] = []
    failed: list[dict[str, str]] = []
    seen: set[str] = set()
    for position in positions:
        symbol = str(position.get("coin", "")).upper().strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        size = abs(float(position.get("szi", 0) or 0))
        if size <= 0:
            continue
        try:
            cancel_reduce_only(symbol)
            close_position(symbol, size)
            closed.append(symbol)
        except Exception as exc:
            failed.append({"symbol": symbol, "reason": str(exc)[:160]})
    return {"closed": closed, "failed": failed}
