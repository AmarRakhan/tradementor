"""Runtime wiring for automatic Profit Pot sweeps.

The extension keeps tenant identity outside the generic Aster transport.  It
tracks the authorized API-wallet signer when a user's Aster secret is loaded,
then exposes prepare/finalize hooks used by the central execute_leg_once close
path.  Sweep failures never turn an already-valid position close into a failure.
"""
from __future__ import annotations

import threading
from typing import Any

import main
from aster_close_guard import CloseEvidence
from aster_gateway import AsterOrderIntent, PositionSide
from profit_sweep_live import finalize_close_sweep, prepare_close_sweep

_lock = threading.RLock()
_signer_uid: dict[str, str] = {}
_installed = False
_original_load_aster_secret = main.load_aster_secret


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


def _uid_for(client: Any, evidence: CloseEvidence | None) -> str:
    if evidence is not None and str(evidence.account_uid or "").strip():
        return str(evidence.account_uid).strip()
    signer = str(getattr(client, "_signer_address", "")).strip().lower()
    with _lock:
        return _signer_uid.get(signer, "")


def prepare_close_sweep_context(
    *,
    client: Any,
    intent: AsterOrderIntent,
    close_evidence: CloseEvidence | None,
) -> Any:
    """Prepare a sweep without ever blocking the position close."""
    try:
        uid = _uid_for(client, close_evidence)
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
            evidence=close_evidence,
        )
    except Exception:
        return None


def finalize_close_sweep_context(
    prepared: Any,
    *,
    client: Any,
    confirmed_order: dict[str, Any],
    close_evidence: CloseEvidence | None,
) -> None:
    """Finalize secondary savings work; never change the close result."""
    if prepared is None:
        return
    try:
        finalize_close_sweep(
            prepared,
            client=client,
            confirmed_order=confirmed_order,
            evidence=close_evidence,
        )
    except Exception:
        return


def install() -> None:
    global _installed
    if _installed:
        return
    # Replace the main-module global used by all request/runtime factories.
    # The secret material itself is never copied into the registry.
    main.load_aster_secret = _tracked_load_aster_secret
    _installed = True


install()
