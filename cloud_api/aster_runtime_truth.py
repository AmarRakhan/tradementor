from __future__ import annotations

from typing import Any


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _b(value: Any) -> bool:
    return value is True


def build_multi_bb_runtime_truth(
    *,
    settings: dict[str, Any],
    report: dict[str, Any],
    zone_report: dict[str, Any],
    enabled: bool,
    monitor: bool,
    last_tick_at: Any,
    zone_active: bool,
    dynamic_hedge_blocking: bool,
    queue_halted: bool,
) -> dict[str, Any]:
    """Build one server-authoritative operational snapshot for Multi-BB.

    This is presentation/observability only. It does not mutate settings, state,
    positions, orders, leases, ownership, or exchange data.
    """
    maximum = max(0, _i(settings.get("maximumPositions")))
    account_count = max(0, _i(report.get("accountPositionCount")))
    remaining = max(0, _i(report.get("accountRemainingCapacity")))
    active_long = max(0, _i(report.get("activeLong")))
    active_short = max(0, _i(report.get("activeShort")))
    remaining_long = max(0, _i(report.get("remainingLong")))
    remaining_short = max(0, _i(report.get("remainingShort")))
    scanner = report.get("scannerDiagnostics") if isinstance(report.get("scannerDiagnostics"), dict) else {}

    if zone_active:
        active_zone = zone_report.get("activeZone")
        zone_safe = _b(zone_report.get("safeForNewEntries"))
        mode = "ZONE_WARRIORS"
    else:
        active_zone = None
        zone_safe = False
        mode = "CLASSIC_DCA"

    expected_remaining = max(0, maximum - account_count) if zone_active else remaining
    capacity_consistent = (remaining == expected_remaining) if zone_active and maximum > 0 else True

    return {
        "source": "SERVER_RUNTIME",
        "schemaVersion": 1,
        "strategyMode": mode,
        "enabled": bool(enabled),
        "monitor": bool(monitor),
        "lastTickAt": last_tick_at,
        "activeZone": active_zone,
        "zoneSafeForNewEntries": zone_safe,
        "maximumPositions": maximum,
        "accountPositionCount": account_count,
        "accountRemainingCapacity": remaining,
        "activeLong": active_long,
        "activeShort": active_short,
        "remainingLong": remaining_long,
        "remainingShort": remaining_short,
        "entryStatus": str(report.get("entryStatus") or ""),
        "entryReason": str(report.get("entryReason") or ""),
        "scannerDiagnostics": scanner,
        "dynamicHedgeBlocking": bool(dynamic_hedge_blocking),
        "queueHalted": bool(queue_halted),
        "invariants": {
            "capacityConsistent": capacity_consistent,
            "expectedAccountRemainingCapacity": expected_remaining,
            "activePositionSum": active_long + active_short,
        },
    }



ZONE_ROLES = {"ZONE_BASE", "EXPOSURE_BALANCER"}


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _side(row: dict[str, Any]) -> str:
    side = str(row.get("side") or row.get("positionSide") or "").upper().strip()
    return side if side in {"LONG", "SHORT"} else ""


def _position_key(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper().strip()
    side = _side(row)
    return f"{symbol}|{side}" if symbol and side else ""


def _zone_index(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number


def _capacity(settings: dict[str, Any], key: str, nested_key: str) -> int:
    price_zone = _record(settings.get("priceZoneSeats"))
    raw = price_zone.get(nested_key) if nested_key in price_zone else settings.get(key)
    return max(0, _i(raw, 0))



def _canonical_long_next_levels(zones: list[dict[str, Any]], current_price: Any, *, reliable: bool) -> dict[str, Any]:
    """Read-only price thresholds from the already canonical ladder; never infer new zone prices."""
    try:
        price = float(current_price)
    except (TypeError, ValueError):
        price = float("nan")
    if not reliable or not (price > 0 and price < float("inf")):
        return {"status": "UNAVAILABLE", "up": None, "down": None, "reason": "CANONICAL_PRICE_OR_OWNERSHIP_UNAVAILABLE"}
    valid = []
    for row in zones:
        try:
            lower, upper = float(row.get("lower")), float(row.get("upper"))
        except (TypeError, ValueError):
            continue
        if not (0 < lower < upper < float("inf")):
            continue
        if int(row.get("longMax", 0)) <= int(row.get("longOpen", 0)):
            continue
        valid.append((row, lower, upper))
    higher = [(lower, row) for row, lower, upper in valid if lower > price]
    lower = [(upper, row) for row, lo, upper in valid if upper < price]
    def result(item: tuple[float, dict[str, Any]] | None) -> dict[str, Any] | None:
        if item is None:
            return None
        threshold, row = item
        return {"zone": row["index"], "price": threshold, "distance": abs(threshold - price), "freeLongSeats": max(0, int(row["longMax"]) - int(row["longOpen"])), "unit": "PORTFOLIO_EQUITY_USDT", "entryPermission": "NOT_EVALUATED"}
    return {
        "status": "AVAILABLE",
        "up": result(min(higher, key=lambda v: v[0]) if higher else None),
        "down": result(max(lower, key=lambda v: v[0]) if lower else None),
        "reason": "",
    }

def _canonical_next_free_position_levels(zones: list[dict[str, Any]], current_price: Any, *, reliable: bool) -> dict[str, Any]:
    """Read-only nearest free LONG or SHORT zone from the same canonical ladder."""
    try:
        price = float(current_price)
    except (TypeError, ValueError):
        price = float("nan")
    if not reliable or not (0 < price < float("inf")):
        return {"status": "UNAVAILABLE", "up": None, "down": None, "reason": "CANONICAL_PRICE_OR_OWNERSHIP_UNAVAILABLE"}
    valid = []
    for row in zones:
        try:
            lower, upper = float(row.get("lower")), float(row.get("upper"))
            free_long = max(0, int(row["longMax"]) - int(row["longOpen"]))
            free_short = max(0, int(row["shortMax"]) - int(row["shortOpen"]))
        except (TypeError, ValueError, KeyError):
            continue
        if 0 < lower < upper < float("inf") and (free_long > 0 or free_short > 0):
            valid.append((row, lower, upper, free_long, free_short))
    higher = [(lower, row, long, short) for row, lower, upper, long, short in valid if lower > price]
    lower = [(upper, row, long, short) for row, lo, upper, long, short in valid if upper < price]
    def result(item: tuple[float, dict[str, Any], int, int] | None) -> dict[str, Any] | None:
        if item is None:
            return None
        threshold, row, long, short = item
        return {"zone": row["index"], "price": threshold, "distance": abs(threshold - price),
                "freeLongSeats": long, "freeShortSeats": short,
                "unit": "PORTFOLIO_EQUITY_USDT", "entryPermission": "NOT_EVALUATED"}
    return {"status": "AVAILABLE",
            "up": result(min(higher, key=lambda item: item[0]) if higher else None),
            "down": result(max(lower, key=lambda item: item[0]) if lower else None),
            "reason": ""}


def build_canonical_zone_state(
    *,
    settings: dict[str, Any],
    positions: list[dict[str, Any]] | None,
    managed_positions: dict[str, Any] | None,
    zone_report: dict[str, Any] | None,
    snapshot_at_ms: Any = None,
) -> dict[str, Any]:
    """Build the single browser-facing position/zone truth.

    This function is pure and read-only. Exchange positions are the owner of
    account-open truth; the persisted Strategy-2 managed map is the owner of
    Strategy-2 ownership; saved Strategy-2 settings own capacity; and the
    persisted runtimeSync ladder owns zone price geometry.

    No browser or caller should reconstruct these counts independently.
    """
    account_rows = [dict(row) for row in positions or [] if isinstance(row, dict)]
    managed = {
        str(key).upper(): dict(value)
        for key, value in (managed_positions or {}).items()
        if isinstance(value, dict)
    }
    report = _record(zone_report)
    runtime_sync = _record(report.get("runtimeSync"))
    ladder_rows = [dict(row) for row in runtime_sync.get("zones", []) if isinstance(row, dict)]

    per_zone_long = _capacity(settings, "zoneBaseLongSoldiers", "longSeatsPerZone")
    per_zone_short = _capacity(settings, "zoneBaseShortSoldiers", "shortSeatsPerZone")
    max_total = max(0, _i(settings.get("maximumPositions"), 0))
    active_zone = _zone_index(runtime_sync.get("activeZone"))
    if active_zone is None:
        active_zone = _zone_index(report.get("activeZone"))

    account_long = account_short = 0
    strategy_long = strategy_short = 0
    other_long = other_short = 0
    zone_counts: dict[int, dict[str, int]] = {}
    unassigned: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    strategy_positions: list[dict[str, Any]] = []

    for position in account_rows:
        key = _position_key(position)
        side = _side(position)
        symbol = str(position.get("symbol") or "").upper().strip()
        if not key:
            continue
        if side == "LONG":
            account_long += 1
        else:
            account_short += 1

        managed_row = managed.get(key)
        if managed_row is None:
            if side == "LONG":
                other_long += 1
            else:
                other_short += 1
            other.append({
                "positionKey": key,
                "symbol": symbol,
                "side": side,
                "ownerType": str(position.get("ownerType") or "ACCOUNT_OTHER"),
                "role": str(position.get("role") or position.get("strategyRole") or ""),
                "reason": "NOT_PRESENT_IN_STRATEGY2_MANAGED_POSITIONS",
            })
            continue

        if side == "LONG":
            strategy_long += 1
        else:
            strategy_short += 1
        role = str(managed_row.get("soldierRole") or "").upper().strip()
        origin_zone = _zone_index(managed_row.get("originZone"))
        strategy_positions.append({
            "positionKey": key,
            "symbol": symbol,
            "side": side,
            "role": role,
            "originZone": origin_zone,
        })

        if role in ZONE_ROLES and origin_zone is not None:
            bucket = zone_counts.setdefault(origin_zone, {"long": 0, "short": 0})
            if side == "LONG":
                bucket["long"] += 1
            else:
                bucket["short"] += 1
            continue

        reason = (
            "MISSING_ORIGIN_ZONE"
            if role in ZONE_ROLES and origin_zone is None
            else "NOT_ZONE_WARRIOR_ROLE"
        )
        unassigned.append({
            "positionKey": key,
            "symbol": symbol,
            "side": side,
            "role": role,
            "originZone": origin_zone,
            "reason": reason,
        })

    price_by_zone: dict[int, dict[str, Any]] = {}
    for row in ladder_rows:
        index = _zone_index(row.get("index"))
        if index is None:
            continue
        price_by_zone[index] = {
            "center": row.get("center"),
            "lower": row.get("lower"),
            "upper": row.get("upper"),
            "source": str(row.get("source") or runtime_sync.get("zoneLadderSource") or ""),
        }

    indexes = set(price_by_zone) | set(zone_counts)
    if active_zone is not None:
        indexes.add(active_zone)
    zone_rows = []
    for index in sorted(indexes, reverse=True):
        counts = zone_counts.get(index, {"long": 0, "short": 0})
        price = price_by_zone.get(index, {})
        long_open = int(counts["long"])
        short_open = int(counts["short"])
        zone_rows.append({
            "index": index,
            "center": price.get("center"),
            "lower": price.get("lower"),
            "upper": price.get("upper"),
            "priceSource": price.get("source", ""),
            "longOpen": long_open,
            "shortOpen": short_open,
            "totalOpen": long_open + short_open,
            "longMax": per_zone_long,
            "shortMax": per_zone_short,
            "totalMax": per_zone_long + per_zone_short,
            "active": active_zone == index,
        })

    account_total = account_long + account_short
    strategy_total = strategy_long + strategy_short
    other_total = other_long + other_short
    assigned_total = sum(row["totalOpen"] for row in zone_rows)
    unassigned_total = len(unassigned)

    return {
        "source": "SERVER_RUNTIME",
        "schemaVersion": 1,
        "snapshotAtMs": snapshot_at_ms,
        "currentPrice": runtime_sync.get("currentEquity"),
        "account": {
            "totalOpen": account_total,
            "longOpen": account_long,
            "shortOpen": account_short,
        },
        "strategyOwned": {
            "totalOpen": strategy_total,
            "longOpen": strategy_long,
            "shortOpen": strategy_short,
        },
        "nonStrategyOwned": {
            "totalOpen": other_total,
            "longOpen": other_long,
            "shortOpen": other_short,
        },
        "capacity": {
            "perZoneLong": per_zone_long,
            "perZoneShort": per_zone_short,
            "maxTotal": max_total,
        },
        "activeZone": active_zone,
        "zones": zone_rows,
        "nextLongLevels": _canonical_long_next_levels(zone_rows, runtime_sync.get("currentEquity"), reliable=bool(ladder_rows) and account_total == strategy_total + other_total and strategy_total == assigned_total + unassigned_total),
        # Distance display is read-only. Unassigned/non-zone positions can make
        # global reconciliation incomplete without invalidating the canonical
        # priced ladder and the separately counted seats in each zone.
        # Do not suppress these display distances on unrelated account drift.
        "nextFreePositionLevels": _canonical_next_free_position_levels(zone_rows, runtime_sync.get("currentEquity"), reliable=bool(ladder_rows) and account_total == strategy_total + other_total and strategy_total == assigned_total + unassigned_total),
        "strategyPositions": strategy_positions,
        "unassignedStrategyPositions": unassigned,
        "otherOpenPositions": other,
        "reconciliation": {
            "accountMatches": account_total == strategy_total + other_total,
            "strategyMatches": strategy_total == assigned_total + unassigned_total,
            "zonesMatchStrategy": strategy_total == assigned_total + unassigned_total,
            "accountTotal": account_total,
            "strategyTotal": strategy_total,
            "zoneAssignedTotal": assigned_total,
            "unassignedStrategyTotal": unassigned_total,
            "otherOpenTotal": other_total,
        },
    }
