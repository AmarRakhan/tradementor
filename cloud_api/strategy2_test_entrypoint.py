"""Isolated entrypoint for the shared Strategy-2 live-test service only."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, Header

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


def _strategy_keys(state: dict[str, Any], strategy_id: str, engine_type: str) -> set[tuple[str, str]]:
    rows = control_plane.proven_owned_rows(
        state.get("ownedLegs", []), strategy_id=strategy_id, engine_type=engine_type,
    )
    return {(str(row["symbol"]).upper(), str(row["side"]).upper()) for row in rows}


@app.get("/v1/me/aster/strategy2/diagnostics")
def strategy2_token_diagnostics(
    user: dict[str, Any] = Depends(control_plane.authenticated_user),
) -> dict[str, Any]:
    """Return token-scoped ownership evidence without exchange or write access."""
    uid = str(user["uid"])
    s2_snapshot = control_plane.aster_strategy2_reference(uid).get()
    s2 = (s2_snapshot.to_dict() or {}) if s2_snapshot.exists else {}
    s1 = control_plane.aster_automation_reference(uid).get().to_dict() or {}
    s3 = control_plane.aster_strategy3_reference(uid).get().to_dict() or {}

    s1_keys = _strategy_keys(s1, "aster-strategy-1", "strategy1") | _strategy_keys(s1, "strategy_1", "strategy_1")
    s2_keys = _strategy_keys(s2, "aster-strategy-2", "strategy2")
    s3_keys = _strategy_keys(s3, "aster-strategy-3", "strategy3")
    collision_keys = (s1_keys & s2_keys) | (s1_keys & s3_keys) | (s2_keys & s3_keys)
    last_tick = s2.get("lastTickAt")
    if isinstance(last_tick, datetime):
        last_tick_utc = last_tick.replace(tzinfo=timezone.utc) if last_tick.tzinfo is None else last_tick.astimezone(timezone.utc)
        heartbeat_age = max(0, int((datetime.now(timezone.utc) - last_tick_utc).total_seconds()))
    else:
        last_tick_utc = None
        heartbeat_age = None
    long_legs = sum(side == "LONG" for _, side in s2_keys)
    short_legs = sum(side == "SHORT" for _, side in s2_keys)
    unassigned = int(control_plane.safe_float(s2.get("unassignedPositions")))
    legacy_active = bool(s1.get("enabled") or s1.get("monitor") or s3.get("enabled") or s3.get("monitor"))
    exclusive = bool(s2.get("exclusiveOwnership"))
    central_exclusive = os.getenv("ASTER_STRATEGY2_EXCLUSIVE_OWNERSHIP", "false").lower() == "true"
    handoff_eligible = bool(s2_snapshot.exists and s2.get("enabled") and s2.get("monitor")
        and central_exclusive and len(s2_keys) == 68 and not unassigned and not collision_keys)
    return {
        "readOnly": True,
        "identity": {"uid": uid, "email": str(user.get("email", "")),
            "emailVerified": user.get("email_verified") is True},
        "strategy2": {
            "documentExists": s2_snapshot.exists, "enabled": bool(s2.get("enabled")),
            "monitor": bool(s2.get("monitor")), "phase": str(s2.get("phase", "MISSING")),
            "reason": str(s2.get("lastReason", "Strategy-2-document ontbreekt")),
            "exclusiveOwnership": exclusive,
            "ownershipProven": bool(s2_snapshot.exists and exclusive and not unassigned and not collision_keys),
            "ownedLegs": len(s2_keys), "longLegs": long_legs, "shortLegs": short_legs,
            "unassignedPositions": unassigned, "crossStrategyCollisions": len(collision_keys),
            "legacyStrategiesActive": legacy_active, "lastTickAt": last_tick_utc,
            "centralExclusiveRuntime": central_exclusive, "handoffEligible": handoff_eligible,
            "heartbeatAgeSeconds": heartbeat_age,
            "heartbeatFresh": heartbeat_age is not None and heartbeat_age <= 180,
        },
    }


@app.post("/v1/me/aster/strategy2/exclusive-handoff")
def strategy2_exclusive_handoff(
    user: dict[str, Any] = Depends(control_plane.authenticated_user),
) -> dict[str, Any]:
    """Disable legacy controls only after token-scoped S2 ownership proof."""
    uid = str(user["uid"])
    s1_ref = control_plane.aster_automation_reference(uid)
    s2_ref = control_plane.aster_strategy2_reference(uid)
    s3_ref = control_plane.aster_strategy3_reference(uid)
    s1_snapshot, s2_snapshot, s3_snapshot = s1_ref.get(), s2_ref.get(), s3_ref.get()
    if not s2_snapshot.exists:
        raise control_plane.HTTPException(409, "Strategy-2-document ontbreekt")
    s1, s2, s3 = s1_snapshot.to_dict() or {}, s2_snapshot.to_dict() or {}, s3_snapshot.to_dict() or {}
    s1_keys = _strategy_keys(s1, "aster-strategy-1", "strategy1") | _strategy_keys(s1, "strategy_1", "strategy_1")
    s2_keys = _strategy_keys(s2, "aster-strategy-2", "strategy2")
    s3_keys = _strategy_keys(s3, "aster-strategy-3", "strategy3")
    collisions = (s1_keys & s2_keys) | (s1_keys & s3_keys) | (s2_keys & s3_keys)
    unassigned = int(control_plane.safe_float(s2.get("unassignedPositions")))
    central_exclusive = os.getenv("ASTER_STRATEGY2_EXCLUSIVE_OWNERSHIP", "false").lower() == "true"
    if not (s2.get("enabled") and s2.get("monitor") and central_exclusive
            and len(s2_keys) == 68 and not collisions and unassigned == 0):
        raise control_plane.HTTPException(409, "Exclusieve Strategy-2-ownership is niet volledig bewezen")
    now = datetime.now(timezone.utc)
    reason = "Administratief uitgeschakeld na bewezen exclusieve Strategy-2-ownership"
    batch = control_plane.db.batch()
    batch.set(s1_ref, {"enabled": False, "monitor": False, "phase": "DISABLED_FOR_STRATEGY2_EXCLUSIVE",
        "lastReason": reason, "updatedAt": now}, merge=True)
    batch.set(s3_ref, {"enabled": False, "monitor": False, "rapidBuildRequested": False,
        "phase": "DISABLED_FOR_STRATEGY2_EXCLUSIVE", "lastReason": reason, "updatedAt": now}, merge=True)
    batch.commit()
    return {"completed": True, "uid": uid, "strategy2OwnedLegs": len(s2_keys),
        "ordersSent": 0, "positionsChanged": 0, "schedulerChanged": False}


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
