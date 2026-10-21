"""Pure protection check for the bulk Close Profits button (2.1). No I/O of its own.

The Auto Hedge lock reader is injected so the rule is unit-testable offline and
reader failures propagate (callers fail closed: no order is sent).
"""
from __future__ import annotations

from typing import Any, Callable


def bulk_profit_close_block_reason(
    uid: str, symbol: str, side: str, strategy2_owned_legs: list[Any],
    *, managed_check: Callable[..., bool],
) -> str | None:
    """Return a Dutch reason when a bulk profit close must not touch this leg."""
    symbol = str(symbol).upper().strip()
    side = str(side).upper().strip()
    if side != "SHORT":
        return "Bulk Close Profits sluit alleen SHORT-posities; LONG vereist een geverifieerde hedgekoppeling"
    if managed_check(account_uid=uid, symbol=symbol):
        return "Deze positie valt onder Auto Hedge; bulk Close Profits sluit haar niet"
    for item in strategy2_owned_legs:
        if not isinstance(item, dict):
            continue
        if (str(item.get("symbol", "")).upper() == symbol and str(item.get("side", "")).upper() == side
                and str(item.get("role", "")).upper().startswith("FOCUS_SLOT_AIRBAG:")):
            return "Deze positie is een Focus Airbag-hedge; bulk Close Profits sluit haar niet"
    return None
