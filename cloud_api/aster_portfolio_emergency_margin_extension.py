"""Runtime safety extension for Portfolio Noodhedge margin preservation.

The base emergency hedge remains intentionally small. This extension augments
its monitor with a conservative reserve calculation and may enter EXECUTING
before the user's equity floor when waiting longer would consume the estimated
margin required to build the 1:1 hedge.

The user's configured equity floor is never changed. Early execution is recorded
as MARGIN_SAFETY_OVERRIDE and is visible in persisted state.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from aster_portfolio_emergency_margin import estimate_emergency_margin
import aster_portfolio_emergency_hedge as emergency

_INSTALLED = False
_ORIGINAL_PUBLIC = emergency._public


def _extended_public(value: dict[str, Any] | None, current: float | None = None) -> dict[str, Any]:
    data = dict(value or {})
    result = _ORIGINAL_PUBLIC(data, current)
    result.update({
        "estimatedHedgeNotionalUsd": emergency._number(data.get("estimatedHedgeNotionalUsd")),
        "estimatedHedgeMarginUsd": emergency._number(data.get("estimatedHedgeMarginUsd")),
        "hedgeReserveUsd": emergency._number(data.get("hedgeReserveUsd")),
        "technicalTriggerAvailableUsd": emergency._number(data.get("technicalTriggerAvailableUsd")),
        "availableBalanceUsd": emergency._number(data.get("availableBalanceUsd")),
        "hedgeHeadroomUsd": emergency._number(data.get("hedgeHeadroomUsd")),
        "hedgeFeasibleNow": bool(data.get("hedgeFeasibleNow", True)),
        "technicalSafetyOverride": bool(data.get("technicalSafetyOverride", False)),
        "triggerReason": str(data.get("triggerReason", "")),
    })
    return result


def _acquire_execution(uid: str, current: float, *, technical_override: bool = False) -> bool:
    ref = emergency._doc(uid)
    transaction = emergency._db.transaction()

    @emergency.firestore.transactional
    def apply(txn):
        snap = ref.get(transaction=txn)
        data = snap.to_dict() or {}
        now = emergency._now()
        status = str(data.get("status", "OFF"))
        trigger = emergency._number(data.get("triggerPortfolioValue"))
        if not data.get("enabled") or not data.get("armed") or trigger <= 0:
            return False
        if status == "LOCKED":
            return False
        if status == "ARMED":
            if current > trigger and not technical_override:
                return False
            reason = "MARGIN_SAFETY_OVERRIDE" if technical_override and current > trigger else "PORTFOLIO_FLOOR"
            txn.set(ref, {
                "status": "EXECUTING",
                "triggeredAt": data.get("triggeredAt") or now,
                "triggerReason": reason,
                "updatedAt": now,
                "leaseOwner": emergency.WORKER_ID,
                "leaseUntil": now + timedelta(seconds=emergency.LEASE_SECONDS),
                "lastObservedPortfolioValue": current,
            }, merge=True)
            return True
        if status == "EXECUTING" and (
            emergency._lease_expired(data, now) or data.get("leaseOwner") == emergency.WORKER_ID
        ):
            txn.set(ref, {
                "leaseOwner": emergency.WORKER_ID,
                "leaseUntil": now + timedelta(seconds=emergency.LEASE_SECONDS),
                "updatedAt": now,
                "lastObservedPortfolioValue": current,
            }, merge=True)
            return True
        return False

    return bool(apply(transaction))


async def _tick_uid(uid: str) -> None:
    try:
        read_client = emergency._client(uid, live=False)
        equity, available = await asyncio.to_thread(emergency._portfolio_truth, read_client)
        positions = await asyncio.to_thread(read_client.position_risk)
        estimate = estimate_emergency_margin(positions, available)
        reserve = estimate.public_dict()
        emergency._doc(uid).set({
            **reserve,
            "lastObservedPortfolioValue": equity,
            "lastCheckedAt": emergency._now(),
        }, merge=True)
        if not _acquire_execution(uid, equity, technical_override=estimate.technical_override):
            return
        await asyncio.to_thread(emergency.execute, uid)
    except Exception as exc:
        data = emergency._doc(uid).get().to_dict() or {}
        if str(data.get("status")) == "EXECUTING":
            emergency._doc(uid).set({
                "lastError": str(exc)[:1000],
                "updatedAt": emergency._now(),
                "leaseUntil": emergency._now() + timedelta(seconds=min(emergency.LEASE_SECONDS, 10)),
            }, merge=True)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    emergency._public = _extended_public
    emergency._acquire_execution = _acquire_execution
    emergency._tick_uid = _tick_uid
    _INSTALLED = True
