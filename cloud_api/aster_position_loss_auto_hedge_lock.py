"""Central automatic-close reservation guard for Auto Hedge 2.0.

This module stays independent from FastAPI/Firestore. The application installs one
read-only pair-state reader at startup. Automatic close paths call the guard with
trusted CloseEvidence before constructing an exchange CLOSE order.

Only quantity created/reserved by Auto Hedge is locked. Normal strategy quantity
on the same aggregated Aster leg remains closable up to normalFreeQty.
Emergency/manual close-all intentionally bypasses this guard.
"""
from __future__ import annotations

from typing import Any, Callable
import math
import threading

_lock = threading.RLock()
_reader: Callable[[str, str], dict[str, Any]] | None = None

LOCKED_STATUSES = {"HEDGING", "HEDGED", "ADJUSTING", "BLOCKED", "ERROR", "PRECISION_BLOCKED"}
# Bulk-profit convenience actions must stay completely away from any symbol that
# still belongs to an Auto Hedge lifecycle. This is intentionally broader than
# the quantity reservation guard below: it protects both legs of the managed
# pair, including RECOVERY/REHEDGE states, from Close Long/Short/All.
AUTO_HEDGE_MANAGED_STATUSES = LOCKED_STATUSES | {"RECOVERY", "REHEDGE_ARMED", "DISABLED"}
EPSILON = 1e-12


class AutoHedgeCloseBlocked(RuntimeError):
    def __init__(self, event: dict[str, Any]):
        self.event = event
        super().__init__(str(event.get("message") or "Auto Hedge-lock blokkeert deze sluiting"))


def configure_auto_hedge_lock_reader(reader: Callable[[str, str], dict[str, Any]] | None) -> None:
    global _reader
    with _lock:
        _reader = reader


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def current_lock(account_uid: str, symbol: str) -> dict[str, Any]:
    with _lock:
        reader = _reader
    if not callable(reader) or not account_uid or not symbol:
        return {}
    try:
        value = reader(str(account_uid), str(symbol).upper())
    except Exception:
        # Fail closed only when the caller has a configured reader but the
        # source itself fails: automatic closes must not guess away protection.
        raise AutoHedgeCloseBlocked({
            "event": "AUTO_HEDGE_CLOSE_BLOCKED",
            "accountUid": str(account_uid),
            "symbol": str(symbol).upper(),
            "blockReason": "AUTO_HEDGE_LOCK_STATE_UNAVAILABLE",
            "message": "Auto Hedge-lock kon niet betrouwbaar worden gelezen",
        })
    return value if isinstance(value, dict) else {}


def auto_hedge_symbol_managed(*, account_uid: str, symbol: str) -> bool:
    """Return whether a symbol is still owned by an Auto Hedge pair lifecycle.

    Empty/CLOSED means no active Auto Hedge ownership. Any known managed status
    is protected. An unexpected non-empty status is also treated as managed so
    bulk-profit actions fail safe when lifecycle versions drift.
    """
    row = current_lock(account_uid, symbol)
    status = str(row.get("status", "")).upper().strip()
    if not status or status == "CLOSED":
        return False
    return status in AUTO_HEDGE_MANAGED_STATUSES or bool(status)


def require_auto_hedge_close_allowed(
    *,
    account_uid: str,
    symbol: str,
    side: str,
    quantity: float,
    caller: str,
    audit: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    row = current_lock(account_uid, symbol)
    status = str(row.get("status", "")).upper()
    hedge_side = str(row.get("hedgeSide", "")).upper()
    if status not in LOCKED_STATUSES or hedge_side != str(side).upper():
        return

    requested = max(0.0, _f(quantity))
    reserved = max(0.0, _f(row.get("reservedHedgeQty")))
    observed = max(0.0, _f(row.get("currentHedgeQty")))
    # normalFreeQty is persisted from exchange truth by the reconciliation
    # worker. Recompute conservatively and take the lower trustworthy value.
    derived_free = max(0.0, observed - reserved)
    stored_free = max(0.0, _f(row.get("normalFreeQty"), derived_free))
    free = min(derived_free, stored_free)

    if reserved <= EPSILON or requested <= free + EPSILON:
        return

    event = {
        "event": "AUTO_HEDGE_CLOSE_BLOCKED",
        "accountUid": str(account_uid),
        "symbol": str(symbol).upper(),
        "side": str(side).upper(),
        "caller": str(caller or "unknown"),
        "proposedQuantity": requested,
        "reservedHedgeQty": reserved,
        "observedHedgeQty": observed,
        "normalFreeQty": free,
        "pairCycleId": str(row.get("generationId", "")),
        "pairStatus": status,
        "blockReason": "HEDGE_LOCKED_QUANTITY_RESERVED",
        "message": (
            f"{symbol}: sluiting van {requested:g} {side} zou Auto Hedge-dekking "
            f"onder de gereserveerde {reserved:g} brengen"
        ),
    }
    if audit:
        audit(event)
    raise AutoHedgeCloseBlocked(event)
