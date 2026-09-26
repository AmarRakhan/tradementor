"""Account-scoped portfolio-growth arithmetic and close-all safety helpers.

The functions in this module are deliberately exchange- and database-agnostic so
the financial rules can be exhaustively tested without credentials or orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
import math
from typing import Any, Iterable
from zoneinfo import ZoneInfo


# Only non-performance capital movements are neutralised from return.
# INSURANCE_CLEAR is deliberately excluded: Aster lists it alongside trading
# income and forced-liquidation/ADL effects must remain visible in performance.
EXTERNAL_CASHFLOW_TYPES = frozenset({
    "TRANSFER", "DEPOSIT", "WITHDRAWAL", "WALLET_TRANSFER", "INTERNAL_TRANSFER",
    "WELCOME_BONUS", "BALANCE_ADJUSTMENT",
})
CASHFLOW_ADJUSTMENT_TYPES = frozenset({"WELCOME_BONUS", "BALANCE_ADJUSTMENT"})
ENTRY_INTENT_WORDS = ("open", "entry", "base", "dca", "reopen", "reset")
PORTFOLIO_GROWTH_START_DATE = "2026-08-23"
PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION = 4


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



def select_day_start_snapshot(
    candles: Iterable[dict[str, Any]], *, day_start_ms: int,
    current_equity: Any, current_at_ms: int,
) -> dict[str, Any]:
    """Choose the first confirmed equity sample inside the local calendar day.

    A stale previous-day observation is never allowed to become today's
    performance baseline. If no earlier same-day sample exists, the current
    exchange equity becomes the baseline so the statistic starts neutrally.
    """
    start = int(day_start_ms)
    current_at = int(current_at_ms)
    candidates: list[tuple[int, float]] = []
    for row in candles:
        if not isinstance(row, dict):
            continue
        sample_at = int(_finite(row.get("firstSampleAtMs", row.get("atMs", 0))))
        opened = _finite(row.get("open", 0))
        if opened > 0 and start <= sample_at <= current_at:
            candidates.append((sample_at, opened))
    if candidates:
        sample_at, opened = min(candidates, key=lambda item: item[0])
        return {"equity": opened, "atMs": sample_at, "source": "portfolio-chart-same-day"}
    current = _finite(current_equity)
    if current <= 0 or current_at <= 0:
        raise ValueError("Actuele portfolio-equity is ongeldig")
    return {"equity": current, "atMs": current_at, "source": "current-exchange-equity"}



def historical_day_windows(
    candles: Iterable[dict[str, Any]], *, timezone_name: str,
    current_date: str, max_days: int | None = None,
    boundary_tolerance_minutes: int = 90,
) -> list[dict[str, Any]]:
    """Return only completed local days with reliable start/end equity coverage.

    Partial days are excluded from the multi-day average instead of being
    presented as complete daily returns.
    """
    if max_days is not None and max_days < 1:
        return []
    zone = ZoneInfo(str(timezone_name))
    today = date.fromisoformat(str(current_date))
    tolerance_ms = max(0, int(boundary_tolerance_minutes)) * 60_000
    grouped: dict[date, dict[str, Any]] = {}

    for row in candles:
        if not isinstance(row, dict):
            continue
        try:
            first_ms = int(_finite(row.get("firstSampleAtMs", row.get("atMs", 0))))
            last_ms = int(_finite(row.get("sourceAtMs", row.get("lastSampleAtMs", row.get("atMs", 0)))))
            opened = _finite(row.get("open", 0))
            closed = _finite(row.get("close", 0))
        except ValueError:
            continue
        if first_ms <= 0 or last_ms < first_ms or opened <= 0 or closed <= 0:
            continue
        first_local = datetime.fromtimestamp(first_ms / 1000, tz=timezone.utc).astimezone(zone)
        last_local = datetime.fromtimestamp(last_ms / 1000, tz=timezone.utc).astimezone(zone)
        if first_local.date() != last_local.date() or first_local.date() >= today:
            continue
        day = first_local.date()
        bucket = grouped.setdefault(day, {
            "date": day.isoformat(),
            "startAtMs": first_ms,
            "endAtMs": last_ms,
            "startEquity": opened,
            "endEquity": closed,
        })
        if first_ms < int(bucket["startAtMs"]):
            bucket["startAtMs"] = first_ms
            bucket["startEquity"] = opened
        if last_ms > int(bucket["endAtMs"]):
            bucket["endAtMs"] = last_ms
            bucket["endEquity"] = closed

    reliable: list[dict[str, Any]] = []
    for day in sorted(grouped):
        row = grouped[day]
        day_start = datetime.combine(day, datetime_time.min, tzinfo=zone)
        next_start = datetime.combine(day + timedelta(days=1), datetime_time.min, tzinfo=zone)
        day_start_ms = int(day_start.astimezone(timezone.utc).timestamp() * 1000)
        day_end_ms = int(next_start.astimezone(timezone.utc).timestamp() * 1000)
        if int(row["startAtMs"]) - day_start_ms > tolerance_ms:
            continue
        if day_end_ms - int(row["endAtMs"]) > tolerance_ms:
            continue
        if int(row["endAtMs"]) <= int(row["startAtMs"]):
            continue
        reliable.append(dict(row))
    return reliable if max_days is None else reliable[-int(max_days):]

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
            total += _finite(row.get("income", row.get("amount", 0)))
    return total


def external_cashflow_breakdown(rows: Iterable[dict[str, Any]], since_ms: int) -> dict[str, Any]:
    """Audit-friendly signed cashflow breakdown for the measured Aster scope."""
    deposits = 0.0
    withdrawals = 0.0
    adjustments = 0.0
    count = 0
    types: set[str] = set()
    for row in rows:
        when = int(_finite(row.get("time", row.get("timestamp", 0))))
        ledger_type = str(row.get("incomeType", "")).upper().strip()
        if when < since_ms or ledger_type not in EXTERNAL_CASHFLOW_TYPES:
            continue
        amount = _finite(row.get("income", row.get("amount", 0)))
        if abs(amount) <= 1e-12:
            continue
        count += 1
        types.add(ledger_type)
        if ledger_type in CASHFLOW_ADJUSTMENT_TYPES:
            adjustments += amount
        elif amount > 0:
            deposits += amount
        else:
            withdrawals += amount
    return {
        "count": count,
        "depositsUsd": deposits,
        "withdrawalsUsd": withdrawals,
        "adjustmentsUsd": adjustments,
        "netExternalCashflowUsd": deposits + withdrawals + adjustments,
        "ledgerTypes": sorted(types),
    }


def chain_linked_return_percent(subperiod_returns_percent: Iterable[Any]) -> float:
    """Chain-link independently measured subperiod returns (TWR primitive)."""
    factor = 1.0
    count = 0
    for value in subperiod_returns_percent:
        rate = _finite(value) / 100.0
        if rate <= -1.0:
            raise ValueError("Subperiode-rendement kan niet lager dan -100% zijn")
        factor *= 1.0 + rate
        count += 1
    if count == 0:
        raise ValueError("Minimaal één subperiode is vereist")
    return (factor - 1.0) * 100.0


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
