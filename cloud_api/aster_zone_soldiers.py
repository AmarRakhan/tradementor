"""Zone-owned soldier state for Aster Multi-BB.

This module is deliberately pure.  It owns no exchange client and never submits,
closes or cancels an order.  It projects persistent per-zone soldier pools from
confirmed Strategy-2 ownership and exchange position truth.

Design invariants:
- each price zone owns its own LONG and SHORT base soldiers;
- only the confirmed active zone exposes free soldiers for NEW entries;
- OPEN soldiers remain OPEN when their origin zone becomes inactive;
- a soldier released while its origin zone is inactive becomes DORMANT;
- legacy positions are never guessed into a zone;
- exposure balancing only prioritizes which existing base side may enter next;
- all entry/exit/DCA execution remains in the existing Multi-BB runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import hashlib
import math

SCHEMA_VERSION = 2
ROLE_ZONE_BASE = "ZONE_BASE"
ROLE_EXPOSURE_BALANCER = "EXPOSURE_BALANCER"
ROLE_LEGACY_UNASSIGNED = "LEGACY_UNASSIGNED"

STATUS_AVAILABLE = "AVAILABLE_ACTIVE_ZONE"
STATUS_OPEN = "OPEN"
STATUS_DORMANT = "DORMANT"
STATUS_WAITING = "WAITING_ENTRY"
STATUS_EXITING = "EXITING"
STATUS_CLOSED = "CLOSED"


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _zone_key(zone: int) -> str:
    return str(int(zone))


def _activation_id(zone: int, timestamp_ms: int) -> str:
    return hashlib.sha256(f"zone|{int(zone)}|{int(timestamp_ms)}".encode()).hexdigest()[:16]


def _pool_cycle_id(zone: int, timestamp_ms: int) -> str:
    return hashlib.sha256(f"zone-pool|{int(zone)}|{int(timestamp_ms)}".encode()).hexdigest()[:16]


def _base_soldier_id(zone: int, side: str, ordinal: int) -> str:
    sign = f"p{zone}" if zone > 0 else f"n{abs(zone)}" if zone < 0 else "z0"
    return f"{sign}:{side.lower()}:base:{ordinal}"


def _balancer_soldier_id(zone: int, side: str, ordinal: int) -> str:
    sign = f"p{zone}" if zone > 0 else f"n{abs(zone)}" if zone < 0 else "z0"
    return f"{sign}:{side.lower()}:bal:{ordinal}"


def _clean_soldier(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    soldier_id = str(raw.get("soldierId", "")).strip()
    side = str(raw.get("side", "")).upper()
    role = str(raw.get("role", ROLE_ZONE_BASE)).upper()
    status = str(raw.get("status", STATUS_DORMANT)).upper()
    if not soldier_id or side not in {"LONG", "SHORT"}:
        return None
    if role not in {ROLE_ZONE_BASE, ROLE_EXPOSURE_BALANCER}:
        role = ROLE_ZONE_BASE
    if status not in {STATUS_AVAILABLE, STATUS_OPEN, STATUS_DORMANT, STATUS_WAITING, STATUS_EXITING, STATUS_CLOSED}:
        status = STATUS_DORMANT
    return {
        "soldierId": soldier_id,
        "side": side,
        "role": role,
        "status": status,
        "originZone": _integer(raw.get("originZone")),
        "originZoneCycleId": str(raw.get("originZoneCycleId", "")),
        "tradeKey": str(raw.get("tradeKey", "")),
        "symbol": str(raw.get("symbol", "")).upper(),
        "openedAtMs": max(0, _integer(raw.get("openedAtMs"))),
        "entryPrice": max(0.0, _number(raw.get("entryPrice"))),
        "entryPortfolioEquity": max(0.0, _number(raw.get("entryPortfolioEquity"))),
        "updatedAtMs": max(0, _integer(raw.get("updatedAtMs"))),
    }



def _clean_homecoming_events(raw: Any) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    by_id: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        closed_at = max(0, _integer(item.get("closedAtMs")))
        side = str(item.get("side", "")).upper()
        role = str(item.get("soldierRole", item.get("role", ""))).upper()
        soldier_id = str(item.get("soldierId", "")).strip()
        if closed_at <= 0 or side not in {"LONG", "SHORT"} or role not in {ROLE_ZONE_BASE, ROLE_EXPOSURE_BALANCER}:
            continue
        origin_raw = item.get("originZone")
        try:
            origin_zone = int(origin_raw) if origin_raw is not None else None
        except (TypeError, ValueError):
            origin_zone = None
        event_id = str(item.get("eventId", "")).strip() or f"{soldier_id or side}:{closed_at}"
        by_id[event_id] = {
            "eventId": event_id,
            "closedAtMs": closed_at,
            "side": side,
            "originZone": origin_zone,
            "soldierId": soldier_id,
            "soldierRole": role,
            "reason": "TP_WIN",
        }
    return sorted(by_id.values(), key=lambda row: (row["closedAtMs"], row["eventId"]))[-512:]


def _clean_pool(raw: Any, zone: int, *, base_long: int, base_short: int, timestamp_ms: int) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    created_at = max(0, _integer(source.get("createdAtMs"))) or timestamp_ms
    cycle_id = str(source.get("originZoneCycleId", "")).strip() or _pool_cycle_id(zone, created_at)
    soldiers: dict[str, dict[str, Any]] = {}
    raw_soldiers = source.get("soldiers")
    if isinstance(raw_soldiers, dict):
        rows = raw_soldiers.values()
    elif isinstance(raw_soldiers, list):
        rows = raw_soldiers
    else:
        rows = ()
    for item in rows:
        soldier = _clean_soldier(item)
        if soldier is not None:
            # Historical balancer soldiers may remain OPEN until their normal
            # profitable close, but flat balancer capacity is never reused.
            if (
                soldier["role"] == ROLE_EXPOSURE_BALANCER
                and soldier["status"] not in {STATUS_OPEN, STATUS_EXITING}
                and not soldier.get("tradeKey")
            ):
                continue
            soldier["originZone"] = zone
            soldier["originZoneCycleId"] = cycle_id
            soldiers[soldier["soldierId"]] = soldier

    def ensure_base(side: str, amount: int) -> None:
        for ordinal in range(1, max(0, amount) + 1):
            soldier_id = _base_soldier_id(zone, side, ordinal)
            if soldier_id not in soldiers:
                soldiers[soldier_id] = {
                    "soldierId": soldier_id,
                    "side": side,
                    "role": ROLE_ZONE_BASE,
                    "status": STATUS_DORMANT,
                    "originZone": zone,
                    "originZoneCycleId": cycle_id,
                    "tradeKey": "",
                    "symbol": "",
                    "openedAtMs": 0,
                    "entryPrice": 0.0,
                    "entryPortfolioEquity": 0.0,
                    "updatedAtMs": timestamp_ms,
                }

    ensure_base("LONG", base_long)
    ensure_base("SHORT", base_short)
    return {
        "zone": zone,
        "originZoneCycleId": cycle_id,
        "createdAtMs": created_at,
        "lastActivatedAtMs": max(0, _integer(source.get("lastActivatedAtMs"))),
        "activationCount": max(0, _integer(source.get("activationCount"))),
        "soldiers": soldiers,
    }


def normalize_zone_state(raw: Any, *, base_long: int, base_short: int, timestamp_ms: int) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    pools: dict[str, dict[str, Any]] = {}
    raw_pools = source.get("pools") if isinstance(source.get("pools"), dict) else {}
    for key, value in raw_pools.items():
        try:
            zone = int(key)
        except (TypeError, ValueError):
            continue
        pools[_zone_key(zone)] = _clean_pool(value, zone, base_long=base_long, base_short=base_short, timestamp_ms=timestamp_ms)
    active = source.get("activeZone")
    previous = source.get("previousZone")
    active_zone = int(active) if isinstance(active, int) or (isinstance(active, str) and active.lstrip("-+").isdigit()) else None
    previous_zone = int(previous) if isinstance(previous, int) or (isinstance(previous, str) and previous.lstrip("-+").isdigit()) else None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "ZONE_OWNED",
        "activeZone": active_zone,
        "previousZone": previous_zone,
        "zoneActivationId": str(source.get("zoneActivationId", "")),
        "activatedAtMs": max(0, _integer(source.get("activatedAtMs"))),
        "lastConfirmedZoneTransition": dict(source.get("lastConfirmedZoneTransition") or {}),
        "baseLongSoldiers": max(0, int(base_long)),
        "baseShortSoldiers": max(0, int(base_short)),
        "pools": pools,
        "balancer": dict(source.get("balancer") or {}),
        "homecomingEvents": _clean_homecoming_events(source.get("homecomingEvents")),
        "updatedAtMs": timestamp_ms,
    }


def annotate_legacy_positions(managed_state: dict[str, Any] | None, *, timestamp_ms: int) -> tuple[dict[str, Any], int]:
    """Mark pre-zone managed positions without inventing an origin zone."""
    state = {str(key): dict(value) for key, value in (managed_state or {}).items() if isinstance(value, dict)}
    migrated = 0
    for key, row in state.items():
        if row.get("soldierId") or row.get("soldierRole") in {ROLE_ZONE_BASE, ROLE_EXPOSURE_BALANCER}:
            continue
        if str(row.get("soldierRole", "")).upper() == ROLE_LEGACY_UNASSIGNED:
            continue
        row.update({
            "originZone": None,
            "originZoneCycleId": "",
            "soldierId": "",
            "soldierRole": ROLE_LEGACY_UNASSIGNED,
            "soldierStatus": STATUS_OPEN,
            "zoneOwnershipMigratedAtMs": timestamp_ms,
        })
        state[key] = row
        migrated += 1
    return state, migrated


def _median(values: list[float]) -> float | None:
    rows = sorted(value for value in values if math.isfinite(value) and value > 0)
    if not rows:
        return None
    middle = len(rows) // 2
    return rows[middle] if len(rows) % 2 else (rows[middle - 1] + rows[middle]) / 2.0


def confirmed_zone_from_display_zones(zones: list[dict[str, Any]] | None, price: float,
                                      *, min_index: int = -3, max_index: int = 3) -> int | None:
    """Mirror the web BETA extrapolated Portfolio Koers ladder.

    The backend and Formation Dashboard must never disagree about the signed
    active zone merely because the latest confirmed S/R set contains only part
    of the -3..+3 ladder.
    """
    value = _number(price)
    observed = []
    for raw in zones or []:
        if not isinstance(raw, dict):
            continue
        index = _integer(raw.get("index"), 10_000)
        center = _number(raw.get("center"))
        atr = _number(raw.get("atr"))
        if index == 10_000 or center <= 0:
            continue
        observed.append({"index": index, "center": center, "atr": atr})
    observed.sort(key=lambda row: row["index"])
    if value <= 0 or not observed:
        return None

    step_candidates: list[float] = []
    for previous, current in zip(observed, observed[1:]):
        index_gap = current["index"] - previous["index"]
        price_gap = current["center"] - previous["center"]
        if index_gap > 0 and price_gap > 0:
            step_candidates.append(price_gap / index_gap)
    observed_step = _median(step_candidates)
    atr_step = _median([row["atr"] * 1.5 for row in observed if row["atr"] > 0])
    center_median = _median([row["center"] for row in observed]) or observed[0]["center"]
    step = observed_step or max(center_median * .02, atr_step or 0.0)
    if step <= 0:
        return None

    anchor = _median([row["center"] - row["index"] * step for row in observed
                      if row["center"] - row["index"] * step > 0])
    if anchor is None or anchor <= 0:
        return None
    by_index = {row["index"]: row["center"] for row in observed}
    centers = []
    for zone_index in range(max(-12, int(min_index)), min(12, int(max_index)) + 1):
        center = by_index.get(zone_index, anchor + zone_index * step)
        if center > 0:
            centers.append((zone_index, center))
    if not centers:
        return None
    if any(centers[index][1] <= centers[index - 1][1] for index in range(1, len(centers))):
        centers = [(zone_index, anchor + zone_index * step) for zone_index, _ in centers]

    for index, (zone_index, center) in enumerate(centers):
        previous = centers[index - 1][1] if index > 0 else float("-inf")
        following = centers[index + 1][1] if index + 1 < len(centers) else float("inf")
        lower = (previous + center) / 2.0 if math.isfinite(previous) else float("-inf")
        upper = (center + following) / 2.0 if math.isfinite(following) else float("inf")
        if lower <= value < upper:
            return zone_index
    return min(centers, key=lambda item: abs(item[1] - value))[0]


def _position_map(positions: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in positions or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper()
        side = str(row.get("positionSide", "")).upper()
        qty = abs(_number(row.get("positionAmt")))
        if symbol and side in {"LONG", "SHORT"} and qty > 0:
            result[f"{symbol}|{side}"] = row
    return result


def _managed_exposure(managed_state: dict[str, Any], positions: list[dict[str, Any]] | None) -> dict[str, Any]:
    pmap = _position_map(positions)
    long_count = short_count = 0
    long_notional = short_notional = 0.0
    notionals: list[float] = []
    legacy_count = 0
    for key, state_row in managed_state.items():
        row = pmap.get(key)
        if row is None:
            continue
        side = str(row.get("positionSide", "")).upper()
        qty = abs(_number(row.get("positionAmt")))
        mark = _number(row.get("markPrice")) or _number(row.get("entryPrice"))
        notional = qty * mark if qty > 0 and mark > 0 else abs(_number(row.get("notionalUsd", row.get("notional"))))
        if notional > 0:
            notionals.append(notional)
        if side == "LONG":
            long_count += 1
            long_notional += notional
        elif side == "SHORT":
            short_count += 1
            short_notional += notional
        if str(state_row.get("soldierRole", "")).upper() == ROLE_LEGACY_UNASSIGNED:
            legacy_count += 1
    gross = long_notional + short_notional
    net = long_notional - short_notional
    side = "LONG" if net > 1e-9 else "SHORT" if net < -1e-9 else "FLAT"
    imbalance = abs(net) / gross * 100.0 if gross > 0 else 0.0
    notionals.sort()
    unit = 0.0
    if notionals:
        middle = len(notionals) // 2
        unit = notionals[middle] if len(notionals) % 2 else (notionals[middle - 1] + notionals[middle]) / 2
    return {
        "totalLongOpenCount": long_count,
        "totalShortOpenCount": short_count,
        "totalLongNotional": long_notional,
        "totalShortNotional": short_notional,
        "grossExposureUsd": gross,
        "netExposureUsd": net,
        "netExposureSide": side,
        "imbalancePercent": imbalance,
        "medianPositionNotionalUsd": unit,
        "legacyUnassignedOpenCount": legacy_count,
    }


def _balancer_plan(*, exposure: dict[str, Any], previous_side: str, enabled: bool,
                   trigger_percent: float, release_percent: float,
                   fallback_unit_notional: float) -> dict[str, Any]:
    """Return exposure ENTRY PRIORITY only; never manufacture capacity."""
    net = _number(exposure.get("netExposureUsd"))
    imbalance = max(0.0, _number(exposure.get("imbalancePercent")))
    previous = str(previous_side or "").upper()
    if previous not in {"LONG", "SHORT"}:
        previous = ""
    underweight = "SHORT" if net > 0 else "LONG" if net < 0 else ""
    active_side = ""
    if enabled and underweight:
        if previous == underweight and imbalance > max(0.0, release_percent):
            active_side = previous
        elif imbalance >= max(0.0, trigger_percent):
            active_side = underweight
    unit = max(0.0, _number(exposure.get("medianPositionNotionalUsd"))) or max(0.0, fallback_unit_notional)
    return {
        "mode": "PRIORITY_ONLY",
        "status": "BALANCED" if not active_side else f"{active_side}_UNDERWEIGHT",
        "activeSide": active_side or None,
        "prioritySide": active_side or None,
        "desiredCount": 0,
        "desiredNotionalUsd": 0.0,
        "unitNotionalUsd": unit,
        "triggerPercent": trigger_percent,
        "releasePercent": release_percent,
    }


def _ensure_balancers(pool: dict[str, Any], *, side: str, amount: int, timestamp_ms: int) -> None:
    """Deprecated compatibility shim. Build 423 never creates extra soldiers."""
    return None


def _bind_open_soldiersdef _bind_open_soldiers(zone_state: dict[str, Any], managed_state: dict[str, Any], positions: list[dict[str, Any]], *, timestamp_ms: int) -> None:
    pmap = _position_map(positions)
    bound: set[str] = set()
    pools = zone_state["pools"]
    for key, row in managed_state.items():
        soldier_id = str(row.get("soldierId", "")).strip()
        role = str(row.get("soldierRole", "")).upper()
        origin = row.get("originZone")
        if not soldier_id or role not in {ROLE_ZONE_BASE, ROLE_EXPOSURE_BALANCER} or origin is None:
            continue
        try:
            zone = int(origin)
        except (TypeError, ValueError):
            continue
        pool = pools.get(_zone_key(zone))
        if pool is None:
            continue
        soldier = pool["soldiers"].get(soldier_id)
        if soldier is None:
            continue
        if key in pmap:
            position = pmap[key]
            soldier.update({
                "status": STATUS_OPEN,
                "tradeKey": key,
                "symbol": str(position.get("symbol", "")).upper(),
                "openedAtMs": max(_integer(row.get("cycleStartedAtMs")), _integer(row.get("openedAtMs")), soldier.get("openedAtMs", 0)),
                "entryPrice": max(0.0, _number(position.get("entryPrice"))),
                "entryPortfolioEquity": max(0.0, _number(row.get("entryPortfolioEquity"))),
                "updatedAtMs": timestamp_ms,
            })
            bound.add(soldier_id)

    active_zone = zone_state.get("activeZone")
    for pool in pools.values():
        for soldier in pool["soldiers"].values():
            if soldier["soldierId"] in bound:
                continue
            if soldier.get("status") == STATUS_OPEN or soldier.get("tradeKey"):
                soldier["tradeKey"] = ""
                soldier["symbol"] = ""
                soldier["status"] = STATUS_AVAILABLE if int(pool["zone"]) == active_zone else STATUS_DORMANT
                soldier["updatedAtMs"] = timestamp_ms


def _activate_free_soldiers(zone_state: dict[str, Any], *, active_zone: int | None, balancer: dict[str, Any], timestamp_ms: int) -> None:
    for pool in zone_state["pools"].values():
        zone = int(pool["zone"])
        for soldier in pool["soldiers"].values():
            if soldier["status"] == STATUS_OPEN:
                continue
            should_activate = bool(
                active_zone is not None
                and zone == active_zone
                and soldier["role"] == ROLE_ZONE_BASE
            )
            soldier["status"] = STATUS_AVAILABLE if should_activate else STATUS_DORMANT
            soldier["updatedAtMs"] = timestamp_ms


def prepare_zone_runtimedef prepare_zone_runtime(*, raw_zone_state: Any, managed_state: dict[str, Any] | None,
                         positions: list[dict[str, Any]] | None, confirmed_zone: int | None,
                         zone_safe: bool, base_long: int, base_short: int,
                         balancer_enabled: bool, trigger_percent: float, release_percent: float,
                         fallback_unit_notional: float, timestamp_ms: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Reconcile persistent pools and return (zone_state, managed_state, report)."""
    state, migrated = annotate_legacy_positions(managed_state, timestamp_ms=timestamp_ms)
    zone_state = normalize_zone_state(raw_zone_state, base_long=base_long, base_short=base_short, timestamp_ms=timestamp_ms)
    previous_active = zone_state.get("activeZone")

    if zone_safe and confirmed_zone is not None:
        zone = int(confirmed_zone)
        key = _zone_key(zone)
        if key not in zone_state["pools"]:
            zone_state["pools"][key] = _clean_pool({}, zone, base_long=base_long, base_short=base_short, timestamp_ms=timestamp_ms)
        if previous_active != zone:
            activation = _activation_id(zone, timestamp_ms)
            pool = zone_state["pools"][key]
            pool["lastActivatedAtMs"] = timestamp_ms
            pool["activationCount"] = max(0, _integer(pool.get("activationCount"))) + 1
            zone_state.update({
                "previousZone": previous_active,
                "activeZone": zone,
                "zoneActivationId": activation,
                "activatedAtMs": timestamp_ms,
                "lastConfirmedZoneTransition": {
                    "fromZone": previous_active,
                    "toZone": zone,
                    "zoneActivationId": activation,
                    "confirmedAtMs": timestamp_ms,
                },
            })
    elif not zone_safe:
        # Fail closed for NEW entries.  Keep the last confirmed zone as history,
        # but no pool is active until continuity is restored.
        zone_state["previousZone"] = zone_state.get("activeZone")
        zone_state["activeZone"] = None

    exposure = _managed_exposure(state, positions)
    previous_balancer = dict(zone_state.get("balancer") or {})
    balancer = _balancer_plan(
        exposure=exposure,
        previous_side=str(previous_balancer.get("activeSide") or ""),
        enabled=bool(balancer_enabled and zone_safe and zone_state.get("activeZone") is not None),
        trigger_percent=trigger_percent,
        release_percent=release_percent,
        fallback_unit_notional=fallback_unit_notional,
    )
    active_zone = zone_state.get("activeZone")
    # Exposure balancing is routing/prioriteit only. It never adds seats.
    zone_state["balancer"] = {**balancer, "updatedAtMs": timestamp_ms}
    _bind_open_soldiers(zone_state, state, positions or [], timestamp_ms=timestamp_ms)
    _activate_free_soldiers(zone_state, active_zone=active_zone, balancer=balancer, timestamp_ms=timestamp_ms)
    zone_state["updatedAtMs"] = timestamp_ms
    report = zone_runtime_report(zone_state, state, positions or [], zone_safe=zone_safe)
    report["legacyMigratedThisTick"] = migrated
    return zone_state, state, report


def available_soldiers(zone_state: dict[str, Any], side: str) -> list[dict[str, Any]]:
    active_zone = zone_state.get("activeZone")
    if active_zone is None:
        return []
    pool = zone_state.get("pools", {}).get(_zone_key(int(active_zone)))
    if not isinstance(pool, dict):
        return []
    normalized = str(side).upper()
    rows = [
        soldier for soldier in pool.get("soldiers", {}).values()
        if (
            isinstance(soldier, dict)
            and soldier.get("role") == ROLE_ZONE_BASE
            and soldier.get("side") == normalized
            and soldier.get("status") == STATUS_AVAILABLE
        )
    ]
    return sorted(rows, key=lambda row: (0 if row.get("role") == ROLE_ZONE_BASE else 1, str(row.get("soldierId"))))


def claim_soldier(zone_state: dict[str, Any], side: str, *, trade_key: str, symbol: str,
                  entry_price: float, entry_portfolio_equity: float, timestamp_ms: int) -> dict[str, Any] | None:
    rows = available_soldiers(zone_state, side)
    if not rows:
        return None
    soldier = rows[0]
    soldier.update({
        "status": STATUS_OPEN,
        "tradeKey": trade_key,
        "symbol": str(symbol).upper(),
        "openedAtMs": timestamp_ms,
        "entryPrice": max(0.0, _number(entry_price)),
        "entryPortfolioEquity": max(0.0, _number(entry_portfolio_equity)),
        "updatedAtMs": timestamp_ms,
    })
    return dict(soldier)


def record_soldier_homecoming(zone_state: dict[str, Any], managed_row: dict[str, Any], *,
                               side: str, timestamp_ms: int) -> bool:
    """Record one exchange-confirmed profitable zone-soldier TP close."""
    role = str((managed_row or {}).get("soldierRole", "")).upper()
    soldier_id = str((managed_row or {}).get("soldierId", "")).strip()
    normalized_side = str(side or "").upper()
    if role not in {ROLE_ZONE_BASE, ROLE_EXPOSURE_BALANCER} or not soldier_id or normalized_side not in {"LONG", "SHORT"}:
        return False
    origin_raw = (managed_row or {}).get("originZone")
    try:
        origin_zone = int(origin_raw) if origin_raw is not None else None
    except (TypeError, ValueError):
        origin_zone = None
    event_id = f"{soldier_id}:{int(timestamp_ms)}"
    events = _clean_homecoming_events(zone_state.get("homecomingEvents"))
    if any(row.get("eventId") == event_id for row in events):
        return False
    events.append({
        "eventId": event_id, "closedAtMs": int(timestamp_ms), "side": normalized_side,
        "originZone": origin_zone, "soldierId": soldier_id, "soldierRole": role, "reason": "TP_WIN",
    })
    zone_state["homecomingEvents"] = _clean_homecoming_events(events)
    zone_state["updatedAtMs"] = max(_integer(zone_state.get("updatedAtMs")), int(timestamp_ms))
    return True


def zone_runtime_report(zone_state: dict[str, Any], managed_state: dict[str, Any],
                        positions: list[dict[str, Any]], *, zone_safe: bool) -> dict[str, Any]:
    active_zone = zone_state.get("activeZone")
    pools = zone_state.get("pools", {}) if isinstance(zone_state.get("pools"), dict) else {}
    current = pools.get(_zone_key(int(active_zone))) if active_zone is not None else None
    current = current if isinstance(current, dict) else {"soldiers": {}}
    soldiers = list(current.get("soldiers", {}).values()) if isinstance(current.get("soldiers"), dict) else []

    def count_current(side: str, *, role: str | None = None, status: str | None = None) -> int:
        return sum(1 for soldier in soldiers if isinstance(soldier, dict)
                   and soldier.get("side") == side
                   and (role is None or soldier.get("role") == role)
                   and (status is None or soldier.get("status") == status))

    pmap = _position_map(positions)
    old_open_long = old_open_short = 0
    for key, row in managed_state.items():
        if str(row.get("soldierRole", "")).upper() not in {ROLE_ZONE_BASE, ROLE_EXPOSURE_BALANCER}:
            continue
        if key not in pmap:
            continue
        origin = row.get("originZone")
        if active_zone is not None and origin is not None and int(origin) == int(active_zone):
            continue
        if key.endswith("|LONG"):
            old_open_long += 1
        elif key.endswith("|SHORT"):
            old_open_short += 1

    exposure = _managed_exposure(managed_state, positions)
    balancer = dict(zone_state.get("balancer") or {})
    priority = str(balancer.get("prioritySide") or balancer.get("activeSide") or "").upper()
    if priority not in {"LONG", "SHORT"}:
        priority = ""
    legacy_balancer_open = (
        count_current("LONG", role=ROLE_EXPOSURE_BALANCER, status=STATUS_OPEN)
        + count_current("SHORT", role=ROLE_EXPOSURE_BALANCER, status=STATUS_OPEN)
    )
    base_open_long = count_current("LONG", role=ROLE_ZONE_BASE, status=STATUS_OPEN)
    base_open_short = count_current("SHORT", role=ROLE_ZONE_BASE, status=STATUS_OPEN)
    base_free_long = count_current("LONG", role=ROLE_ZONE_BASE, status=STATUS_AVAILABLE)
    base_free_short = count_current("SHORT", role=ROLE_ZONE_BASE, status=STATUS_AVAILABLE)
    homecomings = _clean_homecoming_events(zone_state.get("homecomingEvents"))
    zone_state["homecomingEvents"] = homecomings

    return {
        "enabled": True, "schemaVersion": SCHEMA_VERSION,
        "safeForNewEntries": bool(zone_safe and active_zone is not None),
        "activeZone": active_zone, "previousZone": zone_state.get("previousZone"),
        "zoneActivationId": zone_state.get("zoneActivationId"), "hardFormationCap": True,
        "zoneFormation": {
            "baseLongSoldiers": _integer(zone_state.get("baseLongSoldiers")),
            "baseShortSoldiers": _integer(zone_state.get("baseShortSoldiers")),
        },
        "currentZone": {
            "openLong": base_open_long, "openShort": base_open_short,
            "freeLong": base_free_long, "freeShort": base_free_short,
            "balancerOpen": legacy_balancer_open, "balancerFree": 0,
        },
        "oldZonesOpen": {"total": old_open_long + old_open_short, "long": old_open_long, "short": old_open_short},
        "totalActive": exposure["totalLongOpenCount"] + exposure["totalShortOpenCount"],
        "totalLongOpenCount": exposure["totalLongOpenCount"],
        "totalShortOpenCount": exposure["totalShortOpenCount"],
        "exposure": exposure, "entryPriority": priority or None,
        "balancer": {
            **balancer, "mode": "PRIORITY_ONLY", "prioritySide": priority or None,
            "activeSide": priority or None, "desiredCount": 0, "desiredNotionalUsd": 0.0,
            "openCount": legacy_balancer_open, "freeCount": 0,
            "message": "Geen exposure-prioriteit" if not priority else f"Entry-prioriteit {priority} · geen extra soldaten",
        },
        "homecomings": {"total": len(homecomings), "events": homecomings[-128:]},
        "legacyBalancerOpenCount": legacy_balancer_open,
        "legacyUnassignedOpenCount": exposure["legacyUnassignedOpenCount"],
        "poolCount": len(pools),
    }
