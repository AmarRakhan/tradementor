"""Authenticated read-only Aster Spot balance route.

This module deliberately exposes no order, transfer or withdrawal operation.
Importing it registers the route on ``main.app``.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Query, Response

import main
from aster_signing import local_eip712_signer
from aster_spot_balance import (
    AsterSpotBalanceError,
    SUPPORTED_SPOT_ASSETS,
    build_signed_account_query,
    normalize_spot_balance,
)


ASTER_SPOT_REST = "https://sapi.asterdex.com"
_EVM_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_nonce_lock = threading.Lock()
_last_nonce = 0


def _nonce() -> int:
    global _last_nonce
    with _nonce_lock:
        candidate = time.time_ns() // 1_000
        _last_nonce = max(candidate, _last_nonce + 1)
        return _last_nonce


def _master_wallet(user: dict[str, Any]) -> str:
    control = main.user_reference(user).collection("executionControls").document("aster").get().to_dict() or {}
    master = str(control.get("masterAddress", "")).strip().lower()
    if not _EVM_ADDRESS.fullmatch(master):
        raise HTTPException(409, "Koppel eerst je MetaMask-wallet aan je Aster-account")
    return master


def _spot_account(user: dict[str, Any]) -> dict[str, Any]:
    secret = main.load_aster_secret(user)
    try:
        query = build_signed_account_query(
            user_address=_master_wallet(user),
            signer_address=secret.signer_address,
            nonce=_nonce(),
            sign_message=local_eip712_signer(secret),
        )
    except AsterSpotBalanceError as exc:
        raise HTTPException(409, str(exc)) from exc

    try:
        with httpx.Client(base_url=ASTER_SPOT_REST, timeout=15.0) as client:
            # Aster explicitly recommends no form Content-Type header on signed GETs.
            response = client.get(f"/api/v3/account?{query}", headers={"Accept": "application/json"})
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Aster Spot is tijdelijk niet bereikbaar") from exc

    code = payload.get("code") if isinstance(payload, dict) else None
    if response.status_code >= 400 or code not in (None, 0, "0"):
        message = payload.get("msg", payload.get("message", "Aster Spot heeft de aanvraag afgewezen")) if isinstance(payload, dict) else "Aster Spot heeft de aanvraag afgewezen"
        if str(code) == "-5050":
            raise HTTPException(409, "Aster Spot V3 is pas beschikbaar nadat de hoofdwallet een storting heeft voltooid")
        status = 429 if response.status_code in {418, 429} else 409
        raise HTTPException(status, str(message))
    if not isinstance(payload, dict):
        raise HTTPException(502, "Aster Spot gaf geen geldig accountantwoord")
    return payload


@main.app.get("/v1/me/aster/spot-balance")
def aster_spot_balance(
    response: Response,
    asset: str = Query(default="USDC", pattern="^(USDC|USDT)$"),
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    """Return only the authenticated user's current Spot balance for one stablecoin."""
    symbol = asset.strip().upper()
    if symbol not in SUPPORTED_SPOT_ASSETS:
        raise HTTPException(422, "Alleen USDC en USDT worden ondersteund")
    try:
        result = normalize_spot_balance(_spot_account(user), symbol)
    except AsterSpotBalanceError as exc:
        raise HTTPException(502, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-TradeMentor-Aster-Mode"] = "spot-read-only"
    return result
