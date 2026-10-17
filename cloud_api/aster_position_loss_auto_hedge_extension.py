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

WORKER_ENABLED = os.getenv("ASTER_POSITION_LOSS_AUTO_HEDGE_WORKER", "true").lower() == "true"
EXECUTION_ENABLED = os.getenv("ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED", "false").lower() == "true"
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
    shortRecoveryPlan: dict[str, Any] | None = None


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
    from short_recovery_gate import normalize_settings as _normalize_recovery_settings
    try:
        recovery_plan = _normalize_recovery_settings(row.get("shortRecoveryPlan"))
    except ValueError:
        recovery_plan = {"enabled": False, "status": "INVALID_SETTINGS"}
    return _serialize({
        "shortRecoveryPlan": recovery_plan,
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
        "referenceId": "file_00000000ecd08246bd1b15532fb478d6",
    })


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


def _prepare_lifecycle(
    *,
    uid: str,
    settings: dict[str, Any],
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    execute: bool,
    allow_new_triggers: bool = True,
) -> tuple[dict[str, str], set[str], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    threshold = float(settings["thresholdUsd"])
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
                skip.add(symbol)
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


def _run_uid(
    uid: str,
    *,
    force_shadow: bool = False,
    allow_new_triggers: bool | None = None,
    offline_pair_settlement: dict | None = None,
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
        client = _client(uid, live=execute)
        positions = list(client.position_risk() or [])
        open_orders = list(client.open_orders() or [])
        protected_sides, skip_symbols, states, created = _prepare_lifecycle(
            uid=uid,
            settings=settings,
            positions=positions,
            open_orders=open_orders,
            execute=execute,
            allow_new_triggers=bool(allow_new_triggers),
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

        if execute:
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

        contexts = {}
        for symbol, side in protected_sides.items():
            state = states.get(symbol) or {}
            contexts[symbol] = {
                "generationId": str(state.get("generationId") or "g0"),
                "revision": int(float(state.get("intentRevision") or 0)),
            }

        # Evaluate Recovery ownership BEFORE the existing reconciliation in offline
        # mode, so an intentional partial SHORT never appears as a legacy top-up.
        recovery_offline_partition = None
        if (not execute and os.getenv("ASTER_SHORT_RECOVERY_SHADOW_ENABLED", "false").lower() == "true"):
            from short_recovery_gate import partition_reconciliation
            recovery_offline_partition = partition_reconciliation(
                settings=settings.get("shortRecoveryPlan"), protected_sides=protected_sides,
                existing_skip_symbols=set(skip_symbols or ()), recovery_cycles=states)

        report = reconcile_auto_hedge(
            client=client,
            uid=uid,
            threshold_usd=settings["thresholdUsd"],
            execute=execute,
            audit=(lambda payload: _audit(uid, payload)),
            protected_sides=protected_sides or None,
            skip_symbols=skip_symbols,
            recovery_shadow_skip_symbols=(recovery_offline_partition["shadow_skip"] - recovery_offline_partition["legacy_skip"] if recovery_offline_partition else None),
            intent_context=contexts,
            positions=positions,
            open_orders=open_orders,
        )
        # Offline-only injection into the existing reconciliation lifecycle.
        # No production or live mode can invoke this: an explicit force_shadow
        # invocation and a caller-provided isolated mock transaction are required.
        if offline_pair_settlement is not None:
            if execute or not force_shadow or not recovery_offline_partition:
                report["shortRecoveryPairSettlement"] = "BLOCKED_OFFLINE_ONLY"
            elif not settings.get("shortRecoveryPlan", {}).get("enabled"):
                report["shortRecoveryPairSettlement"] = "BLOCKED_RECOVERY_DISABLED"
            elif offline_pair_settlement.get("symbol") not in (recovery_offline_partition["shadow_skip"] - recovery_offline_partition["legacy_skip"]):
                report["shortRecoveryPairSettlement"] = "BLOCKED_RECOVERY_OWNERSHIP"
            else:
                from short_recovery_order_resolution_shadow import reconcile_pair_from_aster_mock
                ctx = dict(offline_pair_settlement)
                if ctx.get("account") != uid or not ctx.get("mock_only"):
                    report["shortRecoveryPairSettlement"] = "BLOCKED_MOCK_SCOPE"
                else:
                    ctx.pop("mock_only")
                    ctx["account"] = uid
                    # One offline lifecycle: decide the three Recovery actions
                    # before settling the pair; neither path can submit orders.
                    action_ctx = ctx.pop("recovery_action", None)
                    if action_ctx is not None:
                        from short_recovery_shadow_bridge import preview_reconciliation
                        from short_recovery_executor_adapter import preview_canonical_executor
                        from short_recovery_order_claim_shadow import pre_submit_check
                        try:
                            symbol = ctx["symbol"]
                            # Match the persistent claim's canonical identity, not a
                            # caller-chosen ID, before the existing pre-submit guard.
                            from short_recovery_order_claim_shadow import canonical_intent_id
                            identifiers = action_ctx.get("intent_ids")
                            scope_step = action_ctx.get("step")
                            if (not isinstance(identifiers, dict) or
                                    isinstance(scope_step, bool) or not isinstance(scope_step, int)):
                                raise ValueError("BLOCKED_CANONICAL_SCOPE")
                            for scope_key, scoped_id in identifiers.items():
                                if scope_key not in ("LONG_CLOSE", "SHORT_CLOSE", "SHORT_OPEN"):
                                    raise ValueError("BLOCKED_CANONICAL_SCOPE")
                                side, act = scope_key.split("_")
                                if scoped_id != canonical_intent_id(
                                        account=uid,symbol=symbol,cycle=ctx["cycle"],
                                        side=side,action=act,step=scope_step):
                                    raise ValueError("BLOCKED_CANONICAL_SCOPE")
                            if action_ctx["intent_id"] not in identifiers.values():
                                raise ValueError("BLOCKED_CANONICAL_SCOPE")
                            state = action_ctx["state"]
                            bridge = preview_reconciliation(
                                protected_sides={symbol:"LONG"}, existing_skip_symbols=set(),
                                recovery_states={symbol:state},
                                exchange_short_quantities={symbol:action_ctx["short_qty"]},
                                long_quantities={symbol:action_ctx["long_qty"]},
                                net_exits={symbol} if action_ctx.get("net_exit_due") else set())
                            preflight = pre_submit_check(
                                db=ctx["db"], transactional=ctx["transactional"],
                                claim_ref=action_ctx["claim_ref"], control_ref=ctx["control_ref"],
                                account=uid, symbol=symbol, cycle=ctx["cycle"],
                                intent_id=action_ctx["intent_id"],
                                account_close_guard=action_ctx["account_close_guard"])
                            report["shortRecoveryAction"] = (
                                preview_canonical_executor(
                                    reconciled=bridge, symbol=symbol, intent_ids=action_ctx.get("intent_ids"),
                                    long_qty=action_ctx["long_qty"], short_qty=action_ctx["short_qty"],
                                    net_evidence_verified=action_ctx.get("net_evidence_verified") is True,
                                    ownership_verified=True,
                                    claim_reserved=preflight=="PREFLIGHT_SHADOW_ONLY",
                                    stop_clear=preflight=="PREFLIGHT_SHADOW_ONLY")
                                if preflight=="PREFLIGHT_SHADOW_ONLY" else
                                {"status":preflight,"ordersSent":0,"intents":()})
                            proposed = report["shortRecoveryAction"]
                            if proposed.get("status")=="PREVIEW_PAIR_CLOSE_REQUIRES_ATOMIC_CLAIMS":
                                # A SHORT claim cannot authorize closing the LONG side.
                                # Require independent LONG preflight before showing either intent.
                                long_ref=action_ctx.get("long_claim_ref")
                                long_id=(action_ctx.get("intent_ids") or {}).get("LONG_CLOSE")
                                if long_ref is None or not long_id:
                                    proposed={"status":"BLOCKED_PAIR_SIDE_CLAIMS","ordersSent":0,"intents":()}
                                else:
                                    long_check=pre_submit_check(
                                        db=ctx["db"],transactional=ctx["transactional"],
                                        claim_ref=long_ref,control_ref=ctx["control_ref"],
                                        account=uid,symbol=symbol,cycle=ctx["cycle"],
                                        intent_id=long_id,account_close_guard=action_ctx["account_close_guard"])
                                    if long_check!="PREFLIGHT_SHADOW_ONLY":
                                        proposed={"status":"BLOCKED_PAIR_SIDE_CLAIMS","ordersSent":0,"intents":()}
                                report["shortRecoveryAction"]=proposed
                            if proposed.get("intents") and any(
                                    intent.intent_id not in identifiers.values()
                                    for intent in proposed["intents"]):
                                report["shortRecoveryAction"] = {
                                    "status":"BLOCKED_INTENT_CLAIM_ID_MISMATCH",
                                    "ordersSent":0,"intents":()}
                            elif proposed.get("intents") and action_ctx.get("submit_mock") is not None:
                                # The transport must be an explicitly provided offline mock;
                                # never use the live _client or an authenticated Aster client.
                                mock_submit = action_ctx["submit_mock"]
                                if not action_ctx.get("offline_mock_confirmed") or not callable(mock_submit):
                                    report["shortRecoverySubmit"] = ("BLOCKED_MOCK_TRANSPORT",)
                                elif len(proposed["intents"]) != 1:
                                    # Reserve both sideclaims atomically, but still
                                    # do not send either leg: exchange POSTs aren't atomic.
                                    from short_recovery_order_claim_shadow import lock_pair_submit_offline
                                    intents={i.position_side.value:i for i in proposed["intents"]}
                                    report["shortRecoverySubmit"] = (lock_pair_submit_offline(
                                        db=ctx["db"],transactional=ctx["transactional"],
                                        long_claim_ref=action_ctx.get("long_claim_ref"),
                                        short_claim_ref=action_ctx["claim_ref"],
                                        control_ref=ctx["control_ref"],account=uid,
                                        symbol=symbol,cycle=ctx["cycle"],
                                        long_intent=intents.get("LONG"),short_intent=intents.get("SHORT"),
                                        account_close_guard=action_ctx["account_close_guard"]),)
                                else:
                                    from short_recovery_order_claim_shadow import submit_once_offline
                                    claim_refs = {"SHORT":action_ctx["claim_ref"],
                                                  "LONG":action_ctx.get("long_claim_ref")}
                                    results=[]
                                    for intent in proposed["intents"]:
                                        ref=claim_refs.get(intent.position_side.value)
                                        if ref is None:
                                            results.append("BLOCKED_SIDE_CLAIM")
                                            break
                                        results.append(submit_once_offline(
                                            db=ctx["db"],transactional=ctx["transactional"],
                                            claim_ref=ref,control_ref=ctx["control_ref"],
                                            account=uid,symbol=symbol,cycle=ctx["cycle"],intent=intent,
                                            account_close_guard=action_ctx["account_close_guard"],
                                            submit_mock=mock_submit))
                                        if results[-1]!="SUBMITTED_RECONCILE_ONLY":break
                                    report["shortRecoverySubmit"] = tuple(results)
                        except (KeyError,TypeError,ValueError):
                            report["shortRecoveryAction"] = {"status":"BLOCKED_ACTION_CONTEXT","ordersSent":0,"intents":()}
                    report["shortRecoveryPairSettlement"] = reconcile_pair_from_aster_mock(**ctx)
        # SHORT Recovery Plan 2.0: strictly read-only shadow instrumentation.
        # NEVER change skip_symbols/protected_sides in the executable reconciler here.
        # No plan execution, order placement, or setting persistence is enabled.
        # An explicit future execution gate is required before intentional reductions
        # may become the authoritative desired hedge amount.
        if (not execute and
                os.getenv("ASTER_SHORT_RECOVERY_SHADOW_ENABLED", "false").lower() == "true"):
            from short_recovery_runtime_shadow import preview_existing_pairs
            report["shortRecoveryShadow"] = preview_existing_pairs(
                settings=settings, pair_states=states, positions=positions,
                open_orders=open_orders,
            )
            # Simulated ownership only: original skip_symbols were already used.
            shadow_plan = recovery_offline_partition
            report["shortRecoveryOwnershipShadow"] = {
                "status": shadow_plan["status"],
                "suppressedTopupSymbols": sorted(
                    shadow_plan["shadow_skip"] - shadow_plan["legacy_skip"]
                ),
                "ordersSent": 0,
            }
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
    from short_recovery_gate import normalize_settings as normalize_recovery
    payload = {"enabled": bool(request.enabled), "thresholdUsd": threshold,
               "updatedAt": datetime.now(timezone.utc)}
    if request.shortRecoveryPlan is not None:
        try:
            plan = normalize_recovery(request.shortRecoveryPlan)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        # This branch never enables trading for the new plan; preserve the user's
        # requested enable state for future rollout behind independent execution gate.
        payload["shortRecoveryPlan"] = {
            "enabled": plan["enabled"], "steps": plan["steps"], "stepPct": plan["stepPct"]
        }
    _doc(uid).set(payload, merge=True)
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
