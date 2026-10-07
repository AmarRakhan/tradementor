"""Explicit deprecation registry for the Aster native-order migration.

Nothing in this file changes runtime behavior. It makes cleanup conditions
machine-readable so legacy paths cannot be left indefinitely after migration.
"""
from __future__ import annotations

from typing import Any


DEPRECATION_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "id": "ACTIVE_TRADES_POLLING",
        "legacyPath": "web/components/portfolio-koers-chart.tsx::loadActiveTrades interval",
        "replacement": "shared realtime Aster state + safety reconciliation",
        "status": "ACTIVE_LEGACY",
        "temporaryFallback": True,
        "removeWhen": (
            "Realtime shared-state parity is proven for positions/openPnL and "
            "reconnect reconciliation passes production canary."
        ),
    },
    {
        "id": "SOFTWARE_TP_TRIGGER",
        "legacyPath": "cloud_api/aster_multi_bb_core.py::tp_due software mark-price trigger",
        "replacement": "exchange-native reduce-only TP lifecycle",
        "status": "ACTIVE_LEGACY",
        "temporaryFallback": True,
        "removeWhen": (
            "Shadow parity is 100% for eligible positions, native TP canary passes, "
            "Auto Hedge/ownership/restart guards are proven, and rollback window closes."
        ),
    },
    {
        "id": "SOFTWARE_DCA_TRIGGER",
        "legacyPath": "cloud_api/aster_multi_bb_core.py::_dca_due software mark-price trigger",
        "replacement": "one exchange-native next-DCA limit order with fill-driven rearm",
        "status": "ACTIVE_LEGACY",
        "temporaryFallback": True,
        "removeWhen": (
            "Next-DCA price/quantity parity is proven, margin/leverage revalidation is "
            "preserved, fill-driven rearm canary passes, and rollback window closes."
        ),
    },
    {
        "id": "MULTI_COMPONENT_ASTER_STATUS_POLLING",
        "legacyPath": "root-mounted Aster UI bridges with independent /api/exchanges/aster reads",
        "replacement": "single shared Aster snapshot/realtime state provider",
        "status": "ACTIVE_LEGACY",
        "temporaryFallback": True,
        "removeWhen": (
            "All consumers use shared state, visibility/reconnect behavior is proven, "
            "and request-rate telemetry confirms no stale-data regression."
        ),
    },
    {
        "id": "PER_INSTANCE_BACKGROUND_WORKERS",
        "legacyPath": "tradementor-api startup realtime + periodic background threads",
        "replacement": "singleton realtime worker + singleton scheduler/reconciliation owner",
        "status": "ACTIVE_LEGACY",
        "temporaryFallback": True,
        "removeWhen": (
            "Dedicated workers are healthy, distributed lease/order safety is retained, "
            "and API instances no longer own background trading loops."
        ),
    },
    {
        "id": "UNBOUNDED_RELEASE_RETENTION",
        "legacyPath": "candidate tags/revisions/images retained by deploy workflows",
        "replacement": "bounded rollback retention + artifact cleanup policy",
        "status": "ACTIVE_LEGACY",
        "temporaryFallback": False,
        "removeWhen": (
            "Protected rollback set is defined and cleanup dry-run proves no live/current "
            "revision or required rollback image would be deleted."
        ),
    },
)


def deprecation_plan() -> dict[str, Any]:
    active = [dict(item) for item in DEPRECATION_ITEMS if item["status"] == "ACTIVE_LEGACY"]
    return {
        "policy": "REPLACEMENT_IS_NOT_COMPLETE_UNTIL_LEGACY_PATH_IS_REMOVED",
        "activeLegacyCount": len(active),
        "items": active,
    }
