"""Runtime wiring for automatic Profit Pot sweeps.

Every Aster close submitted through the shared V3 client is prepared before the
POST and finalized only after the existing execution layer proves the order is
FILLED.  This covers bot and manual close routes without changing strategy
logic.  Sweep failures are secondary and never turn a valid close into failure.
"""
from __future__ import annotations

import threading
from typing import Any

import aster_execution
import aster_gateway
import main
from aster_gateway import AsterOrderIntent
from profit_sweep_live import finalize_close_sweep, is_closing_fill, prepare_close_sweep

_lock = threading.RLock()
_signer_uid: dict[str, str] = {}
_pending: dict[tuple[int, str], Any] = {}
_installed = False
_original_load_aster_secret = main.load_aster_secret
_original_submit_order_once = aster_gateway.AsterV3Client.submit_order_once
_original_confirmed_fill = aster_execution._confirmed_fill


def _register(signer: str, uid: str) -> None:
    signer_key = str(signer or "").strip().lower()
    uid_key = str(uid or "").strip()
    if not signer_key or not uid_key:
        return
    with _lock:
        _signer_uid[signer_key] = uid_key


def _tracked_load_aster_secret(user: dict[str, Any]):
    secret = _original_load_aster_secret(user)
    _register(secret.signer_address, str(user.get("uid", "")))
    return secret


def _uid_for(client: Any) -> str:
    signer = str(getattr(client, "_signer_address", "")).strip().lower()
    with _lock:
        return _signer_uid.get(signer, "")


def _prepare(client: Any, intent: AsterOrderIntent) -> Any:
    if str(intent.action).upper() != "CLOSE":
        return None
    try:
        uid = _uid_for(client)
        if not uid:
            return None
        return prepare_close_sweep(
            uid=uid,
            user_ref=main.db.collection("users").document(uid),
            client=client,
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            position_side=intent.position_side.value,
            close_quantity=intent.quantity,
            evidence=None,
        )
    except Exception:
        return None


def _tracked_submit_order_once(
    self: Any,
    intent: AsterOrderIntent,
    *,
    config: Any,
    confirm: bool,
    hedge_mode_confirmed: bool,
    risk_approved: bool,
):
    key = (id(self), intent.intent_id)
    prepared = _prepare(self, intent)
    if prepared is not None:
        with _lock:
            _pending[key] = prepared
    try:
        return _original_submit_order_once(
            self,
            intent,
            config=config,
            confirm=confirm,
            hedge_mode_confirmed=hedge_mode_confirmed,
            risk_approved=risk_approved,
        )
    except Exception:
        # An unconfirmed close must never trigger a money movement.  The durable
        # PREPARED row remains useful audit evidence but is not retried blindly.
        with _lock:
            _pending.pop(key, None)
        raise


def _tracked_confirmed_fill(
    client: Any,
    intent_id: str,
    symbol: str,
    result: dict[str, Any],
    *,
    poll_attempts: int = 1,
    poll_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    confirmed = _original_confirmed_fill(
        client,
        intent_id,
        symbol,
        result,
        poll_attempts=poll_attempts,
        poll_delay_seconds=poll_delay_seconds,
    )
    key = (id(client), intent_id)
    with _lock:
        prepared = _pending.pop(key, None)
    if prepared is None or not is_closing_fill(confirmed):
        return confirmed
    try:
        finalize_close_sweep(prepared, client=client, confirmed_order=confirmed, evidence=None)
    except Exception:
        # Savings are subordinate to the already-confirmed close.  Never make
        # callers retry a close because a Spot sweep failed or became uncertain.
        pass
    return confirmed


def install() -> None:
    global _installed
    if _installed:
        return
    # Main runtime factories resolve this global when a tenant client is built.
    # Secret material is never copied; only signer-address -> tenant uid is kept.
    main.load_aster_secret = _tracked_load_aster_secret
    aster_gateway.AsterV3Client.submit_order_once = _tracked_submit_order_once
    # execute_leg_once resolves its module-global _confirmed_fill at call time,
    # so every already-imported strategy alias goes through this hook as well.
    aster_execution._confirmed_fill = _tracked_confirmed_fill
    _installed = True


install()
