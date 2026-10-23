"""API, lifecycle persistence and server worker for Auto Hedge 2.0.

Build 431 keeps production order execution behind
ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED=false while adding the complete
pair lifecycle needed for exact 1:1 protection, HEDGE_LOCKED allocations,
RECOVERY and explicit per-pair re-arming.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import re
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
    position_open_pnl,
    position_quantity,
    reconcile_auto_hedge,
)
from aster_gateway import ContractRules
from short_recovery_runtime import decide as short_recovery_decide
from short_recovery_ladder import normalize_settings as normalize_short_recovery_settings
import short_recovery_pair_exit

WORKER_ENABLED = os.getenv("ASTER_POSITION_LOSS_AUTO_HEDGE_WORKER", "true").lower() == "true"
EXECUTION_ENABLED = os.getenv("ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED", "false").lower() == "true"
# SHORT Recovery 2.0: real orders by default (besluit Amar 23-10 02:00: echt, voor iedereen gelijk).
# Each user still switches SHORT afbouwen ON/OFF on their own account. Emergency stop: set the env to
# "false" -> shadow only (decisions recorded, no target change, no orders) for everyone.
SHORT_RECOVERY_EXECUTION_ENABLED = os.getenv("ASTER_SHORT_RECOVERY_EXECUTION_ENABLED", "true").lower() == "true"
HEDGE_MODE_REQUIRED_MESSAGE = (
    "Auto Hedge vereist Hedge Mode op je Aster-account. Je account staat nu op One-way mode. "
    "Zet in Aster de positiemodus op Hedge Mode (dat kan alleen zonder open posities en open orders) "
    "en probeer het daarna opnieuw. Er is niets gewijzigd."
)
HEDGE_MODE_UNKNOWN_MESSAGE = (
    "De positiemodus van je Aster-account kon niet worden gecontroleerd. Er is niets gewijzigd; "
    "probeer het over enkele seconden opnieuw."
)
HEDGE_MODE_CACHE_SECONDS = 300.0
_hedge_mode_ok_at: dict[str, float] = {}
_hedge_mode_lock = threading.Lock()
WORKER_INTERVAL = max(1.0, float(os.getenv("ASTER_POSITION_LOSS_AUTO_HEDGE_INTERVAL_SECONDS", "3")))
_worker_stop = threading.Event()
_worker_thread: threading.Thread | None = None

ACTIVE_STATUSES = {"HEDGING", "HEDGED", "ADJUSTING", "BLOCKED", "ERROR", "PRECISION_BLOCKED"}
RECOVERY_STATUSES = {"RECOVERY", "REHEDGE_ARMED", "DISABLED", "MANUAL_RELEASE_PENDING", "MANUAL_RELEASE_UNCERTAIN"}
REHEDGEABLE_STATUSES = {"RECOVERY", "REHEDGE_ARMED", "DISABLED"}
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,36}USDT$")


class AutoHedgeSettingsRequest(BaseModel):
    enabled: bool
    thresholdUsd: float = Field(default=DEFAULT_THRESHOLD_USD, ge=0.01, le=100_000)
    confirmDisable: bool = False
    clientBuild: str = Field(default="", max_length=32)
    clientSource: str = Field(default="", max_length=64)


class RehedgeRequest(BaseModel):
    enabled: bool


def _doc(uid: str):
    return main.db.collection("asterPositionLossAutoHedge").document(str(uid))


def _pair_collection(uid: str):
    return _doc(uid).collection("pairs")


def _pair_doc(uid: str, symbol: str):
    return _pair_collection(uid).document(str(symbol).upper())


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


def _pair_states(uid: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for snapshot in _pair_collection(uid).stream():
        value = snapshot.to_dict() or {}
        symbol = str(value.get("symbol") or snapshot.id).upper().strip()
        if symbol:
            rows[symbol] = {**value, "symbol": symbol}
    return rows


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        stamp = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return stamp.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _pair_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    priority = {
        "BLOCKED": 0, "ERROR": 0, "PRECISION_BLOCKED": 0,
        "ADJUSTING": 1, "HEDGING": 1, "HEDGED": 2,
        "MANUAL_RELEASE_UNCERTAIN": 0, "MANUAL_RELEASE_PENDING": 1,
        "REHEDGE_ARMED": 3, "RECOVERY": 4, "DISABLED": 5, "CLOSED": 6,
    }
    return priority.get(str(row.get("status", "")).upper(), 9), str(row.get("symbol", ""))


def _public(uid: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    row = data or _current(uid)
    enabled = row.get("enabled") is True
    operational = enabled and WORKER_ENABLED and EXECUTION_ENABLED
    pairs = sorted(
        (_serialize(value) for value in _pair_states(uid).values()
         if str(value.get("status", "")).upper() != "CLOSED"),
        key=_pair_sort_key,
    )
    report = row.get("lastReport") if isinstance(row.get("lastReport"), dict) else None
    preview = []
    if report and str(report.get("mode", "")).upper() == "SHADOW":
        preview = [item for item in report.get("actions", []) if isinstance(item, dict)]
    return _serialize({
        "available": True,
        "ownerOnly": False,
        "releaseFeature": "auto_hedge_v2",
        "legacyHedgeRecoveryAvailable": main._release_feature_enabled_for_uid(uid, "legacy_hedge_recovery"),
        "enabled": enabled,
        "thresholdUsd": float(row.get("thresholdUsd", DEFAULT_THRESHOLD_USD)),
        "workerEnabled": WORKER_ENABLED,
        "executionEnabled": EXECUTION_ENABLED,
        "operational": operational,
        "status": "ACTIEF" if operational else ("TEST" if enabled else "UIT"),
        "lastReport": report,
        "lastCheckedAt": row.get("lastCheckedAt"),
        "lastError": str(row.get("lastError", "")),
        "pairs": pairs,
        "previewPairs": preview,
        "legacyPortfolioHedgeRegistered": False,
        "sourceOfTruth": "ASTER_POSITION_RISK",
        "quantityBasis": "COIN_QUANTITY",
        "comparison": "openPnl <= -thresholdUsd",
        "targetInvariant": "ABS(LONG_QTY)==ABS(SHORT_QTY)",
        "shortRecoveryPlan": _public_short_recovery(row),
        "shortRecoveryExecutionEnabled": SHORT_RECOVERY_EXECUTION_ENABLED,
        "referenceId": "file_00000000ecd08246bd1b15532fb478d6",
    })


def _public_short_recovery(row: dict[str, Any]) -> dict[str, Any]:
    try:
        return normalize_short_recovery_settings(row.get("shortRecoveryPlan") if isinstance(row.get("shortRecoveryPlan"), dict) else {})
    except ValueError:
        return normalize_short_recovery_settings({})


def _audit(uid: str, payload: dict[str, Any]) -> None:
    main.user_reference({"uid": uid}).collection("autoHedgeAudit").add({
        "event": "POSITION_LOSS_AUTO_HEDGE_V2",
        **payload,
        "timestamp": datetime.now(timezone.utc),
    })


def _audit_global_setting_change(
    uid: str,
    *,
    previous_enabled: bool,
    requested_enabled: bool,
    request: AutoHedgeSettingsRequest,
    source_route: str,
    result: str,
) -> None:
    _audit(uid, {
        "eventType": "GLOBAL_SETTINGS_CHANGE",
        "previousEnabled": bool(previous_enabled),
        "requestedEnabled": bool(requested_enabled),
        "confirmDisable": bool(request.confirmDisable),
        "thresholdUsd": float(request.thresholdUsd),
        "clientBuild": str(request.clientBuild or "")[:32],
        "clientSource": str(request.clientSource or "")[:64],
        "sourceRoute": source_route,
        "result": result,
    })


def _hedge_mode_ok(uid: str, client: Any = None) -> bool:
    """True only when Aster confirms Hedge Mode (dualSidePosition). Errors propagate (fail closed).

    A confirmed Hedge Mode is cached briefly (Aster only allows switching without open positions/orders);
    a One-way answer is never cached, so switching to Hedge Mode works on the next try.
    """
    now = time.monotonic()
    with _hedge_mode_lock:
        stamp = _hedge_mode_ok_at.get(uid)
    if stamp is not None and now - stamp < HEDGE_MODE_CACHE_SECONDS:
        return True
    ok = bool((client or _client(uid, live=False)).position_mode())
    with _hedge_mode_lock:
        if ok:
            _hedge_mode_ok_at[uid] = now
        else:
            _hedge_mode_ok_at.pop(uid, None)
    return ok


def _require_hedge_mode(uid: str) -> None:
    """Clean user-facing refusal before switching on anything that can place hedge orders."""
    try:
        ok = _hedge_mode_ok(uid)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, HEDGE_MODE_UNKNOWN_MESSAGE) from exc
    if not ok:
        raise HTTPException(409, HEDGE_MODE_REQUIRED_MESSAGE)


def _client(uid: str, *, live: bool):
    user = {"uid": uid}
    secret = main.load_aster_secret(user)
    return main.AsterV3Client(
        signer_address=secret.signer_address,
        sign_message=main.local_eip712_signer(secret),
        live_authorized=bool(live),
        before_order_submit=main._block_order_during_close_all(uid, allow_auto_hedge_locked=True),
    )


def _position_map(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", row.get("side", ""))).upper().strip()
        if symbol and side in {"LONG", "SHORT"} and position_quantity(row) > 0:
            result[(symbol, side)] = row
    return result


def _leg_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, dict) or position_quantity(row) <= 0:
        return None
    return {
        "quantity": position_quantity(row),
        "entryPrice": float(row.get("entryPrice") or 0),
        "markPrice": float(row.get("markPrice") or row.get("entryPrice") or 0),
        "openPnl": position_open_pnl(row),
        "leverage": float(row.get("leverage") or 0),
    }


def _opposite(side: str) -> str:
    return "SHORT" if str(side).upper() == "LONG" else "LONG"


def _new_cycle_state(action: Any, prior: dict[str, Any] | None, threshold: float) -> dict[str, Any]:
    previous_generation = int(float((prior or {}).get("generation") or 0))
    generation = previous_generation + 1
    now = datetime.now(timezone.utc)
    return {
        "symbol": action.symbol,
        "status": "HEDGING",
        "protectedSide": action.protected_side,
        "hedgeSide": action.hedge_side,
        "generation": generation,
        "generationId": f"g{generation}",
        "intentRevision": 0,
        "triggerThresholdUsd": threshold,
        "triggerPnl": action.protected_open_pnl,
        "triggerAt": now,
        "recoveryAt": None,
        "rehedgeEnabled": False,
        "preExistingOppositeQty": action.existing_hedge_qty,
        "autoHedgeAddedQty": 0.0,
        "reservedHedgeQty": 0.0,
        "normalFreeQty": action.existing_hedge_qty,
        "exchangeOrderIds": [],
        "clientOrderIds": [],
        "createdAt": (prior or {}).get("createdAt") or now,
        "updatedAt": now,
    }


def _transition_missing_protected(
    uid: str,
    state: dict[str, Any],
    pmap: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    symbol = str(state.get("symbol", "")).upper()
    protected_side = str(state.get("protectedSide", "")).upper()
    hedge_side = str(state.get("hedgeSide", _opposite(protected_side))).upper()
    protected = pmap.get((symbol, protected_side))
    hedge = pmap.get((symbol, hedge_side))
    if protected and position_quantity(protected) > 0:
        return state
    now = datetime.now(timezone.utc)
    if hedge and position_quantity(hedge) > 0:
        next_state = {
            **state,
            "status": "RECOVERY",
            "reservedHedgeQty": 0.0,
            "normalFreeQty": position_quantity(hedge),
            "rehedgeEnabled": False,
            "recoveryAt": now,
            "currentProtectedQty": 0.0,
            "currentHedgeQty": position_quantity(hedge),
            "protectedLeg": None,
            "hedgeLeg": _leg_view(hedge),
            "lastReason": "PROTECTED_LEG_CLOSED_RECOVERY_REMAINS",
            "updatedAt": now,
        }
    else:
        next_state = {
            **state,
            "status": "CLOSED",
            "reservedHedgeQty": 0.0,
            "normalFreeQty": 0.0,
            "rehedgeEnabled": False,
            "closedAt": now,
            "currentProtectedQty": 0.0,
            "currentHedgeQty": 0.0,
            "protectedLeg": None,
            "hedgeLeg": None,
            "lastReason": "PAIR_FLAT",
            "updatedAt": now,
        }
    _pair_doc(uid, symbol).set(next_state, merge=True)
    _audit(uid, {
        "symbol": symbol,
        "pairCycleId": str(state.get("generationId", "")),
        "resultingStatus": next_state["status"],
        "reason": next_state["lastReason"],
        "protectedQtyAfter": 0.0,
        "hedgeQtyAfter": next_state["currentHedgeQty"],
    })
    return next_state


def _force_rehedge_cycle(
    *,
    uid: str,
    symbol: str,
    state: dict[str, Any],
    status: str,
    remaining_side: str,
    remaining: dict[str, Any],
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    threshold: float,
    execute: bool,
    results: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Re-Hedge All: start the SAME new cycle the threshold path starts, but without waiting for a loss.

    Only a surviving LONG gets a SHORT hedge. The hedge size is NOT decided here: the existing engine
    (reconcile_auto_hedge) tops the SHORT up to exactly the live LONG quantity, counting the current SHORT and
    pending SHORT orders, flooring to the contract step and never exceeding the LONG. Returns None to skip.
    """
    mark = float(remaining.get("markPrice") or remaining.get("entryPrice") or 0)
    base = {"symbol": symbol, "markPrice": mark, "longQty": position_quantity(remaining)}
    if status not in REHEDGEABLE_STATUSES:
        results[symbol] = {**base, "result": "SKIPPED", "reason": "MANUAL_RELEASE_NOT_CONFIRMED"}
        return None
    if remaining_side != "LONG":
        results[symbol] = {**base, "result": "SKIPPED", "reason": "SURVIVOR_IS_SHORT"}
        return None
    action = next((a for a in evaluate_auto_hedge(
        positions, threshold, open_orders=open_orders,
        protected_sides={symbol: "LONG"}, skip_symbols=set(),
    ) if a.symbol == symbol), None)
    if action is None:
        results[symbol] = {**base, "result": "SKIPPED", "reason": "POSITION_UNREADABLE"}
        return None
    base.update({
        "shortQtyBefore": action.existing_hedge_qty,
        "pendingShortOpenQty": action.pending_open_qty,
        "pendingShortCloseQty": action.pending_close_qty,
        "missingShortQty": max(0.0, action.delta_qty),
    })
    if action.delta_qty < 0:
        # Already over-hedged: this button never opens or reduces anything for such a pair.
        results[symbol] = {**base, "result": "SKIPPED", "reason": "OVER_HEDGED"}
        return None
    new_state = {**_new_cycle_state(action, state, threshold), "triggerReason": "USER_REHEDGE_ALL"}
    if execute:
        _pair_doc(uid, symbol).set(new_state, merge=True)
        _audit(uid, {
            "eventType": "REHEDGE_ALL_CYCLE_STARTED",
            "symbol": symbol,
            "pairCycleId": new_state["generationId"],
            "previousStatus": status,
            "protectedSide": "LONG",
            "hedgeSide": "SHORT",
            "protectedQty": action.protected_qty,
            "hedgeQtyBefore": action.existing_hedge_qty,
            "pendingOpenQty": action.pending_open_qty,
            "requestedDelta": action.required_delta,
            "reason": "USER_REHEDGE_ALL",
        })
    results[symbol] = {**base, "result": "STARTED", "reason": "USER_REHEDGE_ALL", "generationId": new_state["generationId"]}
    return new_state


def _prepare_lifecycle(
    *,
    uid: str,
    settings: dict[str, Any],
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    execute: bool,
    allow_new_triggers: bool = True,
    force_rehedge_symbols: set[str] | None = None,
    force_results: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, str], set[str], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    threshold = float(settings["thresholdUsd"])
    # Re-Hedge All: user-chosen Recovery pairs start a new exact 1:1 cycle NOW, without the loss threshold.
    force = {str(item).upper() for item in (force_rehedge_symbols or set())}
    if force_results is None:
        force_results = {}
    pmap = _position_map(positions)
    states = _pair_states(uid)
    active: dict[str, str] = {}
    skip: set[str] = set()
    created: list[dict[str, Any]] = []

    for symbol, original in list(states.items()):
        state = dict(original)
        status = str(state.get("status", "")).upper()
        if status in ACTIVE_STATUSES:
            state = _transition_missing_protected(uid, state, pmap) if execute else state
            status = str(state.get("status", "")).upper()
            if status in ACTIVE_STATUSES:
                side = str(state.get("protectedSide", "")).upper()
                if side in {"LONG", "SHORT"} and pmap.get((symbol, side)):
                    active[symbol] = side
                    continue
        if status in RECOVERY_STATUSES:
            remaining_side = str(state.get("hedgeSide", "")).upper()
            remaining = pmap.get((symbol, remaining_side))
            if not remaining:
                if execute:
                    now = datetime.now(timezone.utc)
                    _pair_doc(uid, symbol).set({
                        "status": "CLOSED", "rehedgeEnabled": False, "closedAt": now,
                        "currentHedgeQty": 0.0, "reservedHedgeQty": 0.0,
                        "normalFreeQty": 0.0, "updatedAt": now,
                    }, merge=True)
                if symbol in force:
                    force_results[symbol] = {"symbol": symbol, "result": "SKIPPED", "reason": "POSITION_CLOSED"}
                skip.add(symbol)
                continue
            if symbol in force and allow_new_triggers and settings.get("enabled") is True:
                new_state = _force_rehedge_cycle(
                    uid=uid, symbol=symbol, state=state, status=status,
                    remaining_side=remaining_side, remaining=remaining,
                    positions=positions, open_orders=open_orders,
                    threshold=threshold, execute=execute, results=force_results,
                )
                if new_state is not None:
                    states[symbol] = new_state
                    active[symbol] = "LONG"
                    created.append(new_state)
                    continue
            if state.get("rehedgeEnabled") is True and allow_new_triggers:
                if position_open_pnl(remaining) <= -threshold:
                    synthetic = evaluate_auto_hedge(
                        positions, threshold, open_orders=open_orders,
                        protected_sides={symbol: remaining_side},
                        skip_symbols=set(),
                    )
                    action = next((a for a in synthetic if a.symbol == symbol), None)
                    if action:
                        new_state = _new_cycle_state(action, state, threshold)
                        if execute:
                            _pair_doc(uid, symbol).set(new_state, merge=True)
                        states[symbol] = new_state
                        active[symbol] = remaining_side
                        created.append(new_state)
                        continue
                if execute and status != "REHEDGE_ARMED":
                    _pair_doc(uid, symbol).set({
                        "status": "REHEDGE_ARMED",
                        "updatedAt": datetime.now(timezone.utc),
                    }, merge=True)
                skip.add(symbol)
                continue
            skip.add(symbol)
            continue
        if status == "CLOSED":
            # A later brand-new normal position is allowed to create a new generation.
            continue

    if settings.get("enabled") is True and allow_new_triggers:
        candidates = evaluate_auto_hedge(
            positions, threshold, open_orders=open_orders,
            protected_sides=None, skip_symbols=skip | set(active),
        )
        for action in candidates:
            if action.symbol in active:
                continue
            prior = states.get(action.symbol)
            new_state = _new_cycle_state(action, prior, threshold)
            if execute:
                _pair_doc(uid, action.symbol).set(new_state, merge=True)
            states[action.symbol] = new_state
            active[action.symbol] = action.protected_side
            created.append(new_state)
    else:
        # Global OFF stops new triggers but never abandons an existing lock.
        all_symbols = {symbol for symbol, _ in pmap}
        skip |= all_symbols - set(active)

    return active, skip, states, created


def _sync_pair_views(
    *,
    uid: str,
    states: dict[str, dict[str, Any]],
    protected_sides: dict[str, str],
    report: dict[str, Any],
    client: Any,
) -> None:
    positions = list(client.position_risk() or [])
    pmap = _position_map(positions)
    report_rows = {
        str(row.get("symbol", "")).upper(): row
        for row in report.get("actions", [])
        if isinstance(row, dict)
    }
    final_rows = {
        str(row.get("symbol", "")).upper(): row
        for row in report.get("final", [])
        if isinstance(row, dict)
    }
    now = datetime.now(timezone.utc)

    for symbol, protected_side in protected_sides.items():
        state = dict(states.get(symbol) or {})
        hedge_side = str(state.get("hedgeSide") or _opposite(protected_side)).upper()
        protected_row = pmap.get((symbol, protected_side))
        hedge_row = pmap.get((symbol, hedge_side))
        if not protected_row:
            _transition_missing_protected(uid, {**state, "symbol": symbol}, pmap)
            continue

        action = report_rows.get(symbol) or {}
        final = final_rows.get(symbol) or {}
        current_protected = position_quantity(protected_row)
        current_hedge = position_quantity(hedge_row)
        reserved = max(0.0, float(state.get("reservedHedgeQty") or 0))
        filled = max(0.0, float(action.get("filledQty") or 0))
        operation = str(action.get("operation", "")).upper()
        if action.get("exchangeOrderId") is not None:
            if operation == "OPEN":
                reserved += filled
            elif operation == "REDUCE":
                reserved = max(0.0, reserved - min(reserved, filled))
        reserved = min(reserved, current_hedge)
        free_qty = max(0.0, current_hedge - reserved)

        action_status = str(action.get("status") or "").upper()
        final_status = str(final.get("status") or "").upper()
        if action_status == "PRECISION_BLOCKED":
            status = "PRECISION_BLOCKED"
        elif action_status in {"FAILED", "INSUFFICIENT_MARGIN"}:
            status = "BLOCKED"
        elif final_status == "HEDGED":
            status = "HEDGED"
        elif final_status == "PENDING":
            status = "HEDGING"
        elif final_status in {"NEEDS_HEDGE", "NEEDS_REDUCE"}:
            status = "ADJUSTING"
        elif action_status in {"HEDGED", "PARTIAL"}:
            status = "HEDGING" if action_status == "PARTIAL" else "HEDGED"
        else:
            status = "ADJUSTING"

        order_ids = [str(x) for x in state.get("exchangeOrderIds", []) if str(x)]
        client_ids = [str(x) for x in state.get("clientOrderIds", []) if str(x)]
        if action.get("exchangeOrderId") is not None:
            order_ids.append(str(action["exchangeOrderId"]))
        if action.get("clientOrderId"):
            client_ids.append(str(action["clientOrderId"]))
        revision = max(0, int(float(state.get("intentRevision") or 0)))
        if action.get("exchangeOrderId") is not None:
            revision += 1

        update = {
            "symbol": symbol,
            "status": status,
            "protectedSide": protected_side,
            "hedgeSide": hedge_side,
            "currentProtectedQty": current_protected,
            "currentHedgeQty": current_hedge,
            "reservedHedgeQty": reserved,
            "autoHedgeAddedQty": max(0.0, float(state.get("autoHedgeAddedQty") or 0) + (filled if operation == "OPEN" else 0.0)),
            "normalFreeQty": free_qty,
            "protectedLeg": _leg_view(protected_row),
            "hedgeLeg": _leg_view(hedge_row),
            "hedgeRatio": (current_hedge / current_protected * 100.0) if current_protected > 0 else None,
            "intentRevision": revision,
            "exchangeOrderIds": order_ids[-100:],
            "clientOrderIds": client_ids[-100:],
            "lastAction": action or final,
            "lastReason": str(final.get("reason") or action.get("reason") or ""),
            "lastReconciledAt": now,
            "updatedAt": now,
        }
        _pair_doc(uid, symbol).set(update, merge=True)
        _audit(uid, {
            "symbol": symbol,
            "pairCycleId": str(state.get("generationId", "")),
            "protectedSide": protected_side,
            "hedgeSide": hedge_side,
            "triggerPnl": state.get("triggerPnl"),
            "threshold": state.get("triggerThresholdUsd"),
            "protectedQtyAfter": current_protected,
            "hedgeQtyAfter": current_hedge,
            "normalOppositeQty": free_qty,
            "reservedQty": reserved,
            "requestedDelta": action.get("requiredDelta"),
            "operation": action.get("operation"),
            "exchangeOrderId": action.get("exchangeOrderId"),
            "clientOrderId": action.get("clientOrderId"),
            "fillQty": action.get("filledQty"),
            "resultingStatus": status,
            "reason": update["lastReason"],
        })




PAIR_EXIT_REQUEST_MAX_AGE_SECONDS = 120
PAIR_EXIT_MAX_SECONDS = 180


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return None


def _short_recovery_pair_exit(
    *, uid: str, symbol: str, state: dict[str, Any], prior: dict[str, Any] | None,
    long_row: dict[str, Any], short_row: dict[str, Any], mark: Any, client: Any,
    now: datetime, generation: str,
) -> tuple[dict[str, Any] | None, Any, str] | None:
    """Joint LONG+SHORT exit at LONG TP (net positive only). Returns None when not involved.

    Only the SHORT is touched here (target 0 through the existing engine); the LONG is closed by
    the Multi-BB TP path once it sees PAIR_EXIT with a flat SHORT.
    """
    if not prior:
        return None
    long_qty = position_quantity(long_row)
    short_qty = position_quantity(short_row)
    if prior.get("phase") == "PAIR_EXIT":
        if long_qty <= 0:
            return None  # decide() clears the record (NO_LONG)
        started = _as_utc(prior.get("exitStartedAt")) or now
        if short_qty <= 0 and (now - started).total_seconds() > PAIR_EXIT_MAX_SECONDS:
            # LONG was not closed in time (TP no longer due): re-hedge 1:1 instead of leaving it open.
            record = {**prior, "phase": "REFILL", "lastEvent": "JOINT_EXIT_EXPIRED_REHEDGE", "evaluatedAt": now,
                      "lastTarget": str(long_qty)}
            return record, None, "JOINT_EXIT_EXPIRED_REHEDGE"
        record = {**prior, "lastTarget": "0", "evaluatedAt": now,
                  "lastEvent": "JOINT_EXIT_SHORT_FLAT_WAIT_LONG_TP" if short_qty <= 0 else "JOINT_EXIT_CLOSING_SHORT"}
        return record, 0, record["lastEvent"]
    requested = _as_utc(state.get("pairExitRequestedAt"))
    if requested is None or (now - requested).total_seconds() > PAIR_EXIT_REQUEST_MAX_AGE_SECONDS:
        return None
    if long_qty <= 0 or short_qty <= 0:
        return None
    since = _as_utc(prior.get("hedgeSince")) or _as_utc(state.get("triggerAt"))
    funding = (short_recovery_pair_exit.paid_funding(client, symbol=symbol, start_ms=int(since.timestamp() * 1000))
               if since else None)
    price = float(mark or 0)
    verdict = short_recovery_pair_exit.net_exit(
        long_pnl=position_open_pnl(long_row), short_pnl=position_open_pnl(short_row),
        long_notional=long_qty * price, short_notional=short_qty * price, funding_paid=funding,
    )
    if not verdict["allowed"]:
        # Evaluate a request once: Multi-BB asks again on its next tick (avoids an income read every 3 s).
        _pair_doc(uid, symbol).set({"pairExitRequestedAt": None}, merge=True)
        _audit(uid, {"eventType": "SHORT_RECOVERY_JOINT_EXIT_WAIT", "symbol": symbol,
                     "reason": verdict["reason"], "net": None if verdict["net"] is None else str(verdict["net"])})
        return None  # normal ladder continues; the LONG keeps waiting
    record = {**prior, "phase": "PAIR_EXIT", "exitStartedAt": now, "lastTarget": "0", "evaluatedAt": now,
              "lastEvent": "JOINT_EXIT_NET_POSITIVE_CLOSING_SHORT", "exitNet": str(verdict["net"]),
              "generationId": generation}
    _audit(uid, {"eventType": "SHORT_RECOVERY_JOINT_EXIT_START", "symbol": symbol, "net": str(verdict["net"]),
                 "fees": str(verdict["fees"]), "fundingPaid": str(verdict["fundingPaid"])})
    return record, 0, "JOINT_EXIT_NET_POSITIVE_CLOSING_SHORT"


def _short_recovery_exit_reader(uid: str, symbol: str) -> dict[str, Any]:
    return _pair_doc(uid, symbol).get().to_dict() or {}


def _short_recovery_exit_requester(uid: str, symbol: str) -> None:
    _pair_doc(uid, symbol).set({"pairExitRequestedAt": datetime.now(timezone.utc)}, merge=True)


short_recovery_pair_exit.configure(_short_recovery_exit_reader, _short_recovery_exit_requester)


_RECORD_VOLATILE_KEYS = {"evaluatedAt"}


def _short_recovery_record_changed(prior: dict[str, Any] | None, record: dict[str, Any] | None) -> bool:
    if (prior is None) != (record is None):
        return True
    if prior is None:
        return False
    strip = lambda row: {k: v for k, v in row.items() if k not in _RECORD_VOLATILE_KEYS}
    return strip(prior) != strip(record)


def _hedged_before_switch_on(state: dict[str, Any], plan_settings: dict[str, Any]) -> bool:
    """True when this Auto Hedge cycle started before the user switched SHORT afbouwen ON (or the time is unknown)."""
    enabled_at = _as_utc(plan_settings.get("enabledAt"))
    trigger_at = _as_utc(state.get("triggerAt"))
    if enabled_at is None or trigger_at is None:
        return True   # unknown -> safe side: anchor at the current price, never a catch-up burst
    return trigger_at <= enabled_at


def _short_recovery_targets(
    *,
    uid: str,
    settings: dict[str, Any],
    states: dict[str, dict[str, Any]],
    protected_sides: dict[str, str],
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    client: Any,
    execute: bool,
) -> tuple[dict[str, float], list[dict[str, Any]], set[str]]:
    """SHORT Recovery 2.0: per-symbol SHORT targets for the existing engine (+ symbols to hold this tick).

    Live targets are returned only when ASTER_SHORT_RECOVERY_EXECUTION_ENABLED=true AND this is a live run.
    Otherwise the decisions are recorded under ``shortRecoveryShadow`` and the engine keeps legacy 1:1.
    A symbol whose inputs cannot be read keeps its last confirmed target (never a blind top-up or cut).
    """
    plan_settings = settings.get("shortRecoveryPlan") if isinstance(settings.get("shortRecoveryPlan"), dict) else {}
    live = bool(SHORT_RECOVERY_EXECUTION_ENABLED and execute)
    field = "shortRecovery" if live else "shortRecoveryShadow"
    symbols = [s for s, side in protected_sides.items() if side == "LONG"]
    if not symbols or plan_settings.get("enabled") is not True:
        # Feature off: clear any live record so the engine restores the legacy 1:1 hedge.
        if execute:
            for symbol in symbols:
                if (states.get(symbol) or {}).get(field):
                    _pair_doc(uid, symbol).set({field: None}, merge=True)
        return {}, [], set()
    pmap = _position_map(positions)
    try:
        info = client.public_exchange_info() or {}
        rules = {
            str(row.get("symbol", "")).upper(): ContractRules.from_exchange_info(row)
            for row in (info.get("symbols", []) if isinstance(info, dict) else [])
            if isinstance(row, dict)
        }
    except Exception:
        rules = {}
    try:
        available = (client.account_information() or {}).get("availableBalance")
    except Exception:
        available = None
    pending = {
        str(o.get("symbol", "")).upper()
        for o in open_orders or []
        if isinstance(o, dict) and str(o.get("positionSide", "")).upper() == "SHORT"
        and str(o.get("status", "NEW")).upper() not in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
    }
    overrides: dict[str, float] = {}
    hold: set[str] = set()
    rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for symbol in symbols:
        state = states.get(symbol) or {}
        if str(state.get("status", "")).upper() not in ACTIVE_STATUSES:
            continue
        prior = state.get(field) if isinstance(state.get(field), dict) else None
        generation = str(state.get("generationId") or "")
        if prior and str(prior.get("generationId") or "") != generation:
            prior = None  # a new Auto Hedge generation never inherits an old ladder
        if prior and prior.get("startReason") == "ANCHOR_AT_SWITCH_ON":
            prior = None  # Amar 21:36: anchor = hedge moment (SHORT entry); restart cycles anchored at switch-on
        long_row = pmap.get((symbol, "LONG")) or {}
        short_row = pmap.get((symbol, "SHORT")) or {}
        rule = rules.get(symbol)
        if rule is None:
            last = prior.get("lastTarget") if prior else None
            if live and last is not None:
                overrides[symbol] = float(last)
            rows.append({"symbol": symbol, "event": "RULES_UNAVAILABLE_HOLD", "mode": field})
            continue
        mark = long_row.get("markPrice") or short_row.get("markPrice") or 0
        if live:
            exit_result = _short_recovery_pair_exit(
                uid=uid, symbol=symbol, state=state, prior=prior, long_row=long_row,
                short_row=short_row, mark=mark, client=client, now=now, generation=generation,
            )
            if exit_result is not None:
                record, target, event = exit_result
                if target is not None:
                    overrides[symbol] = float(target)
                _pair_doc(uid, symbol).set({field: record, "pairExitRequestedAt": None}, merge=True)
                rows.append({"symbol": symbol, "mode": field, "event": event,
                             "targetShort": None if target is None else float(target),
                             "phase": (record or {}).get("phase")})
                continue
        short_qty: Any = position_quantity(short_row)
        short_entry: Any = short_row.get("entryPrice") or 0
        if not live and prior and prior.get("lastTarget") is not None:
            # Shadow simulates its own SHORT: the real SHORT stays legacy 1:1, so the simulated
            # quantity is the last target and a simulated (re)open fills at the current mark.
            virtual = float(prior["lastTarget"])
            if abs(virtual - float(short_qty)) > 1e-12 or prior.get("phase") in {"REFILL", "REOPEN_OPEN"}:
                short_qty, short_entry = virtual, mark
        result = short_recovery_decide(
            record=prior, settings=plan_settings,
            long_qty=position_quantity(long_row), short_qty=short_qty,
            short_entry=short_entry,
            mark=mark,
            has_pending_short_order=symbol in pending,
            start_at_mark=False,  # Amar 21:36: always anchor at the hedge moment (confirmed SHORT entry)
            qty_step=rule.market_quantity_step, min_qty=rule.market_min_quantity,
            min_notional=rule.min_notional, available_balance=available,
            leverage=long_row.get("leverage") or 1,
        )
        record = result["record"]
        if record is not None:
            record = {**record, "generationId": generation, "lastEvent": result["event"], "evaluatedAt": now,
                      "hedgeSince": (prior or {}).get("hedgeSince") or state.get("triggerAt") or now}
        if live and result["event"] == "PENDING_ORDER_HOLD":
            # An order on the SHORT is still open: send nothing for this symbol until it is final
            # (a held target next to a pending close could otherwise open extra SHORT).
            hold.add(symbol)
        elif live and result["override"] is not None:
            overrides[symbol] = float(result["override"])
        if execute and _short_recovery_record_changed(prior, record):
            # Write only on a real change (the worker ticks every few seconds; Firestore cost).
            _pair_doc(uid, symbol).set({field: record}, merge=True)
        rows.append({
            "symbol": symbol, "mode": field, "event": result["event"],
            "targetShort": None if result["override"] is None else float(result["override"]),
            "stepsReached": (record or {}).get("stepsReached"), "phase": (record or {}).get("phase"),
        })
    return overrides, rows, hold


def _run_uid(
    uid: str,
    *,
    force_shadow: bool = False,
    allow_new_triggers: bool | None = None,
    force_rehedge_symbols: set[str] | None = None,
    force_results: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not uid:
        return {"mode": "OFF", "ordersSent": 0, "status": "BLOCKED", "reason": "MISSING_UID", "actions": []}

    entitled = main._release_feature_enabled_for_uid(uid, "auto_hedge_v2")
    pairs_before = _pair_states(uid)
    has_existing_lock = any(
        str(row.get("status", "")).upper() in ACTIVE_STATUSES
        for row in pairs_before.values()
    )
    if not entitled and not has_existing_lock:
        return {
            "mode": "OFF", "ordersSent": 0, "status": "BLOCKED",
            "reason": "FEATURE_NOT_RELEASED", "actions": [],
        }

    if allow_new_triggers is None:
        allow_new_triggers = entitled
    else:
        allow_new_triggers = bool(allow_new_triggers and entitled)

    settings = _current(uid)
    execute = EXECUTION_ENABLED and not force_shadow
    coordination_token: str | None = None
    try:
        if execute:
            # Take the account lease BEFORE reading positions/pair state: the individual manual
            # Close holds the same lease across its pair freeze + order, so a worker run can no
            # longer act on a pre-close snapshot right after the manual close released the lease.
            coordination_token = main._acquire_aster_account_coordination(
                uid, "AUTO_HEDGE", "POSITION_LOSS_EXACT_1_TO_1",
            )
            if not coordination_token:
                report = {
                    "mode": "LIVE", "ordersSent": 0, "status": "PENDING",
                    "reason": "ACCOUNT_COORDINATION_BUSY", "actions": [],
                }
                _doc(uid).set({
                    "lastReport": report,
                    "lastCheckedAt": datetime.now(timezone.utc),
                }, merge=True)
                return report
        client = _client(uid, live=execute)
        if execute and not _hedge_mode_ok(uid, client):
            # Never send positionSide orders to a One-way account; existing state stays untouched.
            report = {
                "mode": "LIVE", "ordersSent": 0, "status": "BLOCKED",
                "reason": "HEDGE_MODE_REQUIRED", "actions": [],
            }
            _doc(uid).set({
                "lastReport": report,
                "lastCheckedAt": datetime.now(timezone.utc),
                "lastError": HEDGE_MODE_REQUIRED_MESSAGE,
            }, merge=True)
            return report
        positions = list(client.position_risk() or [])
        open_orders = list(client.open_orders() or [])
        protected_sides, skip_symbols, states, created = _prepare_lifecycle(
            uid=uid,
            settings=settings,
            positions=positions,
            open_orders=open_orders,
            execute=execute,
            allow_new_triggers=bool(allow_new_triggers),
            force_rehedge_symbols=force_rehedge_symbols,
            force_results=force_results,
        )

        if not settings.get("enabled") and not protected_sides:
            report = {"mode": "OFF", "ordersSent": 0, "actions": []}
            _doc(uid).set({
                "lastReport": report,
                "lastCheckedAt": datetime.now(timezone.utc),
                "lastError": "",
            }, merge=True)
            return report

        if _dynamic_hedge_enabled(uid):
            report = {
                "mode": "OFF", "ordersSent": 0, "status": "BLOCKED",
                "reason": "DYNAMIC_HEDGE_CONFLICT", "actions": [],
            }
            _doc(uid).set({
                "lastReport": report,
                "lastCheckedAt": datetime.now(timezone.utc),
                "lastError": "",
            }, merge=True)
            return report

        contexts = {}
        for symbol, side in protected_sides.items():
            state = states.get(symbol) or {}
            contexts[symbol] = {
                "generationId": str(state.get("generationId") or "g0"),
                "revision": int(float(state.get("intentRevision") or 0)),
            }

        recovery_targets, recovery_rows, recovery_hold = _short_recovery_targets(
            uid=uid, settings=settings, states=states, protected_sides=protected_sides,
            positions=positions, open_orders=open_orders, client=client, execute=execute,
        )
        report = reconcile_auto_hedge(
            client=client,
            uid=uid,
            threshold_usd=settings["thresholdUsd"],
            execute=execute,
            audit=(lambda payload: _audit(uid, payload)),
            protected_sides=protected_sides or None,
            skip_symbols=skip_symbols | recovery_hold,
            intent_context=contexts,
            target_overrides=recovery_targets or None,
            positions=positions,
            open_orders=open_orders,
        )
        if recovery_rows:
            report["shortRecovery"] = recovery_rows
        report["createdCycles"] = [
            {"symbol": row.get("symbol"), "generationId": row.get("generationId")}
            for row in created
        ]
        if execute and protected_sides:
            _sync_pair_views(
                uid=uid, states=states, protected_sides=protected_sides,
                report=report, client=client,
            )
        _doc(uid).set({
            "lastReport": report,
            "lastCheckedAt": datetime.now(timezone.utc),
            "lastError": "",
            "updatedAt": datetime.now(timezone.utc),
        }, merge=True)
        return report
    except Exception as exc:
        report = {
            "mode": "LIVE" if execute else "SHADOW",
            "ordersSent": 0,
            "status": "FAILED",
            "reason": str(exc)[:500],
            "actions": [],
        }
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
    uid = main.require_release_feature(user, "auto_hedge_v2")
    return _public(uid)


@main.app.put("/v1/me/aster/position-loss-auto-hedge")
def put_position_loss_auto_hedge(
    request: AutoHedgeSettingsRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    uid = main.require_release_feature(user, "auto_hedge_v2")
    current = _current(uid)
    previous_enabled = current.get("enabled") is True
    if previous_enabled and request.enabled is False and request.confirmDisable is not True:
        _audit_global_setting_change(
            uid,
            previous_enabled=previous_enabled,
            requested_enabled=False,
            request=request,
            source_route="PUT /v1/me/aster/position-loss-auto-hedge",
            result="BLOCKED_CONFIRMATION_REQUIRED",
        )
        raise HTTPException(409, "Auto Hedge uitschakelen vereist expliciete bevestiging")
    if request.enabled and _dynamic_hedge_enabled(uid):
        raise HTTPException(409, "Auto Hedge kan niet tegelijk met Dynamic Hedge actief zijn")
    try:
        threshold = normalize_threshold(request.thresholdUsd)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if request.enabled and not previous_enabled:
        _require_hedge_mode(uid)
    now = datetime.now(timezone.utc)
    _doc(uid).set({
        "enabled": bool(request.enabled),
        "thresholdUsd": threshold,
        "updatedAt": now,
    }, merge=True)
    if previous_enabled != bool(request.enabled):
        _audit_global_setting_change(
            uid,
            previous_enabled=previous_enabled,
            requested_enabled=bool(request.enabled),
            request=request,
            source_route="PUT /v1/me/aster/position-loss-auto-hedge",
            result="APPLIED",
        )
    # Turning the global toggle off stops NEW triggers, not an existing hedge lock.
    _run_uid(uid, force_shadow=not EXECUTION_ENABLED)
    response.headers["Cache-Control"] = "no-store"
    return _public(uid)


@main.app.post("/v1/me/aster/position-loss-auto-hedge/apply")
def apply_position_loss_auto_hedge(
    request: AutoHedgeSettingsRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    uid = main.require_release_feature(user, "auto_hedge_v2")
    current = _current(uid)
    previous_enabled = current.get("enabled") is True
    if previous_enabled and request.enabled is False and request.confirmDisable is not True:
        _audit_global_setting_change(
            uid,
            previous_enabled=previous_enabled,
            requested_enabled=False,
            request=request,
            source_route="POST /v1/me/aster/position-loss-auto-hedge/apply",
            result="BLOCKED_CONFIRMATION_REQUIRED",
        )
        raise HTTPException(409, "Auto Hedge uitschakelen vereist expliciete bevestiging")
    if request.enabled and _dynamic_hedge_enabled(uid):
        raise HTTPException(409, "Auto Hedge kan niet tegelijk met Dynamic Hedge actief zijn")
    try:
        threshold = normalize_threshold(request.thresholdUsd)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if request.enabled and not previous_enabled:
        _require_hedge_mode(uid)
    _doc(uid).set({
        "enabled": bool(request.enabled),
        "thresholdUsd": threshold,
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    if previous_enabled != bool(request.enabled):
        _audit_global_setting_change(
            uid,
            previous_enabled=previous_enabled,
            requested_enabled=bool(request.enabled),
            request=request,
            source_route="POST /v1/me/aster/position-loss-auto-hedge/apply",
            result="APPLIED",
        )
    report = _run_uid(uid, force_shadow=not EXECUTION_ENABLED)
    response.headers["Cache-Control"] = "no-store"
    return {**_public(uid), "lastReport": _serialize(report)}


@main.app.put("/v1/me/aster/position-loss-auto-hedge/pairs/{symbol}/rehedge")
def put_position_loss_auto_hedge_rehedge(
    symbol: str,
    request: RehedgeRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    uid = main.require_release_feature(user, "auto_hedge_v2")
    normalized = str(symbol).upper().strip()
    if not SYMBOL_RE.fullmatch(normalized):
        raise HTTPException(422, "Ongeldig Aster USDT-symbool")
    ref = _pair_doc(uid, normalized)
    current = ref.get().to_dict() or {}
    status = str(current.get("status", "")).upper()
    if status not in REHEDGEABLE_STATUSES:
        raise HTTPException(409, "Opnieuw hedgen is alleen beschikbaar nadat de handmatige sluiting volledig is bevestigd")
    if request.enabled and _current(uid).get("enabled") is not True:
        raise HTTPException(409, "Zet Auto Hedge eerst AAN voordat je deze recovery opnieuw bewapent")
    if request.enabled and _dynamic_hedge_enabled(uid):
        raise HTTPException(409, "Auto Hedge kan niet tegelijk met Dynamic Hedge actief zijn")
    if request.enabled:
        _require_hedge_mode(uid)
    now = datetime.now(timezone.utc)
    next_status = (
        "REHEDGE_ARMED" if request.enabled
        else ("DISABLED" if current.get("rehedgeEnabled") is True or status == "REHEDGE_ARMED" else "RECOVERY")
    )
    ref.set({
        "rehedgeEnabled": bool(request.enabled),
        "status": next_status,
        "updatedAt": now,
    }, merge=True)
    _audit(uid, {
        "symbol": normalized,
        "pairCycleId": str(current.get("generationId", "")),
        "resultingStatus": next_status,
        "reason": "USER_REHEDGE_ENABLED" if request.enabled else "USER_REHEDGE_DISABLED",
    })
    report = _run_uid(uid, force_shadow=not EXECUTION_ENABLED)
    response.headers["Cache-Control"] = "no-store"
    return {**_public(uid), "lastReport": _serialize(report)}


class ShortRecoverySettingsRequest(BaseModel):
    enabled: bool
    steps: int = Field(ge=1, le=100)
    totalPct: str = Field(min_length=1, max_length=16)
    clientBuild: str = Field(default="", max_length=32)


@main.app.put("/v1/me/aster/position-loss-auto-hedge/short-recovery")
def put_position_loss_auto_hedge_short_recovery(
    request: ShortRecoverySettingsRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    """Save SHORT Recovery 2.0 settings. Never places an order itself; the worker applies them."""
    uid = main.require_release_feature(user, "auto_hedge_v2")
    try:
        plan = normalize_short_recovery_settings(
            {"enabled": request.enabled, "steps": request.steps, "totalPct": request.totalPct})
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if plan["enabled"] and _current(uid).get("enabled") is not True:
        raise HTTPException(409, "Zet Auto Hedge eerst AAN; SHORT Recovery bouwt alleen Auto Hedge-SHORTs af")
    now = datetime.now(timezone.utc)
    previous = _public_short_recovery(_current(uid))
    switched_on = plan["enabled"] and not previous.get("enabled")
    if switched_on:
        _require_hedge_mode(uid)
    enabled_at = now if switched_on else ((_current(uid).get("shortRecoveryPlan") or {}).get("enabledAt") if plan["enabled"] else None)
    _doc(uid).set({"shortRecoveryPlan": {**plan, "updatedAt": now, "enabledAt": enabled_at}, "updatedAt": now}, merge=True)
    _audit(uid, {"eventType": "SHORT_RECOVERY_SETTINGS_CHANGED", "previous": previous, "next": plan,
                 "clientBuild": request.clientBuild})
    response.headers["Cache-Control"] = "no-store"
    return _public(uid)


class RehedgeAllRequest(BaseModel):
    confirm: bool = False
    clientBuild: str = Field(default="", max_length=32)


REHEDGE_ALL_BUSY = "Account is bezig met een andere actie. Er is niets gewijzigd; probeer het over enkele seconden opnieuw."


def _rehedge_all_item(symbol: str, forced: dict[str, Any] | None, report: dict[str, Any]) -> dict[str, Any]:
    """One summary row. Success is only claimed from the exchange-confirmed reconcile result."""
    forced = forced or {"symbol": symbol, "result": "SKIPPED", "reason": "NOT_IN_RECOVERY_ANYMORE"}
    mark = float(forced.get("markPrice") or 0)
    item = {
        "symbol": symbol,
        "markPrice": mark,
        "longQty": float(forced.get("longQty") or 0),
        "shortQtyBefore": float(forced.get("shortQtyBefore") or 0),
        "addedShortQty": 0.0,
        "shortQtyAfter": float(forced.get("shortQtyBefore") or 0),
        "reason": str(forced.get("reason") or ""),
    }
    if forced.get("result") != "STARTED":
        item["outcome"] = "SKIPPED"
    else:
        action = next((row for row in report.get("actions", []) if isinstance(row, dict)
                       and str(row.get("symbol", "")).upper() == symbol), {})
        final = next((row for row in report.get("final", []) if isinstance(row, dict)
                      and str(row.get("symbol", "")).upper() == symbol), {})
        status = str(action.get("status") or "").upper()
        filled = float(action.get("filledQty") or 0) if action.get("exchangeOrderId") is not None else 0.0
        item["addedShortQty"] = filled
        if final:
            item["longQty"] = float(final.get("protectedQty") or item["longQty"])
            item["shortQtyAfter"] = float(final.get("hedgeQty") or 0)
        else:
            item["shortQtyAfter"] = item["shortQtyBefore"] + filled
        final_status = str(final.get("status") or "").upper()
        if str(report.get("mode", "")).upper() != "LIVE":
            item["outcome"], item["reason"] = "TEST_ONLY", "SHADOW_MODE_NO_ORDERS"
        elif status == "PRECISION_BLOCKED":
            item["outcome"], item["reason"] = "TOO_SMALL", "BELOW_ASTER_MINIMUM_OR_STEP"
        elif status == "INSUFFICIENT_MARGIN":
            item["outcome"], item["reason"] = "NO_MARGIN", str(action.get("reason") or "INSUFFICIENT_MARGIN")
        elif status == "FAILED":
            # An order id was derived: the exchange may have it. The worker re-queries that same id; never resent blindly.
            item["outcome"] = "UNKNOWN" if action.get("clientOrderId") else "FAILED"
            item["reason"] = str(action.get("reason") or "FAILED")[:300]
        elif final_status == "HEDGED":
            item["outcome"] = "PROTECTED"
        elif final_status == "PENDING":
            item["outcome"], item["reason"] = "PENDING", "OPEN_ORDER_RECONCILING"
        elif final_status == "NEEDS_REDUCE":
            # The LONG shrank while the order ran; the existing 1:1 rule trims the SHORT on the next tick.
            item["outcome"], item["reason"] = "PENDING", "LONG_SHRANK_AUTO_HEDGE_TRIMS"
        elif filled > 0:
            item["outcome"] = "PARTIAL"
        else:
            item["outcome"], item["reason"] = "QUEUED", "WORKER_CONTINUES"
    long_qty = item["longQty"]
    item["longNotional"] = long_qty * mark
    item["shortNotionalBefore"] = item["shortQtyBefore"] * mark
    item["shortNotionalAfter"] = item["shortQtyAfter"] * mark
    item["hedgePercent"] = (item["shortQtyAfter"] / long_qty * 100.0) if long_qty > 0 else None
    return item


@main.app.post("/v1/me/aster/position-loss-auto-hedge/rehedge-all")
def post_position_loss_auto_hedge_rehedge_all(
    request: RehedgeAllRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    uid = main.require_release_feature(user, "auto_hedge_v2")
    if request.confirm is not True:
        raise HTTPException(422, "Bevestiging ontbreekt")
    if _current(uid).get("enabled") is not True:
        raise HTTPException(409, "Zet Auto Hedge eerst AAN voordat je Recovery-posities opnieuw hedget")
    if _dynamic_hedge_enabled(uid):
        raise HTTPException(409, "Auto Hedge kan niet tegelijk met Dynamic Hedge actief zijn")
    _require_hedge_mode(uid)
    candidates = sorted(
        symbol for symbol, row in _pair_states(uid).items()
        if str(row.get("status", "")).upper() in RECOVERY_STATUSES
    )
    response.headers["Cache-Control"] = "no-store"
    if not candidates:
        return {**_public(uid), "rehedgeAll": {"status": "NOTHING_TO_DO", "mode": "LIVE" if EXECUTION_ENABLED else "SHADOW",
                                              "found": 0, "ordersSent": 0, "items": []}}
    _audit(uid, {
        "eventType": "REHEDGE_ALL_REQUESTED",
        "symbols": candidates,
        "clientBuild": str(request.clientBuild or "")[:32],
        "reason": "USER_REHEDGE_ALL",
    })
    forced: dict[str, dict[str, Any]] = {}
    report = _run_uid(
        uid, force_shadow=not EXECUTION_ENABLED,
        force_rehedge_symbols=set(candidates), force_results=forced,
    )
    if report.get("reason") == "ACCOUNT_COORDINATION_BUSY":
        raise HTTPException(409, REHEDGE_ALL_BUSY)
    if str(report.get("status", "")).upper() == "FAILED" and not any(
        row.get("result") == "STARTED" for row in forced.values()
    ):
        raise HTTPException(503, "Posities konden niet betrouwbaar worden gelezen. Er is niets opnieuw gehedged.")
    items = [_rehedge_all_item(symbol, forced.get(symbol), report) for symbol in candidates]
    counts: dict[str, int] = {}
    for item in items:
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
    return {
        **_public(uid),
        "lastReport": _serialize(report),
        "rehedgeAll": {
            "status": "FAILED" if str(report.get("status", "")).upper() == "FAILED" else "DONE",
            "error": str(report.get("reason", ""))[:300] if str(report.get("status", "")).upper() == "FAILED" else "",
            "mode": str(report.get("mode", "")),
            "found": len(candidates),
            "ordersSent": int(report.get("ordersSent") or 0),
            "counts": counts,
            "items": items,
        },
    }


def _worker_loop() -> None:
    while not _worker_stop.wait(WORKER_INTERVAL):
        try:
            snapshots = list(main.db.collection("asterPositionLossAutoHedge").stream())
        except Exception:
            continue
        for snapshot in snapshots:
            if _worker_stop.is_set():
                return
            uid = str(snapshot.id or "").strip()
            if not uid:
                continue
            try:
                settings = _current(uid)
                pairs = _pair_states(uid)
                has_active_lock = any(
                    str(row.get("status", "")).upper() in ACTIVE_STATUSES
                    for row in pairs.values()
                )
                entitled = main._release_feature_enabled_for_uid(uid, "auto_hedge_v2")
                if not entitled and not has_active_lock:
                    continue
                if entitled and settings.get("enabled") is not True and not has_active_lock:
                    continue
                _run_uid(
                    uid,
                    force_shadow=not EXECUTION_ENABLED,
                    allow_new_triggers=entitled,
                )
            except Exception:
                continue


@main.app.on_event("startup")
def start_position_loss_auto_hedge_worker() -> None:
    global _worker_thread
    if not WORKER_ENABLED:
        return
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_stop.clear()
    _worker_thread = threading.Thread(
        target=_worker_loop, name="position-loss-auto-hedge-v2", daemon=True,
    )
    _worker_thread.start()


@main.app.on_event("shutdown")
def stop_position_loss_auto_hedge_worker() -> None:
    _worker_stop.set()
