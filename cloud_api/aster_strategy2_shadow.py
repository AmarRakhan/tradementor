"""Strictly pure Strategy-2 queue shadow planning.

The live adapter must finish ownership, exchange, cost and contract validation
before constructing ``ShadowInputs``.  This module has no database, clock,
network or exchange client dependency and cannot submit or persist anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from aster_strategy2 import Strategy2Config, decide_leg
from aster_strategy2_queue import (
    PendingReopen,
    QueueAction,
    QueueState,
    build_reopen,
    build_shadow_plan,
)
from aster_strategy2_runtime import (
    active_position_map,
    estimated_close_fee,
    leg_projection,
    next_balanced_entry_side,
    portfolio_protection_decision,
)
from aster_strategy2_state import OwnedLeg
from aster_strategy2 import PortfolioState


class ShadowMutationBlocked(RuntimeError):
    """Raised whenever a shadow adapter attempts an external side effect."""


class ReadOnlyShadowBoundary:
    """Fail-closed boundary supplied to every future exchange shadow adapter."""

    def persist(self, *_args, **_kwargs) -> None:
        raise ShadowMutationBlocked("Strategy-2 shadow mag niets duurzaam opslaan")

    def submit_order(self, *_args, **_kwargs) -> None:
        raise ShadowMutationBlocked("Strategy-2 shadow mag geen Aster-order versturen")

    def change_leverage(self, *_args, **_kwargs) -> None:
        raise ShadowMutationBlocked("Strategy-2 shadow mag contractleverage niet wijzigen")


@dataclass(frozen=True)
class ShadowInputs:
    account_uid: str
    scan_id: str
    config: Strategy2Config
    portfolio: PortfolioState
    owned: tuple[OwnedLeg, ...]
    positions: tuple[dict, ...]
    pending_reopens: tuple[PendingReopen, ...] = ()
    entry_symbols: tuple[str, ...] = ()
    orders_used: int = 0
    halted_uncertain: bool = False
    close_evidence_keys: frozenset[tuple[str, str]] | None = None
    ownership_isolated: bool = False


def _management_actions(value: ShadowInputs) -> tuple[list[QueueAction], list[QueueAction]]:
    profits: list[QueueAction] = []
    dca: list[QueueAction] = []
    positions = active_position_map(list(value.positions))
    for sequence, leg in enumerate(value.owned):
        row = positions.get((leg.symbol, leg.side))
        if row is None:
            continue
        decision = decide_leg(
            value.config,
            leg_projection(leg, row),
            value.portfolio,
            estimated_close_fee=estimated_close_fee(row),
        )
        if decision.kind in {"FULL_TP", "PARTIAL_TP"}:
            key = (leg.symbol, leg.side)
            if (value.close_evidence_keys is not None
                    and key not in value.close_evidence_keys):
                continue
            profits.append(QueueAction(
                "TAKE_PROFIT_CLOSE", leg.symbol, leg.side, leg.cycle_id,
                notional=decision.notional, reason=decision.reason, sequence=sequence,
            ))
        elif decision.kind == "ADD_DCA":
            dca.append(QueueAction(
                "DCA", leg.symbol, leg.side, leg.cycle_id,
                notional=decision.notional, reason=decision.reason, sequence=sequence,
            ))
    return profits, dca


def _entry_actions(value: ShadowInputs) -> list[QueueAction]:
    simulated = list(value.owned)
    result: list[QueueAction] = []
    for sequence, symbol in enumerate(dict.fromkeys(x.upper() for x in value.entry_symbols if x)):
        side = next_balanced_entry_side(simulated, value.config.maximum_pairs,*value.config.entry_targets)
        if not side:
            break
        result.append(QueueAction(
            "OPEN_BASE", symbol, side, f"shadow-entry-{sequence}",
            notional=value.config.base_notional, reason="Geldige vrije basisinstap",
            sequence=sequence,
        ))
        simulated.append(OwnedLeg(
            value.config.strategy_id, "strategy2", symbol, side,
            f"shadow-entry-{sequence}", value.config.version, 1.0, 1.0,
        ))
    return result


def plan_validated_shadow(value: ShadowInputs) -> dict:
    """Plan at most 15 actions without mutating inputs or external state."""
    risk: list[QueueAction] = []
    protection = portfolio_protection_decision(
        value.config, value.portfolio, list(value.owned)
    )
    if protection:
        leg, decision = protection
        risk.append(QueueAction(
            "RISK_REDUCE", leg.symbol, leg.side, leg.cycle_id,
            notional=decision.notional, reason=decision.reason,
        ))
    profits, dca = _management_actions(value)
    # Mirror the live per-leg isolation boundary: an ownership mismatch may
    # never increase exposure, but exact proven legs remain closable.
    if value.ownership_isolated:
        dca = []
        pending = []
        entries = []
    else:
        pending = [build_reopen(item, sequence=index)
                   for index, item in enumerate(value.pending_reopens)]
        entries = _entry_actions(value)
    state = QueueState(
        value.account_uid, value.scan_id,
        orders_used=value.orders_used,
        halted_uncertain=value.halted_uncertain,
    )
    result = build_shadow_plan(
        state=state, risk=risk, profits=profits,
        pending_reopens=pending, dca=dca, entries=entries,
    )
    result["validatedInput"] = True
    result["externalWrites"] = 0
    result["exchangeSubmissions"] = 0
    return result
