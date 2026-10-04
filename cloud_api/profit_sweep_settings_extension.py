"""Per-user Profit Sweep configuration routes.

The user controls whether savings are armed and which percentage applies to
future closes.  The production money-movement gate is independent and exposed
read-only so the UI can distinguish configured from actually live automation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from typing import Any

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field

import main
from profit_sweep import DEFAULT_SWEEP_ENABLED, DEFAULT_SWEEP_PERCENT, ProfitSweepError, normalize_sweep_percent
from profit_sweep_live import live_enabled


class ProfitSweepSettingsRequest(BaseModel):
    enabled: bool = DEFAULT_SWEEP_ENABLED
    sweepPercent: float = Field(default=float(DEFAULT_SWEEP_PERCENT), ge=0, le=100)
    minimumTransfer: float = Field(default=1.0, ge=0.01, le=1000)
    transferAsset: str = Field(default="USDT", pattern="^(USDT|USDC)$")

LOCAL_DAY_TZ = ZoneInfo("Europe/Amsterdam")


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)
    return result if result.is_finite() else Decimal(default)


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _state_doc(user: dict[str, Any]):
    return main.user_reference(user).collection("asterProfitSweepState").document("current")


def _state_public(user: dict[str, Any]) -> dict[str, Any]:
    state = _state_doc(user).get().to_dict() or {}
    today_key = datetime.now(LOCAL_DAY_TZ).date().isoformat()
    today_total = _decimal(state.get("todayTransferred")) if str(state.get("todayKey", "")) == today_key else Decimal("0")
    return {
        "pendingSavings": _plain(max(Decimal("0"), _decimal(state.get("pendingSavings")))),
        "todayTransferred": _plain(max(Decimal("0"), today_total)),
        "todayKey": today_key,
        "lastTransferAmount": _plain(max(Decimal("0"), _decimal(state.get("lastTransferAmount")))),
        "transferInFlight": isinstance(state.get("inFlight"), dict) and bool(state.get("inFlight", {}).get("claimId")),
    }


def _settings_doc(user: dict[str, Any]):
    # Reuse the existing per-user Aster execution-controls document. merge=True
    # guarantees that unrelated Aster settings remain untouched.
    return main.user_reference(user).collection("executionControls").document("aster")


def _current(data: dict[str, Any] | None) -> tuple[bool, float, float, str]:
    root = dict(data or {})
    nested = root.get("profitSweep")
    if not isinstance(nested, dict):
        return DEFAULT_SWEEP_ENABLED, float(DEFAULT_SWEEP_PERCENT), 1.0, "USDT"
    enabled = nested.get("enabled") is True
    try:
        percent = float(normalize_sweep_percent(nested.get("sweepPercent", DEFAULT_SWEEP_PERCENT)))
    except ProfitSweepError:
        # Malformed legacy state fails closed: feature OFF and default percentage.
        return False, float(DEFAULT_SWEEP_PERCENT), 1.0, "USDT"
    minimum = float(_decimal(nested.get("minimumTransfer", 1.0), "1"))
    if minimum < 0.01 or minimum > 1000:
        minimum = 1.0
    asset = str(nested.get("transferAsset", "USDT")).upper().strip()
    if asset not in {"USDT", "USDC"}:
        asset = "USDT"
    return enabled, percent, minimum, asset


def _public(enabled: bool, percent: float, minimum: float, asset: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    automatic = bool(enabled) and percent > 0 and live_enabled()
    return {
        "enabled": bool(enabled),
        "sweepPercent": percent,
        "automaticTransferEnabled": automatic,
        "mode": "LIVE_AUTO_TRANSFER" if automatic else ("ARMED_WAITING_GLOBAL_GATE" if enabled else "OFF"),
        "formula": "max(0, netRealizedProfit) * sweepPercent / 100",
        "principalIncluded": False,
        "unrealizedPnlIncluded": False,
        "transferDirection": "FUTURE_SPOT" if automatic else None,
        "transferAsset": asset,
        "minimumTransfer": minimum,
        "onlyPositiveProfits": True,
        "accumulateSmallAmounts": True,
        "retryFailedTransfers": True,
        **(state or {}),
    }


@main.app.get("/v1/me/aster/profit-sweep-settings")
def get_profit_sweep_settings(
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    enabled, percent, minimum, asset = _current(_settings_doc(user).get().to_dict() or {})
    response.headers["Cache-Control"] = "no-store"
    return _public(enabled, percent, minimum, asset, _state_public(user))


@main.app.put("/v1/me/aster/profit-sweep-settings")
def put_profit_sweep_settings(
    request: ProfitSweepSettingsRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    try:
        percent = float(normalize_sweep_percent(request.sweepPercent))
    except ProfitSweepError as exc:
        raise HTTPException(422, str(exc)) from exc

    minimum = float(request.minimumTransfer)
    asset = request.transferAsset.upper().strip()
    _settings_doc(user).set(
        {
            "profitSweep": {
                "enabled": bool(request.enabled),
                "sweepPercent": percent,
                "minimumTransfer": minimum,
                "transferAsset": asset,
                "updatedAt": datetime.now(timezone.utc),
            }
        },
        merge=True,
    )
    response.headers["Cache-Control"] = "no-store"
    return _public(bool(request.enabled), percent, minimum, asset, _state_public(user))
