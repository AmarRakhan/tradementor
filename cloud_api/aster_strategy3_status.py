"""Read-only net-TP evidence for Strategy 3 positions.

This module projects the persisted Strategy-3 state through the existing pure
Strategy-3 decision engine.  It has no exchange adapter and cannot submit an
order or mutate runtime state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aster_strategy2_state import OwnedLeg, number
from aster_strategy3 import (
    LegState,
    PortfolioState,
    Strategy3Config,
    decide,
    net_return,
    trailing_distance,
)

ASTER_ESTIMATED_CLOSE_FEE_RATE = .0005
STRATEGY3_SCHEDULER_LATE_SECONDS = 180
STRATEGY3_COST_EVIDENCE_MAX_AGE_SECONDS = 300


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return None


def strategy3_scheduler_status(state: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    stamp = _timestamp(state.get("lastTickAt"))
    if stamp is None:
        return {"status": "STALE", "lastTickAt": state.get("lastTickAt"), "ageSeconds": None,
            "warning": "Strategy-3-scheduler heeft nog geen bewezen heartbeat"}
    age = max(0.0, (now - stamp).total_seconds())
    stale = age > STRATEGY3_SCHEDULER_LATE_SECONDS
    return {"status": "STALE" if stale else "HEALTHY", "lastTickAt": stamp,
        "ageSeconds": round(age, 1),
        "warning": f"Strategy-3-scheduler is {int(age)} seconden stil" if stale else ""}


def _notional(row: dict[str, Any]) -> float:
    value = abs(number(row.get("notionalUsd", row.get("notional"))))
    if value <= 0:
        quantity = abs(number(row.get("quantity", row.get("positionAmt"))))
        value = quantity * number(row.get("markPrice"))
    return value


def strategy3_position_tp_contract(*, row: dict[str, Any], owned: OwnedLeg | None,
                                   config: Strategy3Config, state: dict[str, Any],
                                   portfolio: PortfolioState | None,
                                   trailing_peak_return: float | None = None,
                                   now: datetime | None = None) -> dict[str, Any]:
    """Return server-owned Strategy-3 TP evidence without changing runtime state."""
    now = now or datetime.now(timezone.utc)
    scheduler = strategy3_scheduler_status(state, now=now)
    notional = _notional(row)
    target = notional * config.take_profit
    close_fee = notional * ASTER_ESTIMATED_CLOSE_FEE_RATE
    ownership = bool(owned and owned.strategy_id == "aster-strategy-3" and owned.engine_type == "strategy3")
    evidence_age = None
    if owned and owned.costs_updated_at_ms:
        evidence_age = max(0.0, now.timestamp() - owned.costs_updated_at_ms / 1000)
    costs_fresh = evidence_age is not None and evidence_age <= STRATEGY3_COST_EVIDENCE_MAX_AGE_SECONDS
    phase = str(state.get("phase", "UNKNOWN"))

    block = ""
    if not ownership:
        block = "Geen bewezen Strategy-3-ownership"
    elif not costs_fresh:
        block = "Fees en funding zijn niet recent genoeg door Aster bevestigd"

    reliable = not bool(block)
    gross = number(row.get("unrealizedPnl", row.get("unRealizedProfit")))
    net_profit_usd = (gross + (owned.funding if owned else 0) - (owned.fees if owned else 0) - close_fee) if reliable else None
    status = "Niet betrouwbaar te bepalen"
    decision_kind = "HOLD"
    decision_reason = block
    result_return = None

    if reliable and owned is not None:
        status = "TP bereikt" if net_profit_usd is not None and net_profit_usd >= target else "TP nog niet bereikt"
    if reliable and owned is not None and portfolio is not None:
        leg = LegState(
            owned.side, notional, number(row.get("entryPrice")) or owned.weighted_entry,
            number(row.get("markPrice")), owned.dca_count, gross, owned.fees, owned.funding,
            owned.role, trailing_peak_return,
        )
        result_return = net_return(leg, close_fee)
        decision = decide(config, leg, portfolio, close_fee)
        decision_kind = decision.kind
        decision_reason = decision.reason
        if status == "TP bereikt":
            if config.mode != "live":
                decision_reason = "TP bereikt, maar de opgeslagen Strategy-3-modus is paper"
            elif not bool(state.get("monitor")):
                decision_reason = "TP bereikt, maar Strategy-3-monitoring staat uit"
            elif not bool(state.get("enabled")):
                decision_reason = "TP bereikt, maar Strategy 3 staat veilig gestopt"
            elif not bool(state.get("liveReady")) or not bool(state.get("canaryValidated")):
                decision_reason = "TP bereikt, maar liveReady/canaryValidated is niet volledig bewezen"
            elif state.get("runtimeEnabled") is False:
                decision_reason = "TP bereikt, maar de centrale Strategy-3-runtimepoort staat uit"
            elif phase.upper() in {"DATA_HOLD", "RECONCILING", "CANARY_HOLD"}:
                decision_reason = str(state.get("lastReason") or f"Strategy 3 staat in {phase}")
    elif reliable and owned is not None and portfolio is None:
        decision_reason = ("Netto TP is betrouwbaar bereikt, maar protection/trailing kan niet worden beoordeeld "
            "omdat de actuele Strategy-3-portfoliostaat ontbreekt" if status == "TP bereikt" else
            "TP nog niet bereikt; ontbrekende portfoliostaat blokkeert alleen protection/trailing")

    progress = (net_profit_usd / target * 100) if reliable and net_profit_usd is not None and target > 0 else None
    evaluated_at = (datetime.fromtimestamp(owned.costs_updated_at_ms / 1000, tz=timezone.utc).isoformat()
        if owned and owned.costs_updated_at_ms else None)
    side = owned.side if owned else str(row.get("side", row.get("positionSide", ""))).upper()
    peak = trailing_peak_return if trailing_peak_return is not None else None
    trailing_active = bool(config.trailing_enabled and (peak is not None or decision_kind in {"ARM_TRAILING", "TRAILING_TP"}))

    return {
        "netProfitUsd": net_profit_usd,
        "takeProfitTargetUsd": target if ownership else None,
        "takeProfitPercent": config.take_profit * 100 if ownership else None,
        "progressPercent": progress,
        "status": status,
        "evaluatedAt": evaluated_at,
        "blockReason": decision_reason,
        "scheduler": scheduler,
        "ownershipProven": ownership,
        "paidFeesUsd": owned.fees if reliable and owned else None,
        "fundingUsd": owned.funding if reliable and owned else None,
        "estimatedCloseFeeUsd": close_fee if reliable else None,
        "costEvidenceAgeSeconds": round(evidence_age, 1) if evidence_age is not None else None,
        "decision": decision_kind,
        "phase": phase,
        "protection": {"role": owned.role if ownership and owned else None,
            "active": bool(ownership and owned and owned.role in {"PROTECTION", "HARVEST_PROTECTION"})},
        "trailing": {"enabled": config.trailing_enabled, "active": trailing_active,
            "peakReturnPercent": peak * 100 if peak is not None else None,
            "activationPercent": config.trailing_activation * 100,
            "distancePercent": trailing_distance(config, side) * 100 if side in {"LONG", "SHORT"} else None,
            "netReturnPercent": result_return * 100 if result_return is not None else None},
    }
