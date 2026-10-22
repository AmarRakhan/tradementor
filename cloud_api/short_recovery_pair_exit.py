"""SHORT Recovery 2.0 — joint LONG + SHORT exit at LONG take profit, only when net positive.

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
_requester: Callable[[str, str], None] | None = None


def configure(reader: Callable[[str, str], dict[str, Any]] | None,
              requester: Callable[[str, str], None] | None) -> None:
    global _reader, _requester
    with _lock:
        _reader, _requester = reader, requester


def _d(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def long_tp_gate(*, account_uid: str, symbol: str, short_qty: float) -> tuple[str, str]:
    """Called by the Multi-BB LONG TP path right before it would close the LONG.

    Returns ("ALLOW", reason) to close the LONG now, or ("WAIT", reason) to skip this tick.
    Legacy pairs (no live SHORT Recovery record) are always ALLOW: behaviour unchanged.
    """
    with _lock:
        reader, requester = _reader, _requester
    if reader is None:
        return "ALLOW", "SHORT_RECOVERY_NOT_CONFIGURED"
    try:
        pair = reader(str(account_uid), str(symbol).upper()) or {}
    except Exception:
        return "WAIT", "PAIR_STATE_UNREADABLE"
    record = pair.get("shortRecovery") if isinstance(pair, dict) else None
    if not isinstance(record, dict):
        return "ALLOW", "NOT_RECOVERY_MANAGED"
    if float(short_qty or 0) <= 0:
        return "ALLOW", "SHORT_FLAT_JOINT_EXIT" if record.get("phase") == "PAIR_EXIT" else "SHORT_FLAT"
    if requester is None:
        return "WAIT", "EXIT_REQUEST_UNAVAILABLE"
    try:
        requester(str(account_uid), str(symbol).upper())
    except Exception:
        return "WAIT", "EXIT_REQUEST_FAILED"
    return "WAIT", "JOINT_EXIT_REQUESTED_WAIT_FOR_NET_CHECK"


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
