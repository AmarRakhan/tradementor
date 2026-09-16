"""Per-user Profit Sweep configuration routes.

Configuration only: this module does not transfer, withdraw or trade funds.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field

import main
from profit_sweep import DEFAULT_SWEEP_PERCENT, ProfitSweepError, normalize_sweep_percent


class ProfitSweepSettingsRequest(BaseModel):
    sweepPercent: float = Field(ge=0, le=100)


def _settings_doc(user: dict[str, Any]):
    return main.user_reference(user).collection("executionControls").document("aster")


def _current_percent(data: dict[str, Any] | None) -> float:
    root = dict(data or {})
    nested = root.get("profitSweep")
    raw = nested.get("sweepPercent") if isinstance(nested, dict) else DEFAULT_SWEEP_PERCENT
    try:
        return float(normalize_sweep_percent(raw))
    except ProfitSweepError:
        # A malformed legacy value must never silently enable a write path.
        return float(DEFAULT_SWEEP_PERCENT)


def _public(percent: float) -> dict[str, Any]:
    return {
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
    data = _settings_doc(user).get().to_dict() or {}
    response.headers["Cache-Control"] = "no-store"
    return _public(_current_percent(data))


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
                "sweepPercent": percent,
                "automaticTransferEnabled": False,
                "updatedAt": datetime.now(timezone.utc),
            }
        },
        merge=True,
    )
    response.headers["Cache-Control"] = "no-store"
    return _public(percent)
