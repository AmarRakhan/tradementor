"""Joint LONG + SHORT exit at take profit, only when net positive (build 623: both sides, every Auto Hedge pair).

Agreed with Amar (22-10-2026):
* LONG TP reached on a pair that SHORT Recovery manages and that still has a SHORT
  -> LONG and SHORT close together, but only if the live total is net positive.
* Net = open PnL LONG + open PnL SHORT - estimated closing fees - PAID funding since the
  hedge started. Received funding is ignored. Profits of earlier ladder steps do NOT count.
* Not net positive -> do nothing and wait.

Split of responsibilities (no second order engine):
* The Multi-BB TP path owns "is the LONG TP due". For a managed pair with an open SHORT it
  does not close the LONG; it calls ``long_tp_gate`` which records an exit request.
* The Auto Hedge worker (holds the account lease, owns the SHORT) evaluates the request,
  closes the SHORT through the existing engine when net positive, and marks PAIR_EXIT.
* The next Multi-BB tick sees PAIR_EXIT + SHORT flat and closes the LONG through its
  existing TP order path.
Every unreadable input fails closed (wait, no order).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import threading
from typing import Any, Callable

# Conservative taker fee estimate per closing order (fraction of notional).
DEFAULT_CLOSE_FEE_RATE = Decimal("0.0005")
PAGE_LIMIT = 1000

_lock = threading.RLock()
_reader: Callable[[str, str], dict[str, Any]] | None = None
_requester: Callable[[str, str, str], None] | None = None


def configure(reader: Callable[[str, str], dict[str, Any]] | None,
              requester: Callable[[str, str, str], None] | None) -> None:
    global _reader, _requester
    with _lock:
        _reader, _requester = reader, requester


def _d(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


# Auto Hedge pair statuses (mirrors aster_position_loss_auto_hedge_extension; kept local: pure module).
ACTIVE_STATUSES = {"HEDGING", "HEDGED", "ADJUSTING", "BLOCKED", "ERROR", "PRECISION_BLOCKED"}
RECOVERY_STATUSES = {"RECOVERY", "REHEDGE_ARMED", "DISABLED"}
MANUAL_RELEASE_STATUSES = {"MANUAL_RELEASE_PENDING", "MANUAL_RELEASE_UNCERTAIN"}


def pair_tp_gate(*, account_uid: str, symbol: str, side: str, opposite_qty: float) -> tuple[str, str]:
    """Called by the Multi-BB TP path (LONG or SHORT) right before it would close that leg.

    Build 623 (Amar 23-10): on EVERY Auto Hedge pair (hedge afbouwen ON or OFF, LONG or SHORT protected)
    a TP closes both legs together and only when the live total is net positive. The TP leg waits; the
    Auto Hedge worker checks the net result, closes the opposite leg, and the next TP tick then closes this
    leg (opposite flat -> ALLOW). Returns ("ALLOW", reason) or ("WAIT", reason). Unreadable -> WAIT.
    """
    with _lock:
        reader, requester = _reader, _requester
    if reader is None:
        return "ALLOW", "SHORT_RECOVERY_NOT_CONFIGURED"
    try:
        pair = reader(str(account_uid), str(symbol).upper()) or {}
    except Exception:
        return "WAIT", "PAIR_STATE_UNREADABLE"
    if not isinstance(pair, dict):
        return "WAIT", "PAIR_STATE_UNREADABLE"
    status = str(pair.get("status") or "").upper()
    if not status or status == "CLOSED":
        return "ALLOW", "NOT_AUTO_HEDGE_PAIR"
    if float(opposite_qty or 0) <= 0:
        exiting = isinstance(pair.get("pairExit"), dict) or (
            isinstance(pair.get("shortRecovery"), dict) and pair["shortRecovery"].get("phase") == "PAIR_EXIT")
        return "ALLOW", "OPPOSITE_FLAT_JOINT_EXIT" if exiting else "OPPOSITE_FLAT"
    tp_side = str(side or "").upper()
    if status in MANUAL_RELEASE_STATUSES:
        return "WAIT", "MANUAL_RELEASE_IN_PROGRESS"
    if status in ACTIVE_STATUSES and tp_side != str(pair.get("protectedSide") or "").upper():
        # TP of an own position on the hedge side: the close guard keeps the Auto Hedge part reserved.
        return "ALLOW", "TP_ON_HEDGE_SIDE"
    if requester is None:
        return "WAIT", "EXIT_REQUEST_UNAVAILABLE"
    try:
        requester(str(account_uid), str(symbol).upper(), tp_side)
    except Exception:
        return "WAIT", "EXIT_REQUEST_FAILED"
    return "WAIT", "JOINT_EXIT_REQUESTED_WAIT_FOR_NET_CHECK"


def long_tp_gate(*, account_uid: str, symbol: str, short_qty: float) -> tuple[str, str]:
    """Backwards-compatible LONG entry point (see ``pair_tp_gate``)."""
    return pair_tp_gate(account_uid=account_uid, symbol=symbol, side="LONG", opposite_qty=short_qty)


def paid_funding(client: Any, *, symbol: str, start_ms: int) -> Decimal | None:
    """Sum of PAID funding (negative FUNDING_FEE rows) since start_ms, as a positive cost.

    Received funding is ignored. A full page cannot prove completeness -> None (fail closed).
    """
    try:
        rows = client.income_history(symbol=symbol, income_type="FUNDING_FEE",
                                     start_time=int(start_ms), limit=PAGE_LIMIT)
    except Exception:
        return None
    if not isinstance(rows, list) or len(rows) >= PAGE_LIMIT:
        return None
    paid = Decimal(0)
    for row in rows:
        if not isinstance(row, dict):
            return None
        if str(row.get("symbol", symbol)).upper() != str(symbol).upper():
            continue
        amount = _d(row.get("income"))
        if amount is None:
            return None
        if amount < 0:
            paid += -amount
    return paid


def net_exit(*, long_pnl: Any, short_pnl: Any, long_notional: Any, short_notional: Any,
             funding_paid: Decimal | None, fee_rate: Decimal = DEFAULT_CLOSE_FEE_RATE) -> dict[str, Any]:
    values = [_d(long_pnl), _d(short_pnl), _d(long_notional), _d(short_notional)]
    if any(v is None for v in values) or funding_paid is None:
        return {"allowed": False, "reason": "NET_INPUT_UNKNOWN_WAIT", "net": None}
    lp, sp, ln, sn = values
    fees = (abs(ln) + abs(sn)) * fee_rate
    net = lp + sp - fees - funding_paid
    return {"allowed": net > 0, "reason": "NET_POSITIVE" if net > 0 else "NET_NOT_POSITIVE_WAIT",
            "net": net, "fees": fees, "fundingPaid": funding_paid}
