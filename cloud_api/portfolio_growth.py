"""Account-scoped portfolio-growth arithmetic and close-all safety helpers.

The functions in this module are deliberately exchange- and database-agnostic so
the financial rules can be exhaustively tested without credentials or orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterable


EXTERNAL_CASHFLOW_TYPES = frozenset({"TRANSFER", "WELCOME_BONUS", "INSURANCE_CLEAR"})
ENTRY_INTENT_WORDS = ("open", "entry", "base", "dca", "reopen", "reset")
PORTFOLIO_GROWTH_START_DATE = "2026-08-23"


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("Financieel gegeven ontbreekt of is ongeldig")
    if not math.isfinite(number):
        raise ValueError("Financieel gegeven is niet eindig")
    return number


@dataclass(frozen=True)
class CloseEstimate:
    baseline: float
    adjusted_baseline: float
    exchange_equity: float
    external_cashflow: float
    expected_fees: float
    slippage_buffer: float
    other_costs: float
    expected_end_value: float
    difference: float
    percentage: float
    position_count: int
    reliable: bool
    block_reason: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "baseline": round(self.baseline, 8),
            "adjustedBaseline": round(self.adjusted_baseline, 8),
            "exchangeEquity": round(self.exchange_equity, 8),
            "externalCashflow": round(self.external_cashflow, 8),
            "expectedFees": round(self.expected_fees, 8),
            "slippageBuffer": round(self.slippage_buffer, 8),
            "otherCosts": round(self.other_costs, 8),
            "expectedEndValue": round(self.expected_end_value, 8),
            "difference": round(self.difference, 8),
            "percentage": round(self.percentage, 8),
            "positionCount": self.position_count,
            "reliable": self.reliable,
            "profitable": self.reliable and self.difference > 0,
            "closeEnabled": self.reliable and self.difference > 0 and self.position_count > 0,
            "blockReason": self.block_reason,
        }



def daily_return_percentage(previous_equity: Any, current_equity: Any, external_cashflow: Any = 0) -> float:
    previous = _finite(previous_equity)
    current = _finite(current_equity)
    cashflow = _finite(external_cashflow)
    if previous <= 0:
        raise ValueError("Vorige dagwaarde moet positief zijn")
    return ((current - cashflow) - previous) / previous * 100.0


def average_daily_return(completed_sum: Any, completed_count: int, today_return: Any) -> float:
    total = _finite(completed_sum) + _finite(today_return)
    count = int(completed_count) + 1
    if count <= 0:
        raise ValueError("Aantal gemeten dagen moet positief zijn")
    return total / count

def external_cashflow_since(rows: Iterable[dict[str, Any]], since_ms: int) -> float:
    total = 0.0
    for row in rows:
        when = int(_finite(row.get("time", row.get("timestamp", 0))))
        if when < since_ms:
            continue
        if str(row.get("incomeType", "")).upper() in EXTERNAL_CASHFLOW_TYPES:
            total += _finite(row.get("income", 0))
    return total


def estimate_close_value(
    *, baseline: Any, exchange_equity: Any, positions: Iterable[dict[str, Any]],
    external_cashflow: Any = 0, taker_fee_rate: Any, slippage_rate: Any,
    other_costs: Any = 0, equity_includes_unrealized: bool,
    funding_in_equity: bool, data_fresh: bool, cashflow_complete: bool,
) -> CloseEstimate:
    base = _finite(baseline)
    equity = _finite(exchange_equity)
    cashflow = _finite(external_cashflow)
    fee_rate = _finite(taker_fee_rate)
    slip_rate = _finite(slippage_rate)
    costs = _finite(other_costs)
    rows = [row for row in positions if abs(_finite(row.get("positionAmt", 0))) > 0]
    notional = sum(abs(_finite(row.get("positionAmt"))) * _finite(row.get("markPrice")) for row in rows)
    reliable = True
    reason = ""
    if base <= 0 or equity < 0 or min(fee_rate, slip_rate, costs) < 0:
        reliable, reason = False, "Basis, equity of kosten zijn ongeldig"
    elif not equity_includes_unrealized:
        reliable, reason = False, "Exchange-equity bevat ongerealiseerde P&L niet aantoonbaar"
    elif not funding_in_equity:
        reliable, reason = False, "Fundingverwerking is niet aantoonbaar"
    elif not data_fresh:
        reliable, reason = False, "Exchangegegevens zijn verouderd"
    elif not cashflow_complete:
        reliable, reason = False, "Stortingen en opnames zijn niet volledig aantoonbaar"
    fees = notional * fee_rate
    slippage = notional * slip_rate
    adjusted = base + cashflow
    expected = equity - fees - slippage - costs
    difference = expected - adjusted
    percentage = difference / adjusted * 100 if adjusted > 0 else 0.0
    return CloseEstimate(base, adjusted, equity, cashflow, fees, slippage, costs,
        expected, difference, percentage, len(rows), reliable, reason)


def is_exposure_order(order: dict[str, Any]) -> bool | None:
    """True=entry order, False=protection/close, None=not safely classifiable."""
    if str(order.get("reduceOnly", "")).lower() == "true":
        return False
    client_id = str(order.get("clientOrderId", order.get("origClientOrderId", ""))).lower()
    if any(word in client_id for word in ENTRY_INTENT_WORDS):
        return True
    if any(word in client_id for word in ("close", "take", "tp", "protect", "stop")):
        return False
    return None


def utc_ms(value: datetime) -> int:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return int(aware.astimezone(timezone.utc).timestamp() * 1000)
