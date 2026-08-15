"""Isolated entrypoint for the shared Strategy-2 live-test service only."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Header

import main as control_plane
from read_only_source import read_source_url as environment_read_source_url


def _test_runtime_read_source_url(
    base_url: str,
    method: str,
    path: str,
    query: str = "",
) -> str | None:
    return environment_read_source_url(
        base_url,
        method,
        path,
        query,
        environment=os.getenv("TRADEMENTOR_ENVIRONMENT", ""),
    )


# The imported middleware resolves this module global at request time.  Keep
# all non-test environments unchanged while making Strategy-2 status local in
# the isolated test runtime.
control_plane.read_source_url = _test_runtime_read_source_url
app = control_plane.app


def _live_gates_open() -> bool:
    environment = os.getenv("TRADEMENTOR_ENVIRONMENT", "").strip().lower()
    return (
        environment == "strategy2-test-live"
        and os.getenv("TRADEMENTOR_ALLOW_LIVE", "false").lower() == "true"
        and os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
        and os.getenv("ASTER_STRATEGY2_LIVE_ENABLED", "false").lower() == "true"
        and os.getenv("ASTER_STRATEGY3_LIVE_ENABLED", "false").lower() != "true"
        and os.getenv("ASTER_STRATEGY3_RUNTIME_ENABLED", "false").lower() != "true"
    )


@app.post("/internal/aster-strategy2/tick")
def run_aster_strategy2_scheduler(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Run only Strategy 2 in its isolated shared-test runtime."""
    control_plane.verify_internal_cloud_request(authorization)
    if not _live_gates_open():
        return {"processed": 0, "status": "centrally-disabled", "strategy2": [], "strategy3": []}

    controls = list(
        control_plane.db.collection("asterStrategy2").where("monitor", "==", True).stream()
    )
    strategy2_results = []
    for item in controls[:100]:
        reference = control_plane.aster_strategy2_reference(item.id)
        if not control_plane._acquire_mexc_automation_lease(reference):
            strategy2_results.append({"uid": item.id, "status": "lease-busy"})
            continue
        try:
            strategy2_results.append({
                "uid": item.id,
                **control_plane._run_aster_strategy2_tick(item.id),
            })
        except Exception as exc:
            message = f"Veilige Strategy-2-schedulerfout: {exc}"
            reference.set({
                "phase": "DATA_HOLD",
                "lastReason": message,
                "lastTickAt": datetime.now(timezone.utc),
            }, merge=True)
            strategy2_results.append({"uid": item.id, "status": "data-hold", "reason": message})
        finally:
            reference.set({"leaseUntil": datetime.now(timezone.utc)}, merge=True)
    return {
        "processed": len(strategy2_results),
        "status": "ok",
        "strategy2": strategy2_results,
        "strategy3": [],
        "strategy3Isolated": True,
    }
