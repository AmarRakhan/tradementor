"""Pure, order-free proof helpers for exclusive Strategy-2 ownership handoff."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from aster_strategy2_runtime import active_position_map, owned_to_mapping
from aster_strategy2_state import OwnedLeg, number


@dataclass(frozen=True)
class HandoffProof:
    active_keys: frozenset[tuple[str, str]]
    owned_legs: tuple[OwnedLeg, ...]
    missing_keys: tuple[tuple[str, str], ...]
    open_order_count: int
    snapshot_fingerprint: str

    @property
    def complete(self) -> bool:
        return not self.missing_keys and self.open_order_count == 0 and len(self.owned_legs) == len(self.active_keys)


def _fill_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("symbol", "")).upper(), str(row.get("positionSide", "")).upper()


def _valid_fill(row: dict[str, Any]) -> bool:
    return bool(str(row.get("id", row.get("tradeId", ""))).strip()) and number(
        row.get("qty", row.get("quantity", row.get("executedQty")))
    ) > 0 and number(row.get("price")) > 0


def _direction(row: dict[str, Any]) -> str:
    side = str(row.get("side", "")).upper()
    if side in {"BUY", "SELL"}:
        return side
    buyer = row.get("buyer")
    return "BUY" if buyer is True else "SELL" if buyer is False else ""


def _current_cycle_fills(key: tuple[str, str], rows: list[dict[str, Any]], expected_quantity: float) -> list[dict[str, Any]]:
    """Reconstruct the still-open hedge leg from all fills after its last flat point."""
    ordered = sorted(rows, key=lambda row: (int(number(row.get("time", row.get("timestamp")))),
        str(row.get("id", row.get("tradeId", "")))))
    running = 0.0
    cycle: list[dict[str, Any]] = []
    for row in ordered:
        direction = _direction(row)
        if not direction:
            return []
        opens = direction == ("BUY" if key[1] == "LONG" else "SELL")
        quantity = number(row.get("qty", row.get("quantity", row.get("executedQty"))))
        running += quantity if opens else -quantity
        if running < -1e-8:
            return []
        cycle.append(row)
        if abs(running) <= 1e-8:
            running = 0.0
            cycle = []
    tolerance = max(1e-8, expected_quantity * 1e-7)
    return cycle if cycle and abs(running - expected_quantity) <= tolerance else []


def build_handoff_proof(*, positions: list[dict[str, Any]], open_orders: list[dict[str, Any]],
                        fills: list[dict[str, Any]], config_version: int,
                        captured_at_ms: int) -> HandoffProof:
    """Prove every current exchange leg from the complete available fill set."""
    active = active_position_map(positions)
    fills_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    seen_fills: set[tuple[str, str, str]] = set()
    for row in fills:
        if _valid_fill(row):
            key = _fill_key(row)
            fill_id = str(row.get("id", row.get("tradeId", "")))
            identity = (key[0], key[1], fill_id)
            # Paginated exchange history can repeat a boundary fill.  It is one
            # exchange event and must not be counted twice in reconstruction.
            if identity in seen_fills:
                continue
            seen_fills.add(identity)
            fills_by_key.setdefault(key, []).append(row)
    missing: list[tuple[str, str]] = []
    owned: list[OwnedLeg] = []
    for key, position in sorted(active.items()):
        expected_quantity = abs(number(position.get("positionAmt")))
        evidence = _current_cycle_fills(key, fills_by_key.get(key, []), expected_quantity)
        if not evidence:
            missing.append(key)
            continue
        evidence.sort(key=lambda row: int(number(row.get("time", row.get("timestamp")))))
        first, last = evidence[0], evidence[-1]
        first_ms = int(number(first.get("time", first.get("timestamp"))))
        fill_ids = tuple(dict.fromkeys(str(row.get("id", row.get("tradeId"))) for row in evidence))
        owned.append(OwnedLeg(
            strategy_id="aster-strategy-2", engine_type="strategy2", symbol=key[0], side=key[1],
            cycle_id=f"exclusive-handoff-{key[0].lower()}-{key[1].lower()}-{first_ms}",
            config_version=max(1, int(config_version)),
            quantity=expected_quantity, weighted_entry=number(position.get("entryPrice")),
            role="HARVEST", fill_ids=fill_ids, created_at_ms=first_ms,
            last_order_at_ms=int(number(last.get("time", last.get("timestamp")))),
        ))
    # Bind confirmation to the mutable account state that could make a handoff
    # unsafe: active leg identity/quantity and open orders.  Opening fills are
    # fully re-proven on POST, but their pagination and aggregation are not part
    # of the fingerprint because Aster can return equivalent evidence in a
    # different shape between the diagnostic GET and confirmation POST.
    canonical = {
        "positions": [{"symbol": key[0], "side": key[1],
            "quantity": abs(number(row.get("positionAmt")))}
            for key, row in sorted(active.items())],
        "openOrders": sorted(str(row.get("orderId", row.get("clientOrderId", ""))) for row in open_orders),
    }
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return HandoffProof(frozenset(active), tuple(owned), tuple(missing), len(open_orders), fingerprint)


def proof_public(proof: HandoffProof) -> dict[str, Any]:
    long_count = sum(key[1] == "LONG" for key in proof.active_keys)
    short_count = sum(key[1] == "SHORT" for key in proof.active_keys)
    return {"activeLegs": len(proof.active_keys), "longLegs": long_count, "shortLegs": short_count,
        "provenLegs": len(proof.owned_legs), "missingOpeningFills": len(proof.missing_keys),
        "openOrders": proof.open_order_count, "snapshotFingerprint": proof.snapshot_fingerprint,
        "allActiveLegsProven": proof.complete}


def ownership_rows(proof: HandoffProof) -> list[dict[str, Any]]:
    return [owned_to_mapping(leg) for leg in proof.owned_legs]
