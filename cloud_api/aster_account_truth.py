"""Canonical read-only account truth contract for Aster.

This module does not call the exchange, mutate Firestore, or make trading
decisions. It only shapes already-authoritative server state into one stable
browser contract. Every browser surface must consume this contract rather than
reconstructing account truth from DOM text, localStorage, or component caches.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ASTER_ACCOUNT_TRUTH_SCHEMA_VERSION = 1
ASTER_ACCOUNT_TRUTH_CONTRACT = "ASTER_ACCOUNT_TRUTH_V1"


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _captured_at_ms(value: Any) -> int | None:
    if isinstance(value, datetime):
        stamp = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return int(stamp.timestamp() * 1000)
    number = _number(value)
    if number is None or number <= 0:
        return None
    return int(number * 1000 if number < 10_000_000_000 else number)


def build_aster_account_truth(
    public_status: dict[str, Any] | None,
    *,
    day_high: float | None = None,
    day_low: float | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Shape the public Aster status into one canonical browser-facing truth.

    The values are copied from the same server snapshot/status contract that
    drives the rest of the API. Missing data stays missing; this function never
    invents zeroes or falls back to browser-owned state.
    """
    status = _record(public_status)
    strategy2 = _record(status.get("strategy2"))
    settings = _record(strategy2.get("settings"))
    runtime_truth = _record(strategy2.get("runtimeTruth"))
    positions = [dict(row) for row in status.get("positions", []) if isinstance(row, dict)]
    captured_ms = _captured_at_ms(status.get("snapshotAt"))
    now_value = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)
    age_ms = max(0, now_value - captured_ms) if captured_ms is not None else None
    stale = captured_ms is None or age_ms is None or age_ms > 120_000

    zone_state = _record(runtime_truth.get("zoneState"))
    zone_account = _record(zone_state.get("account"))
    calculated_long_count = sum(1 for row in positions if str(row.get("side", "")).upper() == "LONG")
    calculated_short_count = sum(1 for row in positions if str(row.get("side", "")).upper() == "SHORT")
    long_count = _integer(zone_account.get("longOpen"))
    short_count = _integer(zone_account.get("shortOpen"))
    total_count = _integer(zone_account.get("totalOpen"))
    if long_count is None or short_count is None or total_count is None:
        long_count = calculated_long_count
        short_count = calculated_short_count
        total_count = len(positions)

    account = {
        "equity": _number(status.get("equity")),
        "walletBalance": _number(status.get("walletBalance")),
        "availableBalance": _number(status.get("availableBalance")),
        "activeTradeCapital": _number(status.get("activeTradeCapital")),
        "unrealizedPnl": _number(status.get("unrealizedPnl")),
        "maintenanceMargin": _number(status.get("maintenanceMargin")),
        "maintenanceMarginPct": _number(status.get("maintenanceMarginPct")),
        "marginRatio": _number(status.get("marginRatio")),
        "marginBalance": _number(status.get("marginBalance")),
        "liquidationRiskPct": _number(status.get("liquidationRiskPct")),
        "liquidationRiskSource": str(status.get("liquidationRiskSource", "")),
        "longNotional": _number(status.get("longNotional")),
        "shortNotional": _number(status.get("shortNotional")),
        "netExposure": _number(status.get("netExposure")),
        "grossExposure": _number(status.get("grossExposure")),
    }
    position_truth = {
        "count": total_count,
        "longCount": long_count,
        "shortCount": short_count,
        "rows": positions,
    }
    dca_count = sum(max(0, _integer(row.get("dcaCount")) or 0) for row in positions)
    strategy_summary = {
        "enabled": strategy2.get("enabled") is True,
        "monitor": strategy2.get("monitor") is True,
        "activeLong": long_count,
        "activeShort": short_count,
        "longCapacity": _integer(settings.get("longSlots")),
        "shortCapacity": _integer(settings.get("shortSlots")),
        "dcaCount": dca_count,
        "phase": str(strategy2.get("displayPhase", strategy2.get("phase", ""))),
    }
    performance = {
        "dayHigh": _number(day_high),
        "dayLow": _number(day_low),
        "realizedPnlToday": _number(status.get("realizedPnlToday")),
        "tradesClosedToday": _integer(status.get("tradesClosedToday")),
        "closedTodayReliable": status.get("closedTodayReliable") is True,
        "todayGrowthPercentage": _number(status.get("todayGrowthPercentage")),
        "averageDailyGrowthPercentage": _number(status.get("averageDailyGrowthPercentage")),
        "growthReliable": status.get("growthReliable") is True,
    }

    return {
        "schemaVersion": ASTER_ACCOUNT_TRUTH_SCHEMA_VERSION,
        "contract": ASTER_ACCOUNT_TRUTH_CONTRACT,
        "source": "ASTER_SERVER_CANONICAL_STATUS",
        "capturedAt": status.get("snapshotAt"),
        "capturedAtMs": captured_ms,
        "ageMs": age_ms,
        "stale": stale,
        "configured": status.get("configured") is True,
        "account": account,
        "positions": position_truth,
        "performance": performance,
        "strategy": {
            "strategy2": strategy2,
            "settings": settings,
            "runtimeTruth": runtime_truth,
            "summary": strategy_summary,
        },
        "provenance": {
            "account": {
                "source": "aster.account_information + aster.position_risk",
                "owner": "cloud_api.aster_status",
                "storage": "asterAutomation/{uid}.accountSnapshot",
            },
            "positions": {
                "source": "aster.position_risk",
                "owner": "cloud_api.aster_status",
                "storage": "asterAutomation/{uid}.accountSnapshot.positions",
            },
            "dayRange": {
                "source": "server-persisted account equity OHLC",
                "owner": "cloud_api.aster_portfolio_chart",
                "storage": "users/{uid}/asterPortfolioChart5m",
            },
            "strategy": {
                "source": "persisted Strategy-2 runtime",
                "owner": "cloud_api.aster_strategy2",
                "storage": "asterStrategy2/{uid}",
            },
        },
        "readOnly": True,
        "ordersSent": 0,
    }
