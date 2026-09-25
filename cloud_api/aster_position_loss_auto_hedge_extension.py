"""API + server worker for per-position Auto Hedge.

The business logic lives in aster_position_loss_auto_hedge.py and is isolated
from the disabled legacy Portfolio Noodhedge / drawdown engines.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import threading
import time
from typing import Any

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field

import main
from aster_position_loss_auto_hedge import (
    DEFAULT_THRESHOLD_USD,
    evaluate_auto_hedge,
    normalize_threshold,
    reconcile_auto_hedge,
)


WORKER_ENABLED = os.getenv("ASTER_POSITION_LOSS_AUTO_HEDGE_WORKER", "true").lower() == "true"
EXECUTION_ENABLED = os.getenv("ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED", "false").lower() == "true"
WORKER_INTERVAL = max(1.0, float(os.getenv("ASTER_POSITION_LOSS_AUTO_HEDGE_INTERVAL_SECONDS", "3")))
_worker_stop = threading.Event()
_worker_thread: threading.Thread | None = None


class AutoHedgeSettingsRequest(BaseModel):
    enabled: bool
    thresholdUsd: float = Field(default=DEFAULT_THRESHOLD_USD, ge=0.01, le=100_000)


def _doc(uid: str):
    return main.db.collection("asterPositionLossAutoHedge").document(str(uid))


def _owner_uid() -> str:
    value = main.continuity_owner_reference().get().to_dict() or {}
    if value.get("enabled") is False:
        return ""
    return str(value.get("ownerUid") or "").strip()


def _dynamic_hedge_enabled(uid: str) -> bool:
    try:
        value = main.user_reference({"uid": uid}).collection("asterDynamicHedge").document("control").get().to_dict() or {}
    except Exception:
        return True
    return value.get("enabled") is True


def _current(uid: str) -> dict[str, Any]:
    row = _doc(uid).get().to_dict() or {}
    try:
        threshold = normalize_threshold(row.get("thresholdUsd", DEFAULT_THRESHOLD_USD))
    except ValueError:
        threshold = DEFAULT_THRESHOLD_USD
    return {
        **row,
        "enabled": row.get("enabled") is True,
        "thresholdUsd": threshold,
    }


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _public(uid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    row = data or _current(uid)
    enabled = row.get("enabled") is True
    operational = enabled and WORKER_ENABLED and EXECUTION_ENABLED
    return _serialize({
        "available": True,
        "ownerOnly": True,
        "enabled": enabled,
        "thresholdUsd": float(row.get("thresholdUsd", DEFAULT_THRESHOLD_USD)),
        "workerEnabled": WORKER_ENABLED,
        "executionEnabled": EXECUTION_ENABLED,
        "operational": operational,
        "status": "ACTIEF" if operational else ("ARMED" if enabled else "UIT"),
        "lastReport": row.get("lastReport"),
        "lastCheckedAt": row.get("lastCheckedAt"),
        "lastError": str(row.get("lastError", "")),
        "legacyPortfolioHedgeRegistered": False,
        "sourceOfTruth": "ASTER_POSITION_RISK",
        "quantityBasis": "COIN_QUANTITY",
        "comparison": "openPnl <= -thresholdUsd",
    })


def _audit(uid: str, payload: dict[str, Any]) -> None:
    main.user_reference({"uid": uid}).collection("autoHedgeAudit").add({
        "event": "POSITION_LOSS_AUTO_HEDGE",
        **payload,
        "timestamp": datetime.now(timezone.utc),
    })


def _client(uid: str, *, live: bool):
    user = {"uid": uid}
    secret = main.load_aster_secret(user)
    return main.AsterV3Client(
        signer_address=secret.signer_address,
        sign_message=main.local_eip712_signer(secret),
        live_authorized=bool(live),
        before_order_submit=main._block_order_during_close_all(uid),
    )


def _run_uid(uid: str, *, force_shadow: bool = False) -> dict[str, Any]:
    if not uid or uid != _owner_uid():
        return {"mode": "OFF", "ordersSent": 0, "status": "BLOCKED", "reason": "OWNER_ONLY", "actions": []}
    settings = _current(uid)
    if settings.get("enabled") is not True:
        report = {"mode": "OFF", "ordersSent": 0, "actions": []}
        _doc(uid).set({"lastReport": report, "lastCheckedAt": datetime.now(timezone.utc), "lastError": ""}, merge=True)
        return report

    if _dynamic_hedge_enabled(uid):
        report = {"mode": "OFF", "ordersSent": 0, "status": "BLOCKED", "reason": "DYNAMIC_HEDGE_CONFLICT", "actions": []}
        _doc(uid).set({"lastReport": report, "lastCheckedAt": datetime.now(timezone.utc), "lastError": ""}, merge=True)
        return report

    execute = EXECUTION_ENABLED and not force_shadow
    coordination_token: str | None = None
    try:
        if execute:
            coordination_token = main._acquire_aster_account_coordination(uid, "AUTO_HEDGE", "POSITION_LOSS_1_TO_1")
            if not coordination_token:
                report = {"mode": "LIVE", "ordersSent": 0, "status": "PENDING", "reason": "ACCOUNT_COORDINATION_BUSY", "actions": []}
                _doc(uid).set({"lastReport": report, "lastCheckedAt": datetime.now(timezone.utc)}, merge=True)
                return report
        client = _client(uid, live=execute)
        report = reconcile_auto_hedge(
            client=client,
            uid=uid,
            threshold_usd=settings["thresholdUsd"],
            execute=execute,
            audit=(lambda payload: _audit(uid, payload)),
        )
        _doc(uid).set({
            "lastReport": report,
            "lastCheckedAt": datetime.now(timezone.utc),
            "lastError": "",
            "updatedAt": datetime.now(timezone.utc),
        }, merge=True)
        return report
    except Exception as exc:
        report = {"mode": "LIVE" if execute else "SHADOW", "ordersSent": 0, "status": "FAILED", "reason": str(exc)[:500], "actions": []}
        _doc(uid).set({
            "lastReport": report,
            "lastCheckedAt": datetime.now(timezone.utc),
            "lastError": str(exc)[:1000],
            "updatedAt": datetime.now(timezone.utc),
        }, merge=True)
        return report
    finally:
        if coordination_token:
            main._release_aster_account_coordination(uid, coordination_token)


@main.app.get("/v1/me/aster/position-loss-auto-hedge")
def get_position_loss_auto_hedge(
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    try:
        uid = main.require_continuity_owner(user)
    except HTTPException as exc:
        if exc.status_code == 403:
            return {"available": False, "ownerOnly": True, "enabled": False, "thresholdUsd": DEFAULT_THRESHOLD_USD, "status": "UIT"}
        raise
    return _public(uid)


@main.app.put("/v1/me/aster/position-loss-auto-hedge")
def put_position_loss_auto_hedge(
    request: AutoHedgeSettingsRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    uid = main.require_continuity_owner(user)
    if request.enabled and _dynamic_hedge_enabled(uid):
        raise HTTPException(409, "Auto Hedge kan niet tegelijk met Dynamic Hedge actief zijn")
    try:
        threshold = normalize_threshold(request.thresholdUsd)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    now = datetime.now(timezone.utc)
    _doc(uid).set({
        "enabled": bool(request.enabled),
        "thresholdUsd": threshold,
        "updatedAt": now,
    }, merge=True)
    # Enabling evaluates all positions immediately, including positions that
    # were already far beyond the threshold before this request.
    if request.enabled:
        _run_uid(uid, force_shadow=not EXECUTION_ENABLED)
    response.headers["Cache-Control"] = "no-store"
    return _public(uid)


@main.app.post("/v1/me/aster/position-loss-auto-hedge/apply")
def apply_position_loss_auto_hedge(
    request: AutoHedgeSettingsRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    uid = main.require_continuity_owner(user)
    if request.enabled and _dynamic_hedge_enabled(uid):
        raise HTTPException(409, "Auto Hedge kan niet tegelijk met Dynamic Hedge actief zijn")
    try:
        threshold = normalize_threshold(request.thresholdUsd)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _doc(uid).set({
        "enabled": bool(request.enabled),
        "thresholdUsd": threshold,
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    report = _run_uid(uid, force_shadow=not EXECUTION_ENABLED) if request.enabled else {"mode": "OFF", "ordersSent": 0, "actions": []}
    response.headers["Cache-Control"] = "no-store"
    return {**_public(uid), "lastReport": _serialize(report)}


def _worker_loop() -> None:
    while not _worker_stop.wait(WORKER_INTERVAL):
        try:
            uid = _owner_uid()
            if not uid:
                continue
            value = _doc(uid).get().to_dict() or {}
            if value.get("enabled") is not True:
                continue
        except Exception:
            continue
        if _worker_stop.is_set():
            return
        _run_uid(uid, force_shadow=not EXECUTION_ENABLED)


@main.app.on_event("startup")
def start_position_loss_auto_hedge_worker() -> None:
    global _worker_thread
    if not WORKER_ENABLED:
        return
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_stop.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="position-loss-auto-hedge", daemon=True)
    _worker_thread.start()


@main.app.on_event("shutdown")
def stop_position_loss_auto_hedge_worker() -> None:
    _worker_stop.set()
