"""Cloud API wrapper exposing the unified Strategy-2 Bot Health contract.

Importing ``main`` preserves every established route and runtime. Only the existing
authenticated GET Bot Health projection is replaced; no trading route is modified.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends

from main import (
    _today_reliability,
    app,
    aster_strategy2_reference,
    authenticated_user,
    db,
    reliability_counts,
    reliability_overall,
)
from strategy2_bot_health import merge_strategy2_bot_health


def _replace_get_route(path: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and "GET" in (getattr(route, "methods", set()) or set())
        )
    ]
    app.openapi_schema = None


def _legacy_bot_health(uid: str, state: dict[str, Any]) -> dict[str, Any]:
    rows = _today_reliability(uid)
    mine = reliability_counts(rows)
    active = tracked = platform_auto = platform_open = 0

    for document in db.collection("asterStrategy2").stream():
        tracked += 1
        value = document.to_dict() or {}
        active += int(bool(value.get("enabled") or value.get("monitor")))
        events = _today_reliability(document.id)
        counts = reliability_counts(events)
        platform_auto += counts["autoRecovered"]
        platform_open += counts["open"] + counts["safetyHolds"]

    ordered = sorted(
        rows,
        key=lambda event: event.get("lastDetectedAt")
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return {
        "status": reliability_overall(rows),
        "lastSuccessfulScan": state.get(
            "lastSuccessfulScanAt", state.get("lastTickAt")
        ),
        "yourBot": mine,
        "platform": {
            "activeBots": active,
            "trackedBots": tracked,
            "autoRecovered": platform_auto,
            "openIncidents": platform_open,
        },
        "incidents": ordered[:100],
    }


_replace_get_route("/v1/me/bot-health")


@app.get("/v1/me/bot-health")
def bot_health(
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    uid = str(user["uid"])
    state = aster_strategy2_reference(uid).get().to_dict() or {}
    legacy = _legacy_bot_health(uid, state)
    return merge_strategy2_bot_health(legacy, state, account_id=uid)
