"""Exchange-agnostic portfolio risk gate.

All figures use quote-currency values. The gate is intentionally conservative:
missing, stale or contradictory exchange data blocks exposure increases while
risk-reducing actions can still be handled by the order coordinator.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class ExchangeRiskSnapshot:
    exchange: str
    equity: float
    available_balance: float
    gross_exposure: float
    net_exposure: float
    used_margin: float
    maintenance_margin: float
    minimum_liquidation_distance: float
    captured_at_ms: int
    read_ok: bool = True


@dataclass(frozen=True)
class PortfolioRiskLimits:
    maximum_gross_exposure_multiple: float = 3.0
    maximum_margin_ratio: float = 0.60
    maximum_single_exchange_share: float = 0.70
    minimum_liquidation_distance: float = 0.08
    minimum_emergency_reserve: float = 10.0
    maximum_daily_drawdown: float = 0.10
    maximum_snapshot_age_ms: int = 30_000


@dataclass(frozen=True)
class PortfolioRiskDecision:
    approved: bool
    reasons: tuple[str, ...]
    total_equity: float
    total_available: float
    total_gross_exposure: float
    total_net_exposure: float
    portfolio_margin_ratio: float
    projected_gross_multiple: float


def evaluate_risk_increase(
    snapshots: Iterable[ExchangeRiskSnapshot],
    *,
    requested_exchange: str,
    requested_notional: float,
    now_ms: int,
    day_start_equity: float,
    limits: PortfolioRiskLimits = PortfolioRiskLimits(),
) -> PortfolioRiskDecision:
    rows = tuple(snapshots)
    reasons: list[str] = []
    if not rows:
        reasons.append("Geen exchange-risicodata beschikbaar")
    if not math.isfinite(requested_notional) or requested_notional <= 0:
        reasons.append("Gevraagde orderwaarde is ongeldig")
    if any(not row.read_ok for row in rows):
        reasons.append("Minstens één exchange kon niet betrouwbaar worden gelezen")
    if any(now_ms - row.captured_at_ms > limits.maximum_snapshot_age_ms for row in rows):
        reasons.append("Risicodata is te oud")

    numeric_values = [
        value
        for row in rows
        for value in (
            row.equity, row.available_balance, row.gross_exposure, row.net_exposure,
            row.used_margin, row.maintenance_margin, row.minimum_liquidation_distance,
        )
    ]
    if any(not math.isfinite(value) for value in numeric_values):
        reasons.append("Risicodata bevat een ongeldig getal")

    total_equity = sum(max(row.equity, 0.0) for row in rows)
    total_available = sum(max(row.available_balance, 0.0) for row in rows)
    gross = sum(max(row.gross_exposure, 0.0) for row in rows)
    net = sum(row.net_exposure for row in rows)
    used_margin = sum(max(row.used_margin, 0.0) for row in rows)
    margin_ratio = used_margin / total_equity if total_equity > 0 else math.inf
    projected_gross = gross + max(requested_notional, 0.0)
    projected_multiple = projected_gross / total_equity if total_equity > 0 else math.inf

    if total_equity <= 0:
        reasons.append("Totale portfoliowaarde is niet positief")
    if total_available - requested_notional < limits.minimum_emergency_reserve:
        reasons.append("Noodreserve zou onder de veilige grens komen")
    if margin_ratio > limits.maximum_margin_ratio:
        reasons.append("Portefeuille-marginratio is te hoog")
    if projected_multiple > limits.maximum_gross_exposure_multiple:
        reasons.append("Totale blootstelling zou de portfoliolimiet overschrijden")
    if rows and min(row.minimum_liquidation_distance for row in rows) < limits.minimum_liquidation_distance:
        reasons.append("Minimale liquidatieafstand is te klein")

    if day_start_equity > 0:
        drawdown = max(0.0, (day_start_equity - total_equity) / day_start_equity)
        if drawdown >= limits.maximum_daily_drawdown:
            reasons.append("Dagelijkse drawdown-circuit-breaker is actief")
    else:
        reasons.append("Startwaarde voor dagelijkse drawdown ontbreekt")

    exchange_gross = sum(
        max(row.gross_exposure, 0.0)
        for row in rows if row.exchange.lower() == requested_exchange.lower()
    )
    if projected_gross > 0:
        projected_share = (exchange_gross + max(requested_notional, 0.0)) / projected_gross
        if projected_share > limits.maximum_single_exchange_share:
            reasons.append("Te veel blootstelling zou op één exchange staan")

    return PortfolioRiskDecision(
        approved=not reasons,
        reasons=tuple(reasons or ("Portfolio Risk Manager keurt de order goed",)),
        total_equity=total_equity,
        total_available=total_available,
        total_gross_exposure=gross,
        total_net_exposure=net,
        portfolio_margin_ratio=margin_ratio,
        projected_gross_multiple=projected_multiple,
    )
