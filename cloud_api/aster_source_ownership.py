"""Fail-closed ownership recovery from the established account-status source.

The isolated Strategy-2 test runtime intentionally has its own Firestore.  A
user can therefore have proven production ownership while the test copy is
empty.  This module accepts evidence only when the authenticated source says
the complete account snapshot is fresh, internally consistent, conflict-free
and browser-independent, and the source position exactly matches the current
Aster exchange position.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from aster_strategy2_state import OwnedLeg, number


@dataclass(frozen=True)
class SourceOwnershipEvidence:
    strategy2_legs: tuple[OwnedLeg, ...]
    strategy3_legs: tuple[OwnedLeg, ...]
    accepted: bool
    reason: str


def _active(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for row in rows:
        symbol = str(row.get("symbol", "")).upper()
        side = str(row.get("positionSide", row.get("side", ""))).upper()
        quantity = abs(number(row.get("positionAmt", row.get("quantity"))))
        if symbol and side in {"LONG", "SHORT"} and quantity > 0:
            result[(symbol, side)] = row
    return result


def _role(row: dict[str, Any], strategy_id: str) -> str:
    contract = row.get("strategy2Tp" if strategy_id == "aster-strategy-2" else "strategy3Tp")
    protection = contract.get("protection") if isinstance(contract, dict) else None
    role = str(protection.get("role", "HARVEST")) if isinstance(protection, dict) else "HARVEST"
    return role if role in {"HARVEST", "PROTECTION", "HARVEST_PROTECTION"} else "HARVEST"


def matching_source_ownership(*, current_positions: list[dict[str, Any]], source_status: dict[str, Any],
                              config_version: int = 1) -> SourceOwnershipEvidence:
    dashboard = source_status.get("botStatusDashboard")
    evidence = dashboard.get("evidence") if isinstance(dashboard, dict) else None
    safe = (
        source_status.get("configured") is True
        and source_status.get("credentialsVerified") is True
        and isinstance(dashboard, dict)
        and dashboard.get("dataFresh") is True
        and isinstance(evidence, dict)
        and evidence.get("accountCountsConsistent") is True
        and int(number(evidence.get("unknownOwnershipCount"))) == 0
        and int(number(evidence.get("ownershipConflictCount"))) == 0
        and evidence.get("browserDerived") is False
    )
    if not safe:
        return SourceOwnershipEvidence((), (), False, "Bronstatus bewijst geen complete conflictvrije ownership")

    current = _active(current_positions)
    source_rows = source_status.get("positions") if isinstance(source_status.get("positions"), list) else []
    source = _active([row for row in source_rows if isinstance(row, dict)])
    if set(source) != set(current):
        return SourceOwnershipEvidence((), (), False, "Bron- en Aster-positiekeys verschillen")

    strategy2: list[OwnedLeg] = []
    strategy3: list[OwnedLeg] = []
    for key, exchange_row in current.items():
        row = source[key]
        strategy_id = str(row.get("strategyId", ""))
        engine_type = "strategy2" if strategy_id == "aster-strategy-2" else "strategy3" if strategy_id == "aster-strategy-3" else ""
        if not engine_type:
            return SourceOwnershipEvidence((), (), False, f"{key[0]} {key[1]} heeft geen expliciet bronlabel")
        exchange_quantity = abs(number(exchange_row.get("positionAmt", exchange_row.get("quantity"))))
        source_quantity = abs(number(row.get("quantity", row.get("positionAmt"))))
        exchange_entry = number(exchange_row.get("entryPrice"))
        source_entry = number(row.get("entryPrice"))
        if (source_quantity <= 0 or source_entry <= 0
                or not math.isclose(source_quantity, exchange_quantity, rel_tol=1e-7, abs_tol=1e-8)
                or not math.isclose(source_entry, exchange_entry, rel_tol=1e-7, abs_tol=1e-8)):
            return SourceOwnershipEvidence((), (), False, f"{key[0]} {key[1]} wijkt af van actuele Aster-state")
        opened_at = int(number(row.get("openedAt")))
        last_order_at = int(number(row.get("lastOrderAt")))
        leg = OwnedLeg(
            strategy_id=strategy_id, engine_type=engine_type, symbol=key[0], side=key[1],
            cycle_id=f"source-status-{key[0]}-{key[1]}-{opened_at or last_order_at}",
            config_version=max(1, int(config_version)), quantity=exchange_quantity,
            weighted_entry=exchange_entry, dca_count=max(0, int(number(row.get("dcaCount")))),
            role=_role(row, strategy_id), created_at_ms=opened_at,
            last_order_at_ms=max(opened_at, last_order_at),
        )
        (strategy2 if engine_type == "strategy2" else strategy3).append(leg)
    return SourceOwnershipEvidence(tuple(strategy2), tuple(strategy3), True, "Bronownership en actuele Aster-state komen exact overeen")
