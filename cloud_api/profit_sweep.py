"""Pure accounting rules for Profit Sweep / Profit Pot reservations.

Only positive realized net profit can contribute. Principal, notional, margin,
wallet balance and unrealized PnL are deliberately outside this module.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

DEFAULT_SWEEP_ENABLED = False
DEFAULT_SWEEP_PERCENT = Decimal("25")
MIN_SWEEP_PERCENT = Decimal("0")
MAX_SWEEP_PERCENT = Decimal("100")
_AMOUNT_QUANTUM = Decimal("0.00000001")


class ProfitSweepError(ValueError):
    pass


def _decimal(value: Any, *, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProfitSweepError(f"{label} is ongeldig") from exc
    if not result.is_finite():
        raise ProfitSweepError(f"{label} is ongeldig")
    return result


def normalize_sweep_percent(value: Any = DEFAULT_SWEEP_PERCENT) -> Decimal:
    percent = _decimal(value, label="Spaarpercentage")
    if percent < MIN_SWEEP_PERCENT or percent > MAX_SWEEP_PERCENT:
        raise ProfitSweepError("Spaarpercentage moet tussen 0% en 100% liggen")
    return percent


def sweep_contribution(net_realized_profit: Any, sweep_percent: Any, *, enabled: bool = True) -> Decimal:
    """Return the savings contribution from positive net realized profit only."""
    if not enabled:
        return Decimal("0")
    profit = _decimal(net_realized_profit, label="Gerealiseerde nettowinst")
    if profit <= 0:
        return Decimal("0")
    percent = normalize_sweep_percent(sweep_percent)
    return (profit * percent / Decimal("100")).quantize(_AMOUNT_QUANTUM, rounding=ROUND_DOWN)


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def build_sweep_booking(*, closure_id: str, net_realized_profit: Any, sweep_percent: Any, enabled: bool = True) -> dict[str, Any]:
    """Snapshot the immutable settings used for one close/cycle booking."""
    close_key = str(closure_id or "").strip()
    if not close_key:
        raise ProfitSweepError("closure_id ontbreekt")
    profit = _decimal(net_realized_profit, label="Gerealiseerde nettowinst")
    percent = normalize_sweep_percent(sweep_percent)
    contribution = sweep_contribution(profit, percent, enabled=enabled)
    return {
        "closureId": close_key,
        "enabled": bool(enabled),
        "netRealizedProfit": _plain(profit),
        "sweepPercent": _plain(percent),
        "sweepContribution": _plain(contribution),
        "principalIncluded": False,
        "unrealizedPnlIncluded": False,
    }
