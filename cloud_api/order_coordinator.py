"""Central exactly-once decision gate for all exchange order intents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from portfolio_risk import PortfolioRiskDecision


IntentAction = Literal["OPEN", "ADD", "HEDGE", "CLOSE", "CANCEL"]
ExistingStatus = Literal["prepared", "submitting", "accepted", "pending", "filled", "uncertain", "rejected"]


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    exchange: str
    symbol: str
    position_side: str
    action: IntentAction
    requested_notional: float
    created_at_ms: int

    @property
    def risk_increasing(self) -> bool:
        return self.action in {"OPEN", "ADD", "HEDGE"}


@dataclass(frozen=True)
class ExistingIntent:
    intent_id: str
    status: ExistingStatus
    exchange_order_id: str = ""


@dataclass(frozen=True)
class CoordinatorDecision:
    action: Literal["PROCEED", "REPLAY", "BLOCK"]
    reason: str
    exchange_order_id: str = ""


def coordinate_order(
    intent: OrderIntent,
    *,
    existing: ExistingIntent | None,
    adapter_ready: bool,
    reconciliation_ready: bool,
    automation_enabled: bool,
    risk: PortfolioRiskDecision | None,
    now_ms: int,
    maximum_intent_age_ms: int = 30_000,
) -> CoordinatorDecision:
    if not intent.intent_id or not intent.exchange or not intent.symbol or not intent.position_side:
        return CoordinatorDecision("BLOCK", "Orderintentie is onvolledig")
    if intent.requested_notional <= 0:
        return CoordinatorDecision("BLOCK", "Orderwaarde moet positief zijn")

    if existing is not None:
        if existing.intent_id != intent.intent_id:
            return CoordinatorDecision("BLOCK", "Idempotency-record hoort bij een andere intentie")
        if existing.status in {"accepted", "pending", "filled"}:
            return CoordinatorDecision(
                "REPLAY", "Deze intentie is al verwerkt", existing.exchange_order_id
            )
        if existing.status in {"submitting", "uncertain"}:
            return CoordinatorDecision(
                "BLOCK", "Orderstatus is onzeker; eerst exchange-reconciliation uitvoeren"
            )
        # A rejected intent is immutable. A strategy must create a new intent
        # after a fresh market/risk decision instead of replaying stale input.
        if existing.status == "rejected":
            return CoordinatorDecision("BLOCK", "Afgewezen intentie mag niet opnieuw worden gebruikt")

    if now_ms - intent.created_at_ms > maximum_intent_age_ms:
        return CoordinatorDecision("BLOCK", "Orderintentie is verlopen")
    if not adapter_ready:
        return CoordinatorDecision("BLOCK", "Exchange-adapter is niet gereed")
    if not reconciliation_ready:
        return CoordinatorDecision("BLOCK", "Exchange-state is nog niet gereconcilieerd")

    if intent.risk_increasing:
        if not automation_enabled:
            return CoordinatorDecision("BLOCK", "Automatische handel staat UIT")
        if risk is None or not risk.approved:
            return CoordinatorDecision("BLOCK", "Portfolio Risk Manager blokkeert de order")

    # CLOSE and CANCEL remain possible while automation is off or the risk
    # budget is closed; they still require a ready adapter and reconciliation.
    return CoordinatorDecision("PROCEED", "Alle ordergates zijn geslaagd")

