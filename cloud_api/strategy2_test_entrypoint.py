"""Isolated entrypoint for the shared Strategy-2 live-test service only."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, Header

import main as control_plane
from read_only_source import read_source_url as environment_read_source_url
from aster_cost_evidence import paged_user_trades
from aster_gateway import AsterApiError, AsterV3Client
from aster_strategy2_shadow import plan_validated_shadow
from aster_strategy2_shadow_adapter import (
    ReadOnlyAccountSnapshot, ShadowSnapshotRejected, validated_entry_symbols,
    validated_shadow_inputs,
)
from strategy2_handoff import HandoffProof, build_handoff_proof, ownership_rows, proof_public


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


def _token_account_proof(uid: str) -> HandoffProof:
    """Read one current account snapshot and complete fill evidence; never authorize orders."""
    secret = control_plane.load_aster_secret({"uid": uid})
    client = AsterV3Client(signer_address=secret.signer_address,
        sign_message=control_plane.local_eip712_signer(secret), live_authorized=False)
    try:
        positions = client.position_risk()
        open_orders = client.open_orders()
        active = control_plane.active_position_map(positions)
        fills: list[dict[str, Any]] = []
        for symbol in sorted({key[0] for key in active}):
            fills.extend(paged_user_trades(client, symbol, start_time=None))
    except (AsterApiError, ValueError) as exc:
        raise control_plane.HTTPException(409, f"Aster-accountsnapshot is niet betrouwbaar: {exc}") from exc
    state = control_plane.aster_strategy2_reference(uid).get().to_dict() or {}
    return build_handoff_proof(positions=positions, open_orders=open_orders, fills=fills,
        config_version=int(control_plane.safe_float(state.get("configVersion", 1))) or 1,
        captured_at_ms=int(datetime.now(timezone.utc).timestamp() * 1000))


@app.get("/v1/me/aster/strategy2/diagnostics")
def strategy2_token_diagnostics(
    user: dict[str, Any] = Depends(control_plane.authenticated_user),
) -> dict[str, Any]:
    """Return token-scoped ownership evidence from one current exchange snapshot."""
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
    proof = _token_account_proof(uid)
    proof_data = proof_public(proof)
    ownership_matches = s2_keys == set(proof.active_keys)
    ownership_proven = bool(s2_snapshot.exists and exclusive and ownership_matches
        and not unassigned and not collision_keys and proof.complete)
    handoff_required = not ownership_proven
    handoff_eligible = bool(s2_snapshot.exists and central_exclusive and proof.complete and not collision_keys)
    return {
        "readOnly": True,
        "identity": {"uid": uid, "email": str(user.get("email", "")),
            "emailVerified": user.get("email_verified") is True},
        "strategy2": {
            "documentExists": s2_snapshot.exists, "enabled": bool(s2.get("enabled")),
            "monitor": bool(s2.get("monitor")), "phase": str(s2.get("phase", "MISSING")),
            "reason": str(s2.get("lastReason", "Strategy-2-document ontbreekt")),
            "exclusiveOwnership": exclusive,
            "ownershipProven": ownership_proven,
            "ownedLegs": len(s2_keys), "longLegs": long_legs, "shortLegs": short_legs,
            "unassignedPositions": unassigned, "crossStrategyCollisions": len(collision_keys),
            "legacyStrategiesActive": legacy_active, "lastTickAt": last_tick_utc,
            "centralExclusiveRuntime": central_exclusive, "handoffEligible": handoff_eligible,
            "handoffRequired": handoff_required, "accountSnapshot": proof_data,
            "heartbeatAgeSeconds": heartbeat_age,
            "heartbeatFresh": heartbeat_age is not None and heartbeat_age <= 180,
        },
    }


@app.get("/v1/me/aster/strategy2/queue-shadow")
def strategy2_queue_shadow(
    user: dict[str, Any] = Depends(control_plane.authenticated_user),
) -> dict[str, Any]:
    """Plan existing-position actions from fresh reads; never write or trade."""
    uid = str(user["uid"])
    captured_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    state_snapshot = control_plane.aster_strategy2_reference(uid).get()
    state = (state_snapshot.to_dict() or {}) if state_snapshot.exists else {}
    secret = control_plane.load_aster_secret({"uid": uid})
    client = AsterV3Client(
        signer_address=secret.signer_address,
        sign_message=control_plane.local_eip712_signer(secret),
        live_authorized=False,
    )
    try:
        hedge_mode = client.position_mode()
        account = client.account_information()
        positions = tuple(client.position_risk())
        open_orders = tuple(client.open_orders())
        exchange_info = client.public_exchange_info()
        prices = tuple(client.ticker_prices())
        tickers_24h = tuple(client.ticker_24h())
        brackets = tuple(client.leverage_brackets())
        config = control_plane.Strategy2Config.from_mapping(state.get("settings"))
        persisted_owned = tuple(
            control_plane.owned_from_mapping(row)
            for row in state.get("ownedLegs", [])
        )
        entry_symbols = validated_entry_symbols(
            config=config, owned=persisted_owned, positions=positions,
            account=account, exchange_info=exchange_info,
            ticker_prices=prices, tickers_24h=tickers_24h,
            leverage_brackets=brackets, captured_at_ms=captured_at_ms,
        )
        inputs = validated_shadow_inputs(ReadOnlyAccountSnapshot(
            account_uid=uid,
            scan_id=f"shadow-{captured_at_ms}",
            captured_at_ms=captured_at_ms,
            strategy_state=state,
            hedge_mode=hedge_mode,
            account=account,
            positions=positions,
            open_orders=open_orders,
            exchange_reliable=True,
            entry_symbols=entry_symbols,
        ))
    except (AsterApiError, ShadowSnapshotRejected, TypeError, ValueError) as exc:
        raise control_plane.HTTPException(
            409, f"Read-only queue-shadow veilig geblokkeerd: {exc}",
        ) from exc
    result = plan_validated_shadow(inputs)
    return {
        **result,
        "scope": "proven-positions-and-validated-new-entries",
        "newEntryPlanning": "READ_ONLY_CONTRACT_VALIDATED",
        "ordersSent": 0,
        "positionsChanged": 0,
        "persistentWrites": 0,
        "schedulerChanged": False,
        "botStatusChanged": False,
    }


@app.post("/v1/me/aster/strategy2/exclusive-handoff")
def strategy2_exclusive_handoff(
    user: dict[str, Any] = Depends(control_plane.authenticated_user),
) -> dict[str, Any]:
    """Prove and atomically transfer one fresh token-scoped account snapshot."""
    uid = str(user["uid"])
    s1_ref = control_plane.aster_automation_reference(uid)
    s2_ref = control_plane.aster_strategy2_reference(uid)
    s3_ref = control_plane.aster_strategy3_reference(uid)
    # This is the authoritative diagnostic and handoff snapshot.  A prior GET
    # is presentation-only; comparing two exchange requests is unsafe because
    # Aster may normalize equivalent position/fill data differently.
    proof = _token_account_proof(uid)
    if proof.open_order_count:
        raise control_plane.HTTPException(409, "Open Aster-order aanwezig; overdracht veilig geblokkeerd")
    if not proof.complete:
        raise control_plane.HTTPException(409, "Niet iedere actieve leg heeft een bewezen openingsfill")
    central_exclusive = os.getenv("ASTER_STRATEGY2_EXCLUSIVE_OWNERSHIP", "false").lower() == "true"
    if not central_exclusive:
        raise control_plane.HTTPException(409, "Centrale exclusieve Strategy-2-runtime is niet vrijgegeven")
    now = datetime.now(timezone.utc)
    reason = "Administratief uitgeschakeld na bewezen exclusieve Strategy-2-ownership"
    transaction = control_plane.db.transaction()

    @control_plane.firestore.transactional
    def commit_handoff(txn):
        s1_snapshot = s1_ref.get(transaction=txn)
        s2_snapshot = s2_ref.get(transaction=txn)
        s3_snapshot = s3_ref.get(transaction=txn)
        if not s2_snapshot.exists:
            raise control_plane.HTTPException(409, "Strategy-2-document ontbreekt")
        s1, s2, s3 = s1_snapshot.to_dict() or {}, s2_snapshot.to_dict() or {}, s3_snapshot.to_dict() or {}
        s1_keys = _strategy_keys(s1, "aster-strategy-1", "strategy1") | _strategy_keys(s1, "strategy_1", "strategy_1")
        s2_keys = _strategy_keys(s2, "aster-strategy-2", "strategy2")
        s3_keys = _strategy_keys(s3, "aster-strategy-3", "strategy3")
        collisions = (s1_keys & s2_keys) | (s1_keys & s3_keys) | (s2_keys & s3_keys)
        if collisions:
            raise control_plane.HTTPException(409, "Dubbele ownershipclaim; overdracht veilig geblokkeerd")
        txn.set(s1_ref, {"enabled": False, "monitor": False, "phase": "DISABLED_FOR_STRATEGY2_EXCLUSIVE",
            "lastReason": reason, "updatedAt": now}, merge=True)
        # Deliberately do not write enabled/monitor: a handoff never starts Strategy 2.
        txn.set(s2_ref, {"ownedLegs": ownership_rows(proof), "exclusiveOwnership": True,
            "unassignedPositions": 0, "ownershipSnapshotFingerprint": proof.snapshot_fingerprint,
            "ownershipTransferredAt": now, "updatedAt": now}, merge=True)
        txn.set(s3_ref, {"enabled": False, "monitor": False, "rapidBuildRequested": False,
            "phase": "DISABLED_FOR_STRATEGY2_EXCLUSIVE", "lastReason": reason, "updatedAt": now}, merge=True)
        return bool(s2.get("enabled")), bool(s2.get("monitor"))

    enabled, monitor = commit_handoff(transaction)
    return {"completed": True, "uid": uid, "strategy2OwnedLegs": len(proof.owned_legs),
        "activeAccountLegs": len(proof.active_keys), "exclusiveOwnership": True,
        "strategy2Enabled": enabled, "strategy2Monitor": monitor,
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


@app.post("/internal/aster-strategy2/queue-canary/tick")
def run_aster_strategy2_queue_canary(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Run the queue for exactly one opted-in account without moving service traffic.

    The legacy account lease is deliberately left to expire instead of being
    released.  The existing scheduler therefore skips this account while a
    canary scan may still be reconciling Aster truth.  A busy legacy lease is
    fail-closed: the canary sends no order and releases only its queue lease.
    """
    control_plane.verify_internal_cloud_request(authorization)
    if (
        not _live_gates_open()
        or os.getenv(control_plane.QUEUE_FEATURE_FLAG, "false").lower() != "true"
    ):
        return {"processed": 0, "status": "centrally-disabled", "ordersSent": 0}

    controls = list(
        control_plane.db.collection("asterStrategy2")
        .where("monitor", "==", True)
        .stream()
    )
    selected = []
    for item in controls[:100]:
        raw = item.to_dict() or {}
        if bool(raw.get("orderQueueCanary", False)):
            selected.append((item, raw))
    if len(selected) != 1:
        return {
            "processed": 0,
            "status": "canary-selection-failed",
            "ordersSent": 0,
            "selectedAccounts": len(selected),
        }

    item, raw = selected[0]
    reference = control_plane.aster_strategy2_reference(item.id)
    account_ref = hashlib.sha256(item.id.encode()).hexdigest()[:12]
    if not bool(raw.get("enabled", False)) or not control_plane._strategy2_order_queue_enabled(
        raw
    ):
        return {
            "processed": 0,
            "status": "account-gate-disabled",
            "ordersSent": 0,
            "accountRef": account_ref,
        }

    queue_token = control_plane._acquire_strategy2_queue_lease(reference)
    if not queue_token:
        return {
            "processed": 0,
            "status": "queue-lease-busy",
            "ordersSent": 0,
            "accountRef": account_ref,
        }
    if not control_plane._acquire_mexc_automation_lease(reference):
        control_plane._release_strategy2_queue_lease(reference, queue_token)
        return {
            "processed": 0,
            "status": "legacy-lease-busy",
            "ordersSent": 0,
            "accountRef": account_ref,
        }
    try:
        result = control_plane._run_aster_strategy2_queue_scan(item.id)
        return {"processed": 1, "status": "ok", "accountRef": account_ref, **result}
    finally:
        control_plane._release_strategy2_queue_lease(reference, queue_token)
