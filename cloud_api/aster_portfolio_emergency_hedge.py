"""Persistent Aster Portfolio Noodhedge.

Safety invariants:
- trigger source is Aster totalMarginBalance (the Portfolio Snapshot equity source)
- state is persisted per uid in Firestore and survives process restarts
- ARMED -> EXECUTING is acquired transactionally; one execution lease owner at a time
- every hedge amount is recomputed from authoritative Aster positionRisk after fills
- existing opposite legs are netted; blind retries and over-hedging are forbidden
- LOCKED never auto-unlocks

The module is deliberately installable on the existing FastAPI app so the legacy
entrypoint can remain intact.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import os
import secrets
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from fastapi import FastAPI, Header, HTTPException
from firebase_admin import auth, firestore
from pydantic import BaseModel, Field

from aster_gateway import (
    AsterApiError,
    AsterAutomationConfig,
    AsterOrderIntent,
    AsterSubmissionUncertain,
    AsterV3Client,
    AsterValidationError,
    ContractRules,
    PositionSide,
)
from aster_signing import local_eip712_signer
from aster_state import account_information_values

COLLECTION = "aster_portfolio_emergency_hedges"
STATUSES = {"OFF", "ARMED", "EXECUTING", "LOCKED"}
LEASE_SECONDS = 45
POLL_SECONDS = max(1.0, float(os.getenv("ASTER_EMERGENCY_HEDGE_POLL_SECONDS", "2")))
FILL_WAIT_SECONDS = max(2.0, float(os.getenv("ASTER_EMERGENCY_HEDGE_FILL_WAIT_SECONDS", "12")))
LIVE_ENABLED = os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "").lower() == "true"
EMERGENCY_PREFIX = "tm-eh-"
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(3)}"

_db = None
_load_secret: Callable[[dict[str, Any]], Any] | None = None
_auth_app = None
_task: asyncio.Task | None = None


class ArmRequest(BaseModel):
    enabled: bool = True
    start_portfolio_value: float = Field(gt=0, le=1_000_000_000)
    trigger_portfolio_value: float = Field(gt=0, le=1_000_000_000)


class DisableRequest(BaseModel):
    confirm: bool = True


class ManualUnlockRequest(BaseModel):
    confirm: bool


@dataclass(frozen=True)
class HedgeNeed:
    symbol: str
    position_side: PositionSide
    quantity: Decimal
    tolerance: Decimal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def calculations(start: float, trigger: float) -> dict[str, float]:
    if not math.isfinite(start) or not math.isfinite(trigger) or start <= 0:
        raise ValueError("Startwaarde moet positief zijn")
    if trigger <= 0 or trigger >= start:
        raise ValueError("Noodhedge-trigger moet boven US$0 en onder de startwaarde liggen")
    return {
        "triggerPercentage": trigger / start * 100.0,
        "maxAllowedLoss": start - trigger,
    }


def aggregate_positions(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", "")).upper().strip()
        qty = abs(_number(row.get("positionAmt")))
        if not symbol or side not in {"LONG", "SHORT"} or qty <= 0:
            continue
        bucket = result.setdefault(symbol, {"LONG": 0.0, "SHORT": 0.0})
        bucket[side] += qty
    return result


def missing_hedges(rows: list[dict[str, Any]], rules: dict[str, ContractRules] | None = None) -> list[HedgeNeed]:
    needs: list[HedgeNeed] = []
    for symbol, sides in aggregate_positions(rows).items():
        delta = sides["LONG"] - sides["SHORT"]
        rule = (rules or {}).get(symbol)
        step = rule.market_quantity_step if rule else Decimal("0.00000001")
        minimum = rule.market_min_quantity if rule else Decimal("0")
        tolerance = max(step, minimum, Decimal("0.00000001"))
        quantity = Decimal(str(abs(delta)))
        if quantity <= tolerance:
            continue
        needs.append(HedgeNeed(
            symbol=symbol,
            position_side=PositionSide.SHORT if delta > 0 else PositionSide.LONG,
            quantity=quantity,
            tolerance=tolerance,
        ))
    return needs


def _doc(uid: str):
    return _db.collection(COLLECTION).document(uid)


def _public(value: dict[str, Any] | None, current: float | None = None) -> dict[str, Any]:
    data = dict(value or {})
    return {
        "enabled": bool(data.get("enabled", False)),
        "armed": bool(data.get("armed", False)),
        "status": str(data.get("status", "OFF")),
        "startPortfolioValue": _number(data.get("startPortfolioValue")),
        "triggerPortfolioValue": _number(data.get("triggerPortfolioValue")),
        "triggerPercentage": _number(data.get("triggerPercentage")),
        "maxAllowedLoss": _number(data.get("maxAllowedLoss")),
        "currentPortfolioValue": current,
        "activatedAt": data.get("activatedAt"),
        "updatedAt": data.get("updatedAt"),
        "triggeredAt": data.get("triggeredAt"),
        "lockedAt": data.get("lockedAt"),
        "lastError": str(data.get("lastError", "")),
        "reference": "file_00000000ca148210b52f9a8befc68d22",
    }


def _verify_user(authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Firebase ID-token ontbreekt")
    try:
        token = authorization.split(" ", 1)[1].strip()
        decoded = auth.verify_id_token(token, app=_auth_app, check_revoked=False)
    except Exception as exc:
        raise HTTPException(401, "Ongeldige of verlopen sessie") from exc
    uid = str(decoded.get("uid", "")).strip()
    if not uid:
        raise HTTPException(401, "Gebruikerssessie heeft geen uid")
    return {**decoded, "uid": uid}


def _client(uid: str, *, live: bool) -> AsterV3Client:
    if _load_secret is None:
        raise RuntimeError("Noodhedge is niet geïnstalleerd")
    secret = _load_secret({"uid": uid})
    return AsterV3Client(
        signer_address=secret.signer_address,
        sign_message=local_eip712_signer(secret),
        live_authorized=bool(live and LIVE_ENABLED),
    )


def _portfolio_truth(client: AsterV3Client) -> tuple[float, float]:
    account = client.account_information()
    equity, _wallet, available, _pnl, _maintenance = account_information_values(account)
    if equity <= 0:
        raise AsterApiError("PORTFOLIOWAARDE kon niet betrouwbaar bij Aster worden gelezen")
    return equity, available


def _contract_rules(client: AsterV3Client) -> dict[str, ContractRules]:
    info = client.public_exchange_info()
    return {
        str(row.get("symbol", "")).upper(): ContractRules.from_exchange_info(row)
        for row in info.get("symbols", []) if isinstance(row, dict) and row.get("symbol")
    }


def _lease_expired(data: dict[str, Any], now: datetime) -> bool:
    until = data.get("leaseUntil")
    return not isinstance(until, datetime) or until <= now


def _acquire_execution(uid: str, current: float) -> bool:
    ref = _doc(uid)
    transaction = _db.transaction()

    @firestore.transactional
    def apply(txn):
        snap = ref.get(transaction=txn)
        data = snap.to_dict() or {}
        now = _now()
        status = str(data.get("status", "OFF"))
        trigger = _number(data.get("triggerPortfolioValue"))
        if not data.get("enabled") or not data.get("armed") or trigger <= 0:
            return False
        if status == "LOCKED":
            return False
        if status == "ARMED":
            if current > trigger:
                return False
            txn.set(ref, {
                "status": "EXECUTING", "triggeredAt": data.get("triggeredAt") or now,
                "updatedAt": now, "leaseOwner": WORKER_ID,
                "leaseUntil": now + timedelta(seconds=LEASE_SECONDS),
                "lastObservedPortfolioValue": current,
            }, merge=True)
            return True
        if status == "EXECUTING" and (_lease_expired(data, now) or data.get("leaseOwner") == WORKER_ID):
            txn.set(ref, {
                "leaseOwner": WORKER_ID, "leaseUntil": now + timedelta(seconds=LEASE_SECONDS),
                "updatedAt": now, "lastObservedPortfolioValue": current,
            }, merge=True)
            return True
        return False

    return bool(apply(transaction))


def _renew(uid: str, **extra: Any) -> None:
    now = _now()
    _doc(uid).set({
        "leaseOwner": WORKER_ID,
        "leaseUntil": now + timedelta(seconds=LEASE_SECONDS),
        "updatedAt": now,
        **extra,
    }, merge=True)


def _cancel_interfering_orders(client: AsterV3Client) -> int:
    cancelled = 0
    for order in client.open_orders():
        cid = str(order.get("clientOrderId", order.get("origClientOrderId", "")))
        if cid.startswith(EMERGENCY_PREFIX):
            continue
        symbol = str(order.get("symbol", "")).upper()
        oid = order.get("orderId")
        if not symbol or oid is None:
            continue
        try:
            client.cancel_order(symbol, order_id=oid)
            cancelled += 1
        except AsterApiError:
            # A fill/cancel race is reconciled from positionRisk below.
            pass
    return cancelled


def _intent_id(uid: str, generation: int, need: HedgeNeed, attempt: int) -> str:
    digest = hashlib.sha1(f"{uid}:{generation}:{need.symbol}:{need.position_side.value}:{attempt}".encode()).hexdigest()[:10]
    return f"{EMERGENCY_PREFIX}{generation}-{digest}"[:36]


def _terminal_status(value: Any) -> str:
    return str(value or "").upper().replace(" ", "_")


def _submit_one(client: AsterV3Client, uid: str, generation: int, need: HedgeNeed, rules: dict[str, ContractRules], attempt: int) -> None:
    row = rules.get(need.symbol)
    if row is None:
        raise AsterValidationError(f"Contractregels ontbreken voor {need.symbol}")
    positions = client.position_risk(need.symbol)
    mark = max((_number(item.get("markPrice")) for item in positions), default=0.0)
    if mark <= 0:
        raise AsterApiError(f"Actuele markprijs ontbreekt voor {need.symbol}")
    try:
        quantity = row.market_quantity(need.quantity, mark)
    except AsterValidationError:
        # A residual smaller than the contract minimum is within executable tolerance.
        if need.quantity <= max(row.market_min_quantity, row.market_quantity_step):
            return
        raise
    if quantity <= 0:
        return
    intent = AsterOrderIntent(
        intent_id=_intent_id(uid, generation, need, attempt),
        symbol=need.symbol,
        position_side=need.position_side,
        quantity=quantity,
        action="OPEN",
    )
    config = AsterAutomationConfig(enabled=True, mode="live", hedge_mode_required=True, websocket_required=False)
    try:
        response, _recovered = client.submit_order_once(
            intent, config=config, confirm=True, hedge_mode_confirmed=True, risk_approved=True,
        )
    except AsterSubmissionUncertain:
        # Never issue a second POST for an uncertain id. Leave EXECUTING; the next pass
        # first reconciles positionRisk and the deterministic client order id.
        raise
    deadline = time.monotonic() + FILL_WAIT_SECONDS
    while time.monotonic() < deadline:
        current = client.query_order(need.symbol, intent.intent_id)
        status = _terminal_status(current.get("status", response.get("status")))
        if status in {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}:
            return
        # MARKET partial fills are authoritative. Reconciliation happens outside this
        # function; do not submit the remainder while this order remains open.
        time.sleep(0.35)
    raise AsterSubmissionUncertain(f"Noodhedge-order {intent.intent_id} heeft nog geen terminale fillstatus")


def execute(uid: str) -> dict[str, Any]:
    if not LIVE_ENABLED:
        raise RuntimeError("ASTER_LIVE_EXECUTION_ENABLED staat niet aan")
    ref = _doc(uid)
    data = ref.get().to_dict() or {}
    if str(data.get("status")) != "EXECUTING":
        return data
    generation = int(_number(data.get("generation")) or 1)
    client = _client(uid, live=True)
    if not client.position_mode():
        raise AsterValidationError("Portfolio Noodhedge vereist Aster Hedge Mode")
    cancelled = _cancel_interfering_orders(client)
    rules = _contract_rules(client)
    attempt = 0
    while attempt < 200:
        attempt += 1
        positions = client.position_risk()
        needs = missing_hedges(positions, rules)
        if not needs:
            now = _now()
            ref.set({
                "enabled": True, "armed": False, "status": "LOCKED", "lockedAt": now,
                "updatedAt": now, "leaseOwner": None, "leaseUntil": None,
                "lastError": "", "cancelledOrders": cancelled,
            }, merge=True)
            return ref.get().to_dict() or {}
        equity, available = _portfolio_truth(client)
        if available <= 0:
            raise AsterApiError("Onvoldoende Available to Trade om ontbrekende noodhedge uit te voeren")
        _renew(uid, lastObservedPortfolioValue=equity, remainingSymbols=[n.symbol for n in needs])
        # One order at a time. After every fill/status transition positionRisk is read
        # again before another amount is calculated; this is the over-hedge guard.
        _submit_one(client, uid, generation, needs[0], rules, attempt)
    raise RuntimeError("Noodhedge bereikte de maximale reconciliatiepogingen zonder 1:1 lock")


async def _tick_uid(uid: str) -> None:
    try:
        read_client = _client(uid, live=False)
        equity, _available = await asyncio.to_thread(_portfolio_truth, read_client)
        if not _acquire_execution(uid, equity):
            _doc(uid).set({"lastObservedPortfolioValue": equity, "lastCheckedAt": _now()}, merge=True)
            return
        await asyncio.to_thread(execute, uid)
    except Exception as exc:
        data = _doc(uid).get().to_dict() or {}
        if str(data.get("status")) == "EXECUTING":
            _doc(uid).set({
                "lastError": str(exc)[:1000], "updatedAt": _now(),
                "leaseUntil": _now() + timedelta(seconds=min(LEASE_SECONDS, 10)),
            }, merge=True)


async def monitor_loop() -> None:
    while True:
        try:
            docs = await asyncio.to_thread(lambda: list(_db.collection(COLLECTION).stream()))
            for snap in docs:
                data = snap.to_dict() or {}
                if data.get("enabled") and str(data.get("status")) in {"ARMED", "EXECUTING"}:
                    await _tick_uid(snap.id)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(POLL_SECONDS)


def install(app: FastAPI, *, db: Any, load_secret: Callable[[dict[str, Any]], Any], auth_app: Any) -> None:
    global _db, _load_secret, _auth_app
    _db, _load_secret, _auth_app = db, load_secret, auth_app

    @app.get("/v1/me/aster/portfolio-emergency-hedge")
    def get_state(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        user = _verify_user(authorization)
        client = _client(user["uid"], live=False)
        current, _available = _portfolio_truth(client)
        return _public(_doc(user["uid"]).get().to_dict(), current)

    @app.put("/v1/me/aster/portfolio-emergency-hedge")
    def arm(request: ArmRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        user = _verify_user(authorization)
        uid = user["uid"]
        if not request.enabled:
            existing = _doc(uid).get().to_dict() or {}
            if str(existing.get("status")) in {"EXECUTING", "LOCKED"}:
                raise HTTPException(409, "Een uitgevoerde Portfolio Lock kan alleen bewust handmatig worden beëindigd")
            _doc(uid).set({"enabled": False, "armed": False, "status": "OFF", "updatedAt": _now()}, merge=True)
            return _public(_doc(uid).get().to_dict())
        values = calculations(request.start_portfolio_value, request.trigger_portfolio_value)
        # Do not silently replace a saved baseline: this write only happens after the
        # explicit Opslaan & activeren action in the UI.
        previous = _doc(uid).get().to_dict() or {}
        generation = int(_number(previous.get("generation"))) + 1
        now = _now()
        _doc(uid).set({
            "enabled": True, "armed": True, "status": "ARMED",
            "startPortfolioValue": request.start_portfolio_value,
            "triggerPortfolioValue": request.trigger_portfolio_value,
            **values, "activatedAt": now, "updatedAt": now, "triggeredAt": None,
            "lockedAt": None, "lastError": "", "generation": generation,
            "leaseOwner": None, "leaseUntil": None,
        }, merge=True)
        return _public(_doc(uid).get().to_dict())

    @app.post("/v1/me/aster/portfolio-emergency-hedge/unlock")
    def unlock(request: ManualUnlockRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        user = _verify_user(authorization)
        if not request.confirm:
            raise HTTPException(422, "Handmatige bevestiging is verplicht")
        data = _doc(user["uid"]).get().to_dict() or {}
        if str(data.get("status")) != "LOCKED":
            raise HTTPException(409, "Portfolio is niet LOCKED")
        _doc(user["uid"]).set({
            "enabled": False, "armed": False, "status": "OFF", "updatedAt": _now(),
            "leaseOwner": None, "leaseUntil": None, "manualUnlockedAt": _now(),
        }, merge=True)
        return _public(_doc(user["uid"]).get().to_dict())

    @app.on_event("startup")
    async def _start_monitor() -> None:
        global _task
        if os.getenv("ASTER_EMERGENCY_HEDGE_WORKER", "true").lower() == "true" and (_task is None or _task.done()):
            _task = asyncio.create_task(monitor_loop(), name="aster-portfolio-emergency-hedge")

    @app.on_event("shutdown")
    async def _stop_monitor() -> None:
        global _task
        if _task is not None:
            _task.cancel()
            try:
                await _task
            except asyncio.CancelledError:
                pass
            _task = None
