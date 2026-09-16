"""Per-user Profit Sweep configuration routes.

Configuration only: this module never transfers, withdraws or trades funds.
The real money-movement layer is intentionally separate and remains disabled.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field

import main
from profit_sweep import DEFAULT_SWEEP_ENABLED, DEFAULT_SWEEP_PERCENT, ProfitSweepError, normalize_sweep_percent


class ProfitSweepSettingsRequest(BaseModel):
    enabled: bool = DEFAULT_SWEEP_ENABLED
    sweepPercent: float = Field(default=float(DEFAULT_SWEEP_PERCENT), ge=0, le=100)


def _settings_doc(user: dict[str, Any]):
    # Reuse the existing per-user Aster execution-controls document. merge=True below
    # guarantees that unrelated Aster settings remain untouched.
    return main.user_reference(user).collection("executionControls").document("aster")


def _current(data: dict[str, Any] | None) -> tuple[bool, float]:
    root = dict(data or {})
    nested = root.get("profitSweep")
    if not isinstance(nested, dict):
        return DEFAULT_SWEEP_ENABLED, float(DEFAULT_SWEEP_PERCENT)
    enabled = nested.get("enabled") is True
    try:
        percent = float(normalize_sweep_percent(nested.get("sweepPercent", DEFAULT_SWEEP_PERCENT)))
    except ProfitSweepError:
        # Malformed legacy state fails closed: feature OFF and default percentage.
        return False, float(DEFAULT_SWEEP_PERCENT)
    return enabled, percent


def _public(enabled: bool, percent: float) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "sweepPercent": percent,
        "automaticTransferEnabled": False,
        "mode": "CONFIG_ONLY",
        "formula": "max(0, netRealizedProfit) * sweepPercent / 100",
        "principalIncluded": False,
        "unrealizedPnlIncluded": False,
    }


@main.app.get("/v1/me/aster/profit-sweep-settings")
def get_profit_sweep_settings(
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    enabled, percent = _current(_settings_doc(user).get().to_dict() or {})
    response.headers["Cache-Control"] = "no-store"
    return _public(enabled, percent)


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

    _settings_doc(user).set(
        {
            "profitSweep": {
                "enabled": bool(request.enabled),
                "sweepPercent": percent,
                # Hard safety gate: config can be armed now, money movement cannot.
                "automaticTransferEnabled": False,
                "updatedAt": datetime.now(timezone.utc),
            }
        },
        merge=True,
    )
    response.headers["Cache-Control"] = "no-store"
    return _public(bool(request.enabled), percent)
