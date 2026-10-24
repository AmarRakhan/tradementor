"""API, lifecycle persistence and server worker for Auto Hedge 2.0.

Build 431 keeps production order execution behind
ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED=false while adding the complete
pair lifecycle needed for exact 1:1 protection, HEDGE_LOCKED allocations,
RECOVERY and explicit per-pair re-arming.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import math
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
from short_recovery_ladder import direction_for as short_recovery_direction
from short_recovery_ladder import normalize_settings as normalize_short_recovery_settings
import short_recovery_pair_exit
from aster_position_loss_auto_hedge_lock import configure_auto_hedge_enabled_reader

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
# Build 654: defaults when the user never set "LONG-/SHORT-posities beschermen".
DEFAULT_PROTECT_LONG = True
DEFAULT_PROTECT_SHORT = True
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,36}USDT$")


class AutoHedgeSettingsRequest(BaseModel):
    enabled: bool
    # thresholdUsd = loss threshold for a LONG position (historic field name, kept for old clients);
    # thresholdShortUsd = loss threshold for a SHORT position (build 623). None = keep the stored value.
    thresholdUsd: float = Field(default=DEFAULT_THRESHOLD_USD, ge=0.01, le=100_000)
    thresholdShortUsd: float | None = Field(default=None, ge=0.01, le=100_000)
    # Build 647 (Amar 24-10): max hedge in % of the position (1-100, default 100 = 1:1). None = keep the stored value.
    maxHedgePct: float | None = Field(default=None, ge=1, le=200)          # LONG position (SHORT hedge)
    maxHedgeShortPct: float | None = Field(default=None, ge=1, le=200)     # SHORT position (LONG hedge)
    # Build 650: above 100% only with this switch ON ("Hedge mag groter dan positie"). None = keep the stored value.
    allowHedgeAbovePosition: bool | None = None
    # Build 654: which positions Auto Hedge protects with a NEW hedge. None = keep the stored value.
    protectLongPositions: bool | None = None
    protectShortPositions: bool | None = None
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
    try:
        threshold_short = normalize_threshold(row.get("thresholdShortUsd", DEFAULT_THRESHOLD_USD))
    except ValueError:
        threshold_short = DEFAULT_THRESHOLD_USD
    return {
        **row,
        "enabled": row.get("enabled") is True,
        "thresholdUsd": threshold,
        "thresholdShortUsd": threshold_short,
        "allowHedgeAbovePosition": row.get("allowHedgeAbovePosition") is True,
        "maxHedgePct": _max_pct(row.get("maxHedgePct"), row.get("allowHedgeAbovePosition") is True),
        "maxHedgeShortPct": _max_pct(row.get("maxHedgeShortPct"), row.get("allowHedgeAbovePosition") is True),
        **_protect_flags(row),
    }


def _protect_flags(row: dict[str, Any]) -> dict[str, bool]:
    """Build 654 (Amar 24-10): "LONG-posities beschermen" / "SHORT-posities beschermen" (not stored = default)."""
    long_flag = row.get("protectLongPositions")
    short_flag = row.get("protectShortPositions")
    return {"protectLongPositions": DEFAULT_PROTECT_LONG if long_flag is None else long_flag is True,
            "protectShortPositions": DEFAULT_PROTECT_SHORT if short_flag is None else short_flag is True}


def _allowed_sides(settings: dict[str, Any]) -> frozenset[str]:
    """Sides that may get a NEW Auto Hedge (trigger or automatic re-hedge after Recovery)."""
    flags = _protect_flags(settings)
    return frozenset(side for side, on in (("LONG", flags["protectLongPositions"]),
                                           ("SHORT", flags["protectShortPositions"])) if on)


def _max_pct(value: Any, allow_above: bool = False) -> float:
    """Build 647: max hedge in % of the position, 1..100 (build 650: up to 200 when the user allows a hedge above
    the position); anything unreadable = 100 (1:1). Without the switch a stored value above 100 counts as 100."""
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return 100.0
    if not math.isfinite(pct) or pct < 1:
        return 100.0
    return min(pct, 200.0 if allow_above else 100.0)


def _max_hedge_update(current: dict[str, Any], request: Any) -> dict[str, Any]:
    """Build 650: stored max hedge fields; above 100% needs "Hedge mag groter dan positie" (422 otherwise)."""
    allow = (current.get("allowHedgeAbovePosition") is True if request.allowHedgeAbovePosition is None
             else bool(request.allowHedgeAbovePosition))
    long_pct = current.get("maxHedgePct") if request.maxHedgePct is None else request.maxHedgePct
    short_pct = current.get("maxHedgeShortPct") if request.maxHedgeShortPct is None else request.maxHedgeShortPct
    for value in (request.maxHedgePct, request.maxHedgeShortPct):
        if value is not None and float(value) > 100 and not allow:
            raise HTTPException(422, "Max hedge boven 100% kan alleen met 'Hedge mag groter dan positie' aan")
    flags = _protect_flags(current)
    return {"allowHedgeAbovePosition": allow,
            "maxHedgePct": _max_pct(long_pct, allow), "maxHedgeShortPct": _max_pct(short_pct, allow),
            "protectLongPositions": flags["protectLongPositions"] if request.protectLongPositions is None
            else bool(request.protectLongPositions),
            "protectShortPositions": flags["protectShortPositions"] if request.protectShortPositions is None
            else bool(request.protectShortPositions)}


def _max_hedge_by_side(settings: dict[str, Any]) -> dict[str, float]:
    """Fraction of the protected position that Auto Hedge hedges, keyed by the PROTECTED side."""
    allow = settings.get("allowHedgeAbovePosition") is True
    return {"LONG": _max_pct(settings.get("maxHedgePct"), allow) / 100.0,
            "SHORT": _max_pct(settings.get("maxHedgeShortPct"), allow) / 100.0}


def _max_hedge_caps(client: Any, settings: dict[str, Any], positions: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    """Build 647: per (symbol, protected side) the hedge quantity at max hedge %, floored to the Aster step.

    Empty when both sides are 100% (then nothing changes and no exchange info is read)."""
    fractions = _max_hedge_by_side(settings)
    if all(f == 1 for f in fractions.values()):
        return {}
    try:
        info = client.public_exchange_info() or {}
        rules = {str(row.get("symbol", "")).upper(): ContractRules.from_exchange_info(row)
                 for row in info.get("symbols", []) if isinstance(row, dict)}
    except Exception:
        rules = {}
    caps: dict[tuple[str, str], float] = {}
    for (symbol, side), row in _position_map(positions).items():
        frac = fractions.get(side, 1.0)
        if frac == 1:
            continue
        rule = rules.get(symbol)
        if rule is None:
            continue                       # no rules: keep 1:1 rather than send an unsendable quantity
        step = Decimal(str(rule.market_quantity_step or 0))
        qty = Decimal(str(position_quantity(row))) * Decimal(str(frac))
        if step > 0:
            qty = (qty / step).to_integral_value(rounding="ROUND_DOWN") * step
        caps[(symbol, side)] = float(qty)
    return caps


def _thresholds_by_side(settings: dict[str, Any]) -> dict[str, float]:
    """Build 623: a LONG position triggers at -thresholdUsd, a SHORT position at -thresholdShortUsd."""
    return {"LONG": float(settings["thresholdUsd"]), "SHORT": float(settings.get("thresholdShortUsd", DEFAULT_THRESHOLD_USD))}


def _plan_field(protected_side: str) -> str:
    """Settings per side: a protected LONG reduces its SHORT hedge (shortRecoveryPlan, historic name);
    a protected SHORT reduces its LONG hedge (longRecoveryPlan)."""
    return "shortRecoveryPlan" if str(protected_side).upper() == "LONG" else "longRecoveryPlan"


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
        "thresholdLongUsd": float(row.get("thresholdUsd", DEFAULT_THRESHOLD_USD)),
        "thresholdShortUsd": float(row.get("thresholdShortUsd", DEFAULT_THRESHOLD_USD)),
        "allowHedgeAbovePosition": row.get("allowHedgeAbovePosition") is True,
        "maxHedgePct": _max_pct(row.get("maxHedgePct"), row.get("allowHedgeAbovePosition") is True),
        "maxHedgeShortPct": _max_pct(row.get("maxHedgeShortPct"), row.get("allowHedgeAbovePosition") is True),
        **_protect_flags(row),
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
        "longRecoveryPlan": _public_short_recovery(row, "longRecoveryPlan"),
        "shortRecoveryExecutionEnabled": SHORT_RECOVERY_EXECUTION_ENABLED,
        "referenceId": "file_00000000ecd08246bd1b15532fb478d6",
    })


def _public_short_recovery(row: dict[str, Any], field: str = "shortRecoveryPlan") -> dict[str, Any]:
    try:
        return normalize_short_recovery_settings(row.get(field) if isinstance(row.get(field), dict) else {})
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
        "thresholdShortUsd": None if request.thresholdShortUsd is None else float(request.thresholdShortUsd),
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
        # A new cycle never inherits a joint-exit of an earlier cycle (it would close the new hedge).
        "pairExit": None,
        "pairExitRequestedAt": None,
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

    Build 623: the surviving leg (LONG or SHORT) gets a 1:1 hedge on the other side. The hedge size is NOT
    decided here: the existing engine (reconcile_auto_hedge) tops the hedge up to exactly the live protected
    quantity, counting the current hedge and pending orders, flooring to the contract step and never exceeding
    the protected leg. Afbouwen of the new cycle counts from the price at this moment. Returns None to skip.
    (Field names longQty/shortQty* are kept for the UI: they mean protected leg / hedge leg.)
    """
    mark = float(remaining.get("markPrice") or remaining.get("entryPrice") or 0)
    base = {"symbol": symbol, "markPrice": mark, "longQty": position_quantity(remaining),
            "protectedSide": remaining_side, "hedgeSide": _opposite(remaining_side)}
    if status not in REHEDGEABLE_STATUSES:
        results[symbol] = {**base, "result": "SKIPPED", "reason": "MANUAL_RELEASE_NOT_CONFIRMED"}
        return None
    if remaining_side not in {"LONG", "SHORT"}:
        results[symbol] = {**base, "result": "SKIPPED", "reason": "POSITION_UNREADABLE"}
        return None
    action = next((a for a in evaluate_auto_hedge(
        positions, threshold, open_orders=open_orders,
        protected_sides={symbol: remaining_side}, skip_symbols=set(),
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
    if action.delta_qty < 0 or action.status == "OVER_COVERED" or action.effective_hedge_qty > action.protected_qty + 1e-12:
        # Already over-hedged: this button never opens or reduces anything for such a pair.
        results[symbol] = {**base, "result": "SKIPPED", "reason": "OVER_HEDGED"}
        return None
    new_state = {**_new_cycle_state(action, state, threshold), "triggerReason": "USER_REHEDGE_ALL",
                 "pairExit": None, "pairExitRequestedAt": None}
    # Amar 23-10: after Re-Hedge All the afbouw counts from the price at the moment of pressing.
    new_state["shortRecovery"] = {"phase": "REFILL", "anchorAtMark": True, "generationId": new_state["generationId"],
                                  "lastEvent": "REHEDGE_ALL", "lastTarget": str(action.protected_qty)}
    if execute:
        _pair_doc(uid, symbol).set(new_state, merge=True)
        _audit(uid, {
            "eventType": "REHEDGE_ALL_CYCLE_STARTED",
            "symbol": symbol,
            "pairCycleId": new_state["generationId"],
            "previousStatus": status,
            "protectedSide": remaining_side,
            "hedgeSide": _opposite(remaining_side),
            "protectedQty": action.protected_qty,
            "hedgeQtyBefore": action.existing_hedge_qty,
            "pendingOpenQty": action.pending_open_qty,
            "requestedDelta": action.required_delta,
            "reason": "USER_REHEDGE_ALL",
        })
    results[symbol] = {**base, "result": "STARTED", "reason": "USER_REHEDGE_ALL", "generationId": new_state["generationId"]}
    return new_state


def _force_rehedge_active(
    *, uid: str, symbol: str, state: dict[str, Any], pmap: dict[tuple[str, str], dict[str, Any]],
    open_orders: list[dict[str, Any]], execute: bool, results: dict[str, dict[str, Any]],
) -> None:
    """Re-Hedge All on a pair that is still in its cycle but partly reduced (halfway the afbouw).

    Amar 23-10: Re-Hedge All puts EVERYTHING back to 100%. The afbouw record goes to REFILL with
    anchorAtMark: this tick the engine tops the hedge up to exactly the protected leg (no target), and the
    next cycle starts at the price of that moment. Updates ``state`` in place for the current tick.
    """
    protected_side = str(state.get("protectedSide", "")).upper()
    hedge_side = _opposite(protected_side)
    protected = pmap.get((symbol, protected_side)) or {}
    hedge = pmap.get((symbol, hedge_side)) or {}
    protected_qty, hedge_qty = position_quantity(protected), position_quantity(hedge)
    mark = float(protected.get("markPrice") or protected.get("entryPrice") or 0)
    base = {"symbol": symbol, "markPrice": mark, "longQty": protected_qty, "shortQtyBefore": hedge_qty,
            "protectedSide": protected_side, "hedgeSide": hedge_side}
    if hedge_qty > protected_qty + 1e-12:
        results[symbol] = {**base, "result": "SKIPPED", "reason": "OVER_HEDGED"}
        return
    if hedge_qty + 1e-12 >= protected_qty:
        results[symbol] = {**base, "result": "SKIPPED", "reason": "ALREADY_FULLY_HEDGED"}
        return
    record = {"phase": "REFILL", "anchorAtMark": True, "generationId": str(state.get("generationId") or ""),
              "cycleId": (state.get("shortRecovery") or {}).get("cycleId") if isinstance(state.get("shortRecovery"), dict) else None,
              "lastEvent": "REHEDGE_ALL", "lastTarget": str(protected_qty)}
    state["shortRecovery"] = record
    state["pairExit"] = None
    if execute:
        _pair_doc(uid, symbol).set({"shortRecovery": record, "pairExit": None, "pairExitRequestedAt": None,
                                    "triggerReason": "USER_REHEDGE_ALL"}, merge=True)
        _audit(uid, {"eventType": "REHEDGE_ALL_MID_LADDER", "symbol": symbol, "protectedSide": protected_side,
                     "protectedQty": protected_qty, "hedgeQtyBefore": hedge_qty, "reason": "USER_REHEDGE_ALL"})
    results[symbol] = {**base, "result": "STARTED", "reason": "USER_REHEDGE_ALL",
                       "missingShortQty": max(0.0, protected_qty - hedge_qty),
                       "generationId": str(state.get("generationId") or "")}


def _flip_roles_to_active_plan(
    uid: str,
    state: dict[str, Any],
    pmap: dict[tuple[str, str], dict[str, Any]],
    open_orders: list[dict[str, Any]],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Build 638 (Amar 23-10): an exactly 1:1 pair follows the afbouw setting that is switched ON.

    For a 1:1 pair "protected" vs "hedge" is only a label: the protection is the same either way. When afbouwen is
    OFF for the current protected side and ON for the other side, swap the labels so the pair joins the grid that
    is switched on (e.g. an old SHORT position with an Auto Hedge LONG, while only SHORT-hedge afbouwen is ON).
    No order is ever placed here; the afbouw record restarts (new cycle anchored on the new hedge's entry).
    Only for a settled HEDGED pair without joint exit and without open orders on the symbol.
    """
    if str(state.get("status", "")).upper() != "HEDGED" or isinstance(state.get("pairExit"), dict):
        return state
    protected_side = str(state.get("protectedSide", "")).upper()
    if protected_side not in {"LONG", "SHORT"}:
        return state
    other = _opposite(protected_side)
    own_plan = settings.get(_plan_field(protected_side))
    other_plan = settings.get(_plan_field(other))
    if (isinstance(own_plan, dict) and own_plan.get("enabled") is True) or not (
            isinstance(other_plan, dict) and other_plan.get("enabled") is True):
        return state
    symbol = str(state.get("symbol", "")).upper()
    if any(isinstance(o, dict) and str(o.get("symbol", "")).upper() == symbol
           and str(o.get("status", "NEW")).upper() not in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
           for o in open_orders or []):
        return state
    protected_qty = position_quantity(pmap.get((symbol, protected_side)))
    hedge_qty = position_quantity(pmap.get((symbol, other)))
    if protected_qty <= 0 or hedge_qty <= 0 or abs(protected_qty - hedge_qty) > max(1e-9, 1e-6 * protected_qty):
        return state
    now = datetime.now(timezone.utc)
    update = {
        "protectedSide": other,
        "hedgeSide": protected_side,
        "currentProtectedQty": hedge_qty,
        "currentHedgeQty": protected_qty,
        "reservedHedgeQty": protected_qty,
        "normalFreeQty": 0.0,
        "protectedLeg": _leg_view(pmap.get((symbol, other))),
        "hedgeLeg": _leg_view(pmap.get((symbol, protected_side))),
        "shortRecovery": None,
        "shortRecoveryShadow": None,
        "rolesFlippedAt": now,
        "lastReason": "ROLES_FLIPPED_TO_ACTIVE_AFBOUW_PLAN",
        "updatedAt": now,
    }
    _pair_doc(uid, symbol).set(update, merge=True)
    _audit(uid, {"eventType": "ROLES_FLIPPED_TO_ACTIVE_AFBOUW_PLAN", "symbol": symbol,
                 "previousProtectedSide": protected_side, "protectedSide": other,
                 "qty": protected_qty, "reason": "AFBOUW_ON_FOR_OTHER_SIDE_ONLY"})
    return {**state, **update}


def _transition_closed_outside_app(
    uid: str,
    state: dict[str, Any],
    pmap: dict[tuple[str, str], dict[str, Any]],
    open_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Vangnet (Amar 23-10): a leg made smaller OUTSIDE the app (e.g. on the Aster website) -> RECOVERY.

    The in-app manual close already goes to RECOVERY. Without this, the engine would see the gap and
    "straighten" the pair itself. Now nothing is bought or sold until the user presses Re-Hedge All.
    Same convention as the in-app close: the reduced leg becomes protectedSide, the other leg hedgeSide
    (the side Re-Hedge All protects). Only for a settled HEDGED pair without open orders on the symbol.
    """
    if str(state.get("status", "")).upper() != "HEDGED" or isinstance(state.get("pairExit"), dict):
        return state
    symbol = str(state.get("symbol", "")).upper()
    protected_side = str(state.get("protectedSide", "")).upper()
    hedge_side = str(state.get("hedgeSide", _opposite(protected_side))).upper()
    stored_protected = float(state.get("currentProtectedQty") or 0)
    stored_hedge = float(state.get("currentHedgeQty") or 0)
    if stored_protected <= 0:
        return state
    if any(isinstance(o, dict) and str(o.get("symbol", "")).upper() == symbol
           and str(o.get("status", "NEW")).upper() not in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
           for o in open_orders or []):
        return state
    # The bot's own order may not be visible yet in Aster's position endpoint (lag): never call that "outside".
    last_action = state.get("lastAction") if isinstance(state.get("lastAction"), dict) else {}
    reconciled = _as_utc(state.get("lastReconciledAt"))
    if last_action.get("exchangeOrderId") is not None and (
            reconciled is None or (datetime.now(timezone.utc) - reconciled).total_seconds() < OUTSIDE_APP_ORDER_GRACE_SECONDS):
        return state
    protected = pmap.get((symbol, protected_side))
    hedge = pmap.get((symbol, hedge_side))
    protected_qty, hedge_qty = position_quantity(protected), position_quantity(hedge)
    tolerance = max(1e-9, 1e-6 * max(stored_protected, stored_hedge, 1.0))
    record = state.get("shortRecovery") if isinstance(state.get("shortRecovery"), dict) else {}
    try:
        expected_hedge = float(record["lastTarget"]) if record.get("lastTarget") is not None else None
    except (TypeError, ValueError):
        expected_hedge = None
    if expected_hedge is not None and abs(hedge_qty - expected_hedge) <= max(tolerance, 1e-6 * max(expected_hedge, 1.0)):
        stored_hedge = hedge_qty            # the hedge is exactly where the afbouw put it: not outside the app
    if protected_qty + tolerance < stored_protected:
        closed_side, survivor_side, reason = protected_side, hedge_side, "PROTECTED_REDUCED_OUTSIDE_APP"
    elif stored_hedge > 0 and hedge_qty + tolerance < stored_hedge:
        closed_side, survivor_side, reason = hedge_side, protected_side, "HEDGE_REDUCED_OUTSIDE_APP"
    else:
        return state
    now = datetime.now(timezone.utc)
    survivor = protected if survivor_side == protected_side else hedge
    closed = hedge if survivor_side == protected_side else protected
    next_state = {
        **state,
        "status": "RECOVERY",
        "protectedSide": closed_side,
        "hedgeSide": survivor_side,
        "reservedHedgeQty": 0.0,
        "normalFreeQty": position_quantity(survivor),
        "rehedgeEnabled": False,
        "recoveryAt": now,
        "currentProtectedQty": position_quantity(closed),
        "currentHedgeQty": position_quantity(survivor),
        "protectedLeg": _leg_view(closed) if closed else None,
        "hedgeLeg": _leg_view(survivor) if survivor else None,
        "lastReason": reason,
        "updatedAt": now,
    }
    _pair_doc(uid, symbol).set(next_state, merge=True)
    _audit(uid, {
        "symbol": symbol,
        "pairCycleId": str(state.get("generationId", "")),
        "resultingStatus": "RECOVERY",
        "reason": reason,
        "protectedQtyBefore": stored_protected, "protectedQtyAfter": protected_qty,
        "hedgeQtyBefore": stored_hedge, "hedgeQtyAfter": hedge_qty,
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
    force_rehedge_symbols: set[str] | None = None,
    force_results: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, str], set[str], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    threshold = float(settings["thresholdUsd"])
    thresholds = _thresholds_by_side(settings)
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
            if status in ACTIVE_STATUSES and execute and symbol not in force:
                state = _transition_closed_outside_app(uid, state, pmap, open_orders)
                status = str(state.get("status", "")).upper()
            if status in ACTIVE_STATUSES:
                side = str(state.get("protectedSide", "")).upper()
                if side in {"LONG", "SHORT"} and pmap.get((symbol, side)):
                    if symbol in force:
                        _force_rehedge_active(
                            uid=uid, symbol=symbol, state=state, pmap=pmap, open_orders=open_orders,
                            execute=execute, results=force_results,
                        )
                    if execute and symbol not in force:
                        state = _flip_roles_to_active_plan(uid, state, pmap, open_orders, settings)
                        side = str(state.get("protectedSide", side)).upper()
                    states[symbol] = state   # this tick works on the updated state (also after a transition)
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
                    active[symbol] = remaining_side
                    created.append(new_state)
                    continue
            if state.get("rehedgeEnabled") is True and allow_new_triggers:
                if (remaining_side in _allowed_sides(settings)
                        and position_open_pnl(remaining) <= -thresholds.get(remaining_side, threshold)):
                    synthetic = evaluate_auto_hedge(
                        positions, threshold, open_orders=open_orders,
                        protected_sides={symbol: remaining_side},
                        skip_symbols=set(), thresholds_by_side=thresholds,
                    )
                    action = next((a for a in synthetic if a.symbol == symbol), None)
                    if action:
                        new_state = _new_cycle_state(action, state, action.threshold_usd)
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
            protected_sides=None, skip_symbols=skip | set(active), thresholds_by_side=thresholds,
            allowed_sides=_allowed_sides(settings),
        )
        for action in candidates:
            if action.symbol in active:
                continue
            prior = states.get(action.symbol)
            new_state = _new_cycle_state(action, prior, action.threshold_usd)
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
            # Build 656: on FOUT keep the real cause (the order error), not the final re-evaluation's generic reason.
            "lastReason": str((action.get("reason") if status in {"BLOCKED", "PRECISION_BLOCKED"} else None)
                              or final.get("reason") or action.get("reason") or ""),
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
OUTSIDE_APP_ORDER_GRACE_SECONDS = 120
PAIR_EXIT_MAX_SECONDS = 180


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return None


def _joint_exit_net(*, symbol: str, legs: tuple[dict[str, Any], dict[str, Any]], since: datetime | None,
                    mark: Any, client: Any) -> dict[str, Any]:
    """Net result of closing BOTH legs now: open PnL both legs - closing fees - PAID funding since the hedge."""
    funding = (short_recovery_pair_exit.paid_funding(client, symbol=symbol, start_ms=int(since.timestamp() * 1000))
               if since else None)
    price = float(mark or 0)
    first, second = legs
    return short_recovery_pair_exit.net_exit(
        long_pnl=position_open_pnl(first), short_pnl=position_open_pnl(second),
        long_notional=position_quantity(first) * price, short_notional=position_quantity(second) * price,
        funding_paid=funding,
    )


def _fresh_exit_request(state: dict[str, Any], now: datetime) -> str | None:
    """The TP side that asked for a joint exit within the request window, else None."""
    requested = _as_utc(state.get("pairExitRequestedAt"))
    if requested is None or (now - requested).total_seconds() > PAIR_EXIT_REQUEST_MAX_AGE_SECONDS:
        return None
    side = str(state.get("pairExitRequestedSide") or state.get("protectedSide") or "").upper()
    return side if side in {"LONG", "SHORT"} else None


def _active_joint_exit(
    *, uid: str, symbol: str, state: dict[str, Any], protected_row: dict[str, Any],
    hedge_row: dict[str, Any], mark: Any, client: Any, now: datetime, field: str,
) -> tuple[Any, str] | None:
    """Joint exit at TP of the PROTECTED leg (LONG or SHORT), only when net positive (build 623).

    Returns (hedge target, event) while this symbol is exiting, else None. Only the hedge leg is touched
    here (target 0 through the existing engine); the TP leg is closed by the Multi-BB TP path once the
    hedge is flat. Applies to every Auto Hedge pair, hedge afbouwen ON or OFF.
    """
    protected_qty = position_quantity(protected_row)
    hedge_qty = position_quantity(hedge_row)
    exiting = state.get("pairExit") if isinstance(state.get("pairExit"), dict) else None
    if exiting:
        if protected_qty <= 0:
            return None  # TP leg closed: the lifecycle moves the pair to CLOSED/RECOVERY
        started = _as_utc(exiting.get("startedAt")) or now
        if hedge_qty <= 0 and (now - started).total_seconds() > PAIR_EXIT_MAX_SECONDS:
            # TP was no longer due: hedge 1:1 again instead of leaving the protected leg open.
            update: dict[str, Any] = {"pairExit": None, "pairExitRequestedAt": None}
            record = state.get(field) if isinstance(state.get(field), dict) else None
            if record:
                update[field] = {**record, "phase": "REFILL", "refillPct": None, "lastEvent": "JOINT_EXIT_EXPIRED_REHEDGE",
                                 "evaluatedAt": now, "lastTarget": str(protected_qty)}
            _pair_doc(uid, symbol).set(update, merge=True)
            _audit(uid, {"eventType": "JOINT_EXIT_EXPIRED_REHEDGE", "symbol": symbol})
            return None, "JOINT_EXIT_EXPIRED_REHEDGE"
        return 0, "JOINT_EXIT_HEDGE_FLAT_WAIT_TP" if hedge_qty <= 0 else "JOINT_EXIT_CLOSING_HEDGE"
    tp_side = _fresh_exit_request(state, now)
    protected_side = str(state.get("protectedSide") or "").upper()
    if tp_side is None or tp_side != protected_side or protected_qty <= 0 or hedge_qty <= 0:
        return None
    record = state.get(field) if isinstance(state.get(field), dict) else {}
    since = _as_utc(state.get("triggerAt")) or _as_utc(record.get("hedgeSince")) or _as_utc(state.get("createdAt"))
    verdict = _joint_exit_net(symbol=symbol, legs=(protected_row, hedge_row), since=since, mark=mark, client=client)
    if not verdict["allowed"]:
        # Evaluate a request once: Multi-BB asks again on its next TP tick (no income read every 3 s).
        _pair_doc(uid, symbol).set({"pairExitRequestedAt": None}, merge=True)
        _audit(uid, {"eventType": "JOINT_EXIT_WAIT", "symbol": symbol, "tpSide": tp_side,
                     "reason": verdict["reason"], "net": None if verdict["net"] is None else str(verdict["net"])})
        return None
    _pair_doc(uid, symbol).set({
        "pairExit": {"phase": "CLOSING_OPPOSITE", "tpSide": tp_side, "startedAt": now, "net": str(verdict["net"])},
        "pairExitRequestedAt": None,
    }, merge=True)
    _audit(uid, {"eventType": "JOINT_EXIT_START", "symbol": symbol, "tpSide": tp_side, "net": str(verdict["net"]),
                 "fees": str(verdict["fees"]), "fundingPaid": str(verdict["fundingPaid"])})
    return 0, "JOINT_EXIT_NET_POSITIVE_CLOSING_HEDGE"


def _recovery_joint_exits(
    *, uid: str, states: dict[str, dict[str, Any]], positions: list[dict[str, Any]], client: Any, now: datetime,
) -> dict[str, str]:
    """Joint exit for Recovery pairs that still have BOTH legs (e.g. after a partial manual close).

    Returns {symbol: tp_side}: the caller closes the OTHER leg to 0 through the engine; the TP leg follows
    via the Multi-BB TP path. Net positive only; never for a manual release that is still in progress.
    """
    pmap = _position_map(positions)
    exits: dict[str, str] = {}
    for symbol, state in states.items():
        if str(state.get("status", "")).upper() not in REHEDGEABLE_STATUSES:
            continue
        exiting = state.get("pairExit") if isinstance(state.get("pairExit"), dict) else None
        if exiting:
            tp_side = str(exiting.get("tpSide") or "").upper()
            other = _opposite(tp_side)
            tp_row, other_row = pmap.get((symbol, tp_side)), pmap.get((symbol, other))
            started = _as_utc(exiting.get("startedAt")) or now
            if not tp_row or (not other_row and (now - started).total_seconds() > PAIR_EXIT_MAX_SECONDS):
                _pair_doc(uid, symbol).set({"pairExit": None}, merge=True)
                continue
            if other_row:
                exits[symbol] = tp_side
            continue
        tp_side = _fresh_exit_request(state, now)
        if tp_side is None:
            continue
        tp_row, other_row = pmap.get((symbol, tp_side)), pmap.get((symbol, _opposite(tp_side)))
        if not tp_row or not other_row:
            continue
        since = _as_utc(state.get("triggerAt")) or _as_utc(state.get("createdAt"))
        mark = tp_row.get("markPrice") or other_row.get("markPrice") or 0
        verdict = _joint_exit_net(symbol=symbol, legs=(tp_row, other_row), since=since, mark=mark, client=client)
        if not verdict["allowed"]:
            _pair_doc(uid, symbol).set({"pairExitRequestedAt": None}, merge=True)
            _audit(uid, {"eventType": "JOINT_EXIT_WAIT", "symbol": symbol, "tpSide": tp_side, "status": "RECOVERY",
                         "reason": verdict["reason"], "net": None if verdict["net"] is None else str(verdict["net"])})
            continue
        _pair_doc(uid, symbol).set({
            "pairExit": {"phase": "CLOSING_OPPOSITE", "tpSide": tp_side, "startedAt": now, "net": str(verdict["net"])},
            "pairExitRequestedAt": None,
        }, merge=True)
        _audit(uid, {"eventType": "JOINT_EXIT_START", "symbol": symbol, "tpSide": tp_side, "status": "RECOVERY",
                     "net": str(verdict["net"])})
        exits[symbol] = tp_side
    return exits


def _short_recovery_exit_reader(uid: str, symbol: str) -> dict[str, Any]:
    return _pair_doc(uid, symbol).get().to_dict() or {}


def _short_recovery_exit_requester(uid: str, symbol: str, side: str = "LONG") -> None:
    _pair_doc(uid, symbol).set({"pairExitRequestedAt": datetime.now(timezone.utc),
                                "pairExitRequestedSide": str(side or "LONG").upper()}, merge=True)


short_recovery_pair_exit.configure(_short_recovery_exit_reader, _short_recovery_exit_requester)


_ENABLED_CACHE_SECONDS = 10.0
_enabled_cache: dict[str, tuple[float, bool]] = {}
_enabled_cache_lock = threading.Lock()


def _auto_hedge_enabled_for_entries(uid: str) -> bool:
    """One-position-per-coin gate for the bot's entry path; cached briefly (entry loops ask per candidate)."""
    now = time.monotonic()
    with _enabled_cache_lock:
        hit = _enabled_cache.get(uid)
    if hit and now - hit[0] < _ENABLED_CACHE_SECONDS:
        return hit[1]
    value = _current(uid).get("enabled") is True
    with _enabled_cache_lock:
        _enabled_cache[uid] = (now, value)
    return value


configure_auto_hedge_enabled_reader(_auto_hedge_enabled_for_entries)


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
    """Hedge targets for the existing engine (+ symbols to hold this tick), both sides (build 623).

    Per active pair: (1) a joint TP exit (every pair, afbouwen ON or OFF); otherwise (2) hedge afbouwen with
    the settings of the protected side: a protected LONG reduces its SHORT hedge on a falling price
    (shortRecoveryPlan), a protected SHORT reduces its LONG hedge on a rising price (longRecoveryPlan).
    Live targets only when ASTER_SHORT_RECOVERY_EXECUTION_ENABLED=true (default) AND this is a live run;
    otherwise ladder decisions are recorded under ``shortRecoveryShadow`` and the engine keeps 1:1.
    A symbol whose inputs cannot be read keeps its last confirmed target (never a blind top-up or cut).
    """
    live = bool(SHORT_RECOVERY_EXECUTION_ENABLED and execute)
    field = "shortRecovery" if live else "shortRecoveryShadow"
    pmap = _position_map(positions)
    now = datetime.now(timezone.utc)
    overrides: dict[str, float] = {}
    hold: set[str] = set()
    rows: list[dict[str, Any]] = []
    rules: dict[str, Any] | None = None
    available: Any = None
    available_read = False
    pending = {
        (str(o.get("symbol", "")).upper(), str(o.get("positionSide", "")).upper())
        for o in open_orders or []
        if isinstance(o, dict)
        and str(o.get("status", "NEW")).upper() not in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
    }
    for symbol, protected_side in protected_sides.items():
        state = states.get(symbol) or {}
        if str(state.get("status", "")).upper() not in ACTIVE_STATUSES:
            continue
        protected_side = str(protected_side).upper()
        hedge_side = _opposite(protected_side)
        protected_row = pmap.get((symbol, protected_side)) or {}
        hedge_row = pmap.get((symbol, hedge_side)) or {}
        mark = protected_row.get("markPrice") or hedge_row.get("markPrice") or 0

        if execute:
            exit_result = _active_joint_exit(
                uid=uid, symbol=symbol, state=state, protected_row=protected_row, hedge_row=hedge_row,
                mark=mark, client=client, now=now, field=field,
            )
            if exit_result is not None:
                target, event = exit_result
                if target is not None:
                    overrides[symbol] = float(target)
                rows.append({"symbol": symbol, "mode": field, "event": event, "hedgeSide": hedge_side,
                             "targetShort": None if target is None else float(target), "phase": "PAIR_EXIT"})
                continue

        plan_settings = settings.get(_plan_field(protected_side))
        plan_settings = plan_settings if isinstance(plan_settings, dict) else {}
        if plan_settings.get("enabled") is not True:
            # Afbouwen OFF for this side: clear any record so the engine keeps the plain 1:1 hedge.
            if execute and state.get(field):
                _pair_doc(uid, symbol).set({field: None}, merge=True)
            continue
        direction = short_recovery_direction(protected_side)
        prior = state.get(field) if isinstance(state.get(field), dict) else None
        generation = str(state.get("generationId") or "")
        if prior and str(prior.get("generationId") or "") != generation:
            prior = None  # a new Auto Hedge generation never inherits an old ladder
        if prior and prior.get("startReason") == "ANCHOR_AT_SWITCH_ON":
            prior = None  # Amar 21:36: anchor = hedge moment (hedge entry); restart cycles anchored at switch-on
        if prior and prior.get("direction") and str(prior.get("direction")).upper() != direction:
            prior = None  # protected side changed: never continue a ladder of the other direction
        if rules is None:
            try:
                info = client.public_exchange_info() or {}
                rules = {
                    str(row.get("symbol", "")).upper(): ContractRules.from_exchange_info(row)
                    for row in (info.get("symbols", []) if isinstance(info, dict) else [])
                    if isinstance(row, dict)
                }
            except Exception:
                rules = {}
        rule = rules.get(symbol)
        if rule is None:
            last = prior.get("lastTarget") if prior else None
            if live and last is not None:
                overrides[symbol] = float(last)
            rows.append({"symbol": symbol, "event": "RULES_UNAVAILABLE_HOLD", "mode": field})
            continue
        if not available_read:
            try:
                available = (client.account_information() or {}).get("availableBalance")
            except Exception:
                available = None
            available_read = True
        hedge_qty: Any = position_quantity(hedge_row)
        hedge_entry: Any = hedge_row.get("entryPrice") or 0
        if not live and prior and prior.get("lastTarget") is not None:
            # Shadow simulates its own hedge: the real hedge stays 1:1, so the simulated quantity is the
            # last target and a simulated (re)open fills at the current mark.
            virtual = float(prior["lastTarget"])
            if prior.get("phase") in {"REFILL", "REOPEN_OPEN"}:
                hedge_qty, hedge_entry = virtual, mark       # simulated (re)open fills at the current mark
            elif abs(virtual - float(hedge_qty)) > 1e-12:
                hedge_qty = virtual                          # simulated partial sale keeps the real entry
        result = short_recovery_decide(
            record=prior, settings=plan_settings,
            long_qty=position_quantity(protected_row), short_qty=hedge_qty,
            short_entry=hedge_entry,
            mark=mark,
            has_pending_short_order=(symbol, hedge_side) in pending,
            start_at_mark=False,  # Amar 21:36: always anchor at the hedge moment (confirmed hedge entry)
            qty_step=rule.market_quantity_step, min_qty=rule.market_min_quantity,
            min_notional=rule.min_notional, available_balance=available,
            leverage=protected_row.get("leverage") or 1,
            direction=direction,
            max_hedge=_max_hedge_by_side(settings).get(protected_side, 1.0),
        )
        record = result["record"]
        if record is not None:
            record = {**record, "generationId": generation, "lastEvent": result["event"], "evaluatedAt": now,
                      "hedgeSince": (prior or {}).get("hedgeSince") or state.get("triggerAt") or now}
        if live and result["event"] == "PENDING_ORDER_HOLD":
            # An order on the hedge is still open: send nothing for this symbol until it is final
            # (a held target next to a pending close could otherwise open extra hedge).
            hold.add(symbol)
        elif live and result["override"] is not None:
            overrides[symbol] = float(result["override"])
        if execute and _short_recovery_record_changed(prior, record):
            # Write only on a real change (the worker ticks every few seconds; Firestore cost).
            _pair_doc(uid, symbol).set({field: record}, merge=True)
        rows.append({
            "symbol": symbol, "mode": field, "event": result["event"], "hedgeSide": hedge_side,
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
            thresholds_by_side=_thresholds_by_side(settings),
            max_caps=_max_hedge_caps(client, settings, positions) or None,
            allowed_sides=_allowed_sides(settings),
        )
        if execute:
            # Joint TP exit of Recovery pairs that still hold both legs: close the non-TP leg to 0.
            recovery_exits = _recovery_joint_exits(
                uid=uid, states=_pair_states(uid), positions=positions, client=client,
                now=datetime.now(timezone.utc),
            )
            if recovery_exits:
                all_symbols = {str(row.get("symbol", "")).upper() for row in positions if isinstance(row, dict)}
                exit_report = reconcile_auto_hedge(
                    client=client, uid=uid, threshold_usd=settings["thresholdUsd"], execute=True,
                    audit=(lambda payload: _audit(uid, payload)),
                    protected_sides=recovery_exits,
                    skip_symbols=all_symbols - set(recovery_exits),
                    intent_context={
                        symbol: {"generationId": f"{(states.get(symbol) or {}).get('generationId') or 'g0'}-exit",
                                 "revision": 0}
                        for symbol in recovery_exits
                    },
                    target_overrides={symbol: 0.0 for symbol in recovery_exits},
                    thresholds_by_side=_thresholds_by_side(settings),
                )
                report["recoveryJointExit"] = exit_report
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
        threshold_short = normalize_threshold(
            current.get("thresholdShortUsd", DEFAULT_THRESHOLD_USD) if request.thresholdShortUsd is None
            else request.thresholdShortUsd)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if request.enabled and not previous_enabled:
        _require_hedge_mode(uid)
    now = datetime.now(timezone.utc)
    _doc(uid).set({
        "enabled": bool(request.enabled),
        "thresholdUsd": threshold,
        "thresholdShortUsd": threshold_short,
        **_max_hedge_update(current, request),
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
        threshold_short = normalize_threshold(
            current.get("thresholdShortUsd", DEFAULT_THRESHOLD_USD) if request.thresholdShortUsd is None
            else request.thresholdShortUsd)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if request.enabled and not previous_enabled:
        _require_hedge_mode(uid)
    _doc(uid).set({
        "enabled": bool(request.enabled),
        "thresholdUsd": threshold,
        "thresholdShortUsd": threshold_short,
        **_max_hedge_update(current, request),
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
    # Build 623: which hedge this card reduces. SHORT = SHORT-hedge of a protected LONG (price falls);
    # LONG = LONG-hedge of a protected SHORT (price rises). Old clients send nothing -> SHORT.
    hedgeSide: str = Field(default="SHORT", pattern="^(LONG|SHORT)$")
    # Build 634 (grid): buy a sold part back after this many levels up; re-hedge 100% this % beyond the last level.
    rebuySteps: int = Field(default=1, ge=0, le=100)          # build 646: 0 = never buy back
    safetyNetPct: str | None = Field(default=None, max_length=16)
    # Build 646: "Terughedgen" X% (default 100) for buy-backs and the vangnet; 0 = after a full reduction nothing more.
    rehedgePct: str | None = Field(default=None, max_length=16)


@main.app.put("/v1/me/aster/position-loss-auto-hedge/short-recovery")
def put_position_loss_auto_hedge_short_recovery(
    request: ShortRecoverySettingsRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    """Save hedge afbouwen settings for one side. Never places an order itself; the worker applies them."""
    uid = main.require_release_feature(user, "auto_hedge_v2")
    try:
        plan = normalize_short_recovery_settings(
            {"enabled": request.enabled, "steps": request.steps, "totalPct": request.totalPct,
             "rebuySteps": request.rebuySteps, "safetyNetPct": request.safetyNetPct,
             "rehedgePct": request.rehedgePct})
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    hedge_side = request.hedgeSide.upper()
    field = "shortRecoveryPlan" if hedge_side == "SHORT" else "longRecoveryPlan"
    if plan["enabled"] and _current(uid).get("enabled") is not True:
        raise HTTPException(409, f"Zet Auto Hedge eerst AAN; afbouwen werkt alleen op Auto Hedge-{hedge_side}-hedges")
    now = datetime.now(timezone.utc)
    previous = _public_short_recovery(_current(uid), field)
    switched_on = plan["enabled"] and not previous.get("enabled")
    if switched_on:
        _require_hedge_mode(uid)
    enabled_at = now if switched_on else ((_current(uid).get(field) or {}).get("enabledAt") if plan["enabled"] else None)
    _doc(uid).set({field: {**plan, "updatedAt": now, "enabledAt": enabled_at}, "updatedAt": now}, merge=True)
    _audit(uid, {"eventType": "SHORT_RECOVERY_SETTINGS_CHANGED", "hedgeSide": hedge_side, "previous": previous,
                 "next": plan, "clientBuild": request.clientBuild})
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
        elif status == "PRECISION_BLOCKED" or str(action.get("reason") or "") == "REST_BELOW_ASTER_MINIMUM":
            # Build 656: a rest below the Aster minimum is still reported as too small (nothing could be added),
            # even though the pair itself now counts as HEDGED instead of FOUT.
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
    def _mid_ladder(row: dict[str, Any]) -> bool:
        record = row.get("shortRecovery") if isinstance(row.get("shortRecovery"), dict) else {}
        if not record.get("phase"):
            return False
        if record.get("phase") in {"REOPEN_CLOSE", "REOPEN_OPEN"} or int(float(record.get("stepsReached") or 0)) > 0:
            return True
        try:
            return float(record.get("lastTarget")) + 1e-12 < float(row.get("currentProtectedQty") or 0)
        except (TypeError, ValueError):
            return False

    candidates = sorted(
        symbol for symbol, row in _pair_states(uid).items()
        if str(row.get("status", "")).upper() in RECOVERY_STATUSES
        or (str(row.get("status", "")).upper() in ACTIVE_STATUSES and _mid_ladder(row))
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
    from serving_revision_gate import is_serving
    while not _worker_stop.wait(WORKER_INTERVAL):
        if not is_serving():
            continue  # Build 626: stand-by op een revisie zonder verkeer
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
