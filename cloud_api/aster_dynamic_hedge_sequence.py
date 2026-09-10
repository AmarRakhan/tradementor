"""Fast sequential Dynamic Hedge orchestration.

A scheduler tick is not an order-count throttle.  While Dynamic Hedge is enabled,
this runner may perform multiple hedge actions in the same leased Strategy-2 tick.
Every action is still individually exchange-confirmed and followed by a fresh
Aster position/margin read before another action is allowed.

The normal inter-action delay is configurable but clamped to 2..5 seconds.  The
controller stops because exchange truth, margin/risk sizing, a manual lock,
uncertain execution, or the dynamic target says to stop -- not because one order
has already been sent in the current scheduler tick.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
import time
from typing import Any, Callable

from aster_cross_risk import cross_account_risk
from aster_dynamic_hedge_execution import run_dynamic_hedge_overlay
from aster_dynamic_hedge_verify import verify_read_only_projection


def _n(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _delay_seconds() -> float:
    """User-approved fast cadence: never slower than 5s or faster than 2s."""
    raw = _n(os.getenv("ASTER_DYNAMIC_HEDGE_ACTION_DELAY_SECONDS", "2.0"), 2.0)
    return min(5.0, max(2.0, raw))


def _runtime_window_seconds() -> float:
    """Keep one worker lease finite; this is not an action-count limit.

    If this technical runtime window is reached, the next scheduler invocation
    continues from exchange truth.  With the default 2-second cadence, twenty
    actions comfortably fit in one normal sequence.
    """
    raw = _n(os.getenv("ASTER_DYNAMIC_HEDGE_SEQUENCE_WINDOW_SECONDS", "180"), 180.0)
    return min(240.0, max(30.0, raw))


def _active_quantity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        qty = abs(_n(row.get("positionAmt", row.get("quantity"))))
        side = str(row.get("positionSide", row.get("side", ""))).upper().strip()
        symbol = str(row.get("symbol", "")).upper().strip()
        if qty <= 1e-12 or not symbol or side not in {"LONG", "SHORT"}:
            continue
        payload.append({"symbol": symbol, "side": side, "quantity": round(qty, 12)})
    payload.sort(key=lambda item: (item["symbol"], item["side"]))
    return payload


def _exchange_fingerprint(rows: list[dict[str, Any]], open_orders: list[dict[str, Any]]) -> str:
    payload = {
        "positions": _active_quantity_rows(rows),
        "openOrders": sorted(
            (
                str(row.get("symbol", "")).upper(),
                str(row.get("positionSide", "")).upper(),
                str(row.get("orderId", row.get("clientOrderId", ""))),
            )
            for row in open_orders
            if isinstance(row, dict)
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _control_data(control_ref: Any) -> dict[str, Any]:
    snapshot = control_ref.get()
    return snapshot.to_dict() or {}


def _stable_exchange_snapshot(client: Any) -> dict[str, Any] | None:
    """Require two equal position/order fingerprints before the next POST."""
    try:
        first_rows = client.position_risk()
        first_orders = client.open_orders()
        second_rows = client.position_risk()
        second_orders = client.open_orders()
        account = client.account_information()
    except Exception:
        return None
    if not isinstance(first_rows, list) or not isinstance(second_rows, list):
        return None
    if not isinstance(first_orders, list) or not isinstance(second_orders, list) or not isinstance(account, dict):
        return None
    first_fp = _exchange_fingerprint(first_rows, first_orders)
    second_fp = _exchange_fingerprint(second_rows, second_orders)
    if first_fp != second_fp:
        return None
    risk = cross_account_risk(account, second_rows)
    verification = verify_read_only_projection(account, second_rows, risk)
    if not bool(verification.get("passed", False)):
        return None
    return {
        "account": account,
        "positions": second_rows,
        "openOrders": second_orders,
        "risk": risk,
        "verification": verification,
        "fingerprint": second_fp,
    }


def _reactivate_after_confirmed_action(control_ref: Any, client: Any) -> dict[str, Any] | None:
    """Turn ADOPTING back into ACTIVE only from stable, verified exchange truth."""
    stored = _control_data(control_ref)
    if not bool(stored.get("enabled", False)):
        return None
    owner = str(stored.get("ownershipState", "ADOPTING")).upper()
    if owner not in {"ADOPTING", "DYNAMIC_HEDGE_ACTIVE"}:
        # A manual close/uncertain-order lock always wins over the sequence.
        return None
    pending = stored.get("pendingIntent") if isinstance(stored.get("pendingIntent"), dict) else {}
    if pending:
        return None
    snapshot = _stable_exchange_snapshot(client)
    if snapshot is None:
        return None
    now = _now()
    control_ref.set(
        {
            "ownershipState": "DYNAMIC_HEDGE_ACTIVE",
            "stableReads": 2,
            "positionFingerprint": snapshot["fingerprint"],
            "adoptedPositionCount": len(_active_quantity_rows(snapshot["positions"])),
            "lastVerifiedAt": now,
            "lastVerification": snapshot["verification"],
            "lastReason": "Vorige hedge-actie bevestigd; Aster-state en margin opnieuw geverifieerd voor vervolgactie",
            "updatedAt": now,
        },
        merge=True,
    )
    return snapshot


def _finish(last: dict[str, Any], *, total_orders: int, trace: list[dict[str, Any]], started: float, monotonic_fn: Callable[[], float]) -> dict[str, Any]:
    result = dict(last)
    result["ordersSent"] = total_orders
    result["sequenceOrdersSent"] = total_orders
    result["sequenceActions"] = trace
    result["sequenceElapsedSeconds"] = max(0.0, monotonic_fn() - started)
    result["actionDelaySeconds"] = _delay_seconds()
    result["oneOrderPerTick"] = False
    if total_orders > 0 and str(result.get("reason", "")) == "HEDGE_STABLE":
        result["status"] = "ok"
        result["action"] = "DYNAMIC_HEDGE_SEQUENCE"
    return result


def run_dynamic_hedge_sequence(
    *,
    client: Any,
    control_ref: Any,
    settings: Any,
    uid: str,
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    timestamp_ms: int,
    dry_run: bool = False,
    order_budget: int | None = None,
    before_order: Any = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run as many confirmed hedge actions as current risk/margin allows.

    ``order_budget`` is intentionally *not* used as a one-order-per-scan throttle
    for Dynamic Hedge.  Every candidate remains subject to the primitive's live
    execution gate, projected maintenance check, available-margin sizing,
    exchange confirmation, idempotency and side-isolation checks.
    """
    # A dry run has no exchange mutation to reconcile, so one planning decision
    # is the only truthful simulation at this layer.
    if dry_run:
        out = run_dynamic_hedge_overlay(
            client=client,
            control_ref=control_ref,
            settings=settings,
            uid=uid,
            account=account,
            positions=positions,
            open_orders=open_orders,
            timestamp_ms=timestamp_ms,
            dry_run=True,
            order_budget=None,
            before_order=before_order,
        )
        return {**out, "oneOrderPerTick": False, "sequenceOrdersSent": 0, "sequenceActions": []}

    delay = _delay_seconds()
    window = _runtime_window_seconds()
    started = monotonic_fn()
    total_orders = 0
    trace: list[dict[str, Any]] = []
    current_account = account
    current_positions = positions
    current_orders = open_orders

    while True:
        # Finite worker runtime only: this does not cap action count.  The next
        # scheduler invocation continues immediately from exchange truth.
        if total_orders > 0 and monotonic_fn() - started >= window:
            return _finish(
                {
                    "handled": True,
                    "status": "continue-next-tick",
                    "action": "DYNAMIC_HEDGE_SEQUENCE",
                    "reason": "SEQUENCE_RUNTIME_WINDOW_REACHED",
                },
                total_orders=total_orders,
                trace=trace,
                started=started,
                monotonic_fn=monotonic_fn,
            )

        decision = run_dynamic_hedge_overlay(
            client=client,
            control_ref=control_ref,
            settings=settings,
            uid=uid,
            account=current_account,
            positions=current_positions,
            open_orders=current_orders,
            timestamp_ms=timestamp_ms,
            dry_run=False,
            # Dynamic Hedge is not throttled by Strategy-2's per-scan order count.
            # Capital/margin/risk and exchange truth are the continuation gates.
            order_budget=None,
            before_order=before_order,
        )
        sent = int(_n(decision.get("ordersSent")))
        if sent <= 0:
            return _finish(decision, total_orders=total_orders, trace=trace, started=started, monotonic_fn=monotonic_fn)

        total_orders += sent
        trace.append(
            {
                "sequence": total_orders,
                "action": str(decision.get("action", "")),
                "symbol": str(decision.get("symbol", "")),
                "proof": decision.get("proof"),
            }
        )
        if str(decision.get("status", "")).lower() != "ok":
            return _finish(decision, total_orders=total_orders, trace=trace, started=started, monotonic_fn=monotonic_fn)

        # User-approved cadence: after a confirmed fill, remeasure in 2..5s and
        # continue in this same scheduler tick if another action is still needed.
        sleep_fn(delay)

        # A user/manual action may have acquired the lock while we waited.
        stored = _control_data(control_ref)
        if not bool(stored.get("enabled", False)):
            return _finish(
                {"handled": True, "status": "stopped", "action": "HOLD", "reason": "DYNAMIC_HEDGE_DISABLED_DURING_SEQUENCE"},
                total_orders=total_orders,
                trace=trace,
                started=started,
                monotonic_fn=monotonic_fn,
            )
        if str(stored.get("ownershipState", "ADOPTING")).upper() not in {"ADOPTING", "DYNAMIC_HEDGE_ACTIVE"}:
            return _finish(
                {"handled": True, "status": "waiting", "action": "HOLD", "reason": "MANUAL_OR_UNCERTAIN_LOCK_DURING_SEQUENCE"},
                total_orders=total_orders,
                trace=trace,
                started=started,
                monotonic_fn=monotonic_fn,
            )

        fresh = _reactivate_after_confirmed_action(control_ref, client)
        if fresh is None:
            return _finish(
                {"handled": True, "status": "waiting", "action": "HOLD", "reason": "POST_ACTION_RECONCILIATION_NOT_STABLE"},
                total_orders=total_orders,
                trace=trace,
                started=started,
                monotonic_fn=monotonic_fn,
            )
        current_account = fresh["account"]
        current_positions = fresh["positions"]
        current_orders = fresh["openOrders"]
