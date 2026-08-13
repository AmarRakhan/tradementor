"""Fail-safe Hyperliquid migration and reconciliation primitives.

This module deliberately has no network, Firestore or order side effects. It
turns read-only snapshots into an auditable migration decision. Exchange
state is authoritative; a mismatch may be reconciled, but it may never be
used as permission to increase exposure before the repaired state is stored
and read back successfully.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from typing import Any, Iterable, Literal


MigrationStatus = Literal["READY", "SYNC_REQUIRED", "PAUSED"]


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True, order=True)
class PositionRecord:
    symbol: str
    side: str
    size: float
    entry_price: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "PositionRecord":
        signed_size = _finite(
            raw.get("size", raw.get("szi", raw.get("quantity", raw.get("positionAmt", 0))))
        )
        side = _text(raw.get("side", raw.get("positionSide"))).lower()
        if side not in {"long", "short"}:
            side = "short" if signed_size < 0 else "long"
        return cls(
            symbol=_text(raw.get("symbol", raw.get("coin"))).upper(),
            side=side,
            size=abs(signed_size),
            entry_price=_finite(
                raw.get("entryPrice", raw.get("entry_price", raw.get("averageEntry", 0)))
            ),
        )

    @property
    def identity(self) -> tuple[str, str]:
        return self.symbol, self.side


@dataclass(frozen=True, order=True)
class OrderRecord:
    order_id: str
    symbol: str
    side: str
    size: float
    reduce_only: bool

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "OrderRecord":
        return cls(
            order_id=_text(raw.get("orderId", raw.get("oid", raw.get("cloid")))),
            symbol=_text(raw.get("symbol", raw.get("coin"))).upper(),
            side=_text(raw.get("side", raw.get("dir"))).lower(),
            size=abs(_finite(raw.get("size", raw.get("sz", raw.get("origQty", 0))))),
            reduce_only=bool(raw.get("reduceOnly", raw.get("reduce_only", False))),
        )


@dataclass(frozen=True)
class ReconciliationSnapshot:
    source: str
    account_id: str
    captured_at_ms: int
    positions: tuple[PositionRecord, ...] = ()
    open_orders: tuple[OrderRecord, ...] = ()
    fill_ids: tuple[str, ...] = ()
    settings: dict[str, Any] = field(default_factory=dict)
    cycle_state: dict[str, Any] = field(default_factory=dict)
    enabled: bool | None = None
    enabled_updated_at_ms: int = 0

    @classmethod
    def from_mapping(cls, source: str, raw: dict[str, Any]) -> "ReconciliationSnapshot":
        positions = tuple(sorted(
            (
                PositionRecord.from_mapping(item)
                for item in raw.get("positions", ())
                if isinstance(item, dict)
            ),
            key=lambda item: item.identity,
        ))
        orders = tuple(sorted(
            (
                OrderRecord.from_mapping(item)
                for item in raw.get("openOrders", raw.get("open_orders", ()))
                if isinstance(item, dict)
            ),
            key=lambda item: (item.order_id, item.symbol, item.side),
        ))
        fill_ids = tuple(sorted(
            _text(item.get("id", item.get("tid", item.get("hash"))))
            if isinstance(item, dict) else _text(item)
            for item in raw.get("fills", raw.get("fillIds", ()))
        ))
        enabled_raw = raw.get("enabled")
        return cls(
            source=source,
            account_id=_text(raw.get("accountId", raw.get("address"))).lower(),
            captured_at_ms=int(_finite(raw.get("capturedAtMs", raw.get("captured_at_ms", 0)))),
            positions=positions,
            open_orders=orders,
            fill_ids=fill_ids,
            settings=dict(raw.get("settings") or {}),
            cycle_state=dict(raw.get("cycleState", raw.get("cycle_state")) or {}),
            enabled=enabled_raw if isinstance(enabled_raw, bool) else None,
            enabled_updated_at_ms=int(_finite(raw.get("enabledUpdatedAtMs", 0))),
        )

    def canonical_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("source", None)
        return payload

    def digest(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MigrationDecision:
    status: MigrationStatus
    allow_risk_increase: bool
    effective_enabled: bool
    authoritative_snapshot: ReconciliationSnapshot | None
    reasons: tuple[str, ...]
    repair_targets: tuple[str, ...] = ()


def _positions_match(
    exchange: Iterable[PositionRecord], other: Iterable[PositionRecord], tolerance: float
) -> bool:
    left = list(exchange)
    right = list(other)
    if len(left) != len(right):
        return False
    for expected, actual in zip(left, right):
        if expected.identity != actual.identity:
            return False
        if not math.isclose(expected.size, actual.size, rel_tol=tolerance, abs_tol=tolerance):
            return False
        if expected.size and not math.isclose(
            expected.entry_price, actual.entry_price, rel_tol=tolerance, abs_tol=tolerance
        ):
            return False
    return True


def _orders_match(exchange: Iterable[OrderRecord], other: Iterable[OrderRecord]) -> bool:
    return list(exchange) == list(other)


def _trusted_enabled(snapshots: Iterable[ReconciliationSnapshot]) -> tuple[bool, str | None]:
    candidates = [item for item in snapshots if item.enabled is not None]
    if not candidates:
        return False, "Geen betrouwbare enabled-status gevonden; veilig UIT gehouden"
    newest_time = max(item.enabled_updated_at_ms for item in candidates)
    newest = [item for item in candidates if item.enabled_updated_at_ms == newest_time]
    values = {item.enabled for item in newest}
    if len(values) != 1:
        return False, "Tegenstrijdige enabled-status met gelijke tijd; handmatige controle vereist"
    return bool(next(iter(values))), None


def assess_migration(
    *,
    exchange: ReconciliationSnapshot | None,
    cloud: ReconciliationSnapshot | None,
    local: ReconciliationSnapshot | None,
    exchange_read_ok: bool,
    state_round_trip_verified: bool = False,
    numeric_tolerance: float = 1e-8,
) -> MigrationDecision:
    """Return a safe decision; never mutate any supplied state.

    ``state_round_trip_verified`` means the exchange-authoritative repair was
    written to persistent storage and read back with the same digest. Until
    that is true, a mismatch remains blocked for risk-increasing actions.
    """
    if not exchange_read_ok or exchange is None:
        return MigrationDecision(
            status="PAUSED",
            allow_risk_increase=False,
            effective_enabled=False,
            authoritative_snapshot=None,
            reasons=("Hyperliquid kon niet betrouwbaar worden gelezen",),
        )

    snapshots = [item for item in (cloud, local) if item is not None]
    enabled, enabled_problem = _trusted_enabled(snapshots)
    reasons: list[str] = []
    repairs: list[str] = []
    if enabled_problem:
        reasons.append(enabled_problem)

    for name, snapshot in (("cloud", cloud), ("local", local)):
        if snapshot is None:
            reasons.append(f"{name.capitalize()}-snapshot ontbreekt")
            repairs.append(name)
            continue
        if snapshot.account_id != exchange.account_id:
            reasons.append(f"{name.capitalize()}-account wijkt af van Hyperliquid")
            repairs.append(name)
            continue
        if not _positions_match(exchange.positions, snapshot.positions, numeric_tolerance):
            reasons.append(f"{name.capitalize()}-posities lopen niet gelijk met Hyperliquid")
            repairs.append(name)
        if not _orders_match(exchange.open_orders, snapshot.open_orders):
            reasons.append(f"{name.capitalize()}-orders lopen niet gelijk met Hyperliquid")
            repairs.append(name)

    repairs = list(dict.fromkeys(repairs))
    if repairs and not state_round_trip_verified:
        return MigrationDecision(
            status="SYNC_REQUIRED",
            allow_risk_increase=False,
            effective_enabled=False,
            authoritative_snapshot=exchange,
            reasons=tuple(reasons),
            repair_targets=tuple(repairs),
        )

    if enabled_problem:
        return MigrationDecision(
            status="PAUSED",
            allow_risk_increase=False,
            effective_enabled=False,
            authoritative_snapshot=exchange,
            reasons=tuple(reasons),
            repair_targets=tuple(repairs),
        )

    if repairs:
        reasons.append("Exchange-state is opgeslagen en exact teruggelezen")
    return MigrationDecision(
        status="READY",
        allow_risk_increase=enabled,
        effective_enabled=enabled,
        authoritative_snapshot=exchange,
        reasons=tuple(reasons or ("Alle migratiecontroles zijn gelijk",)),
        repair_targets=tuple(repairs),
    )

