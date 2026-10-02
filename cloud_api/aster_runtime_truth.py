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
