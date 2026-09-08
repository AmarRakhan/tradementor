"""Portfolio Snapshot bulk-profit actions using the existing Aster close adapter."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from google.api_core import exceptions as google_exceptions
from pydantic import BaseModel, Field

from aster_profit_close import MINIMUM_PROFIT_USD, position_profit, strict_profit_preview, strictly_profitable_positions
from main import (
    PairExecutionPlan,
    PositionSide,
    _acquire_strategy2_queue_lease,
    _portfolio_growth_client,
    _release_strategy2_queue_lease,
    aster_strategy2_reference,
    authenticated_user,
    execute_aster_leg,
    safe_float,
    user_reference,
)


router = APIRouter()


class SnapshotProfitCloseRequest(BaseModel):
    confirm: bool
    side: str = Field(pattern="^(ALL|LONG|SHORT)$")
    idempotency_key: str = Field(min_length=16, max_length=120)


def _fresh_snapshot_preview(user: dict[str, Any]) -> dict[str, Any]:
    client = _portfolio_growth_client(user, live=False)
    try:
        preview = strict_profit_preview(client.position_risk())
    except Exception as exc:
        raise HTTPException(502, "Actuele Aster-winstposities konden niet betrouwbaar worden gecontroleerd") from exc
    return {
        **preview,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "reliable": True,
    }


@router.get("/v1/me/aster/positions/snapshot-profit-close-preview")
def snapshot_profit_close_preview(
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Read-only LONG/SHORT/ALL preview from one fresh Aster position-risk read."""
    return _fresh_snapshot_preview(user)


@router.post("/v1/me/aster/positions/snapshot-close-profitable")
def snapshot_close_profitable(
    request: SnapshotProfitCloseRequest,
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Close only still-profitable legs in the explicitly confirmed Snapshot scope."""
    if not request.confirm:
        raise HTTPException(422, "Bevestiging voor winstposities sluiten ontbreekt")
    if os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "false").lower() != "true":
        raise HTTPException(423, "Aster productie-uitvoering staat centraal uit")

    uid = str(user["uid"])
    scope = request.side.upper()
    action_hash = hashlib.sha256(f"{uid}:{scope}:{request.idempotency_key}".encode()).hexdigest()
    action_ref = user_reference(user).collection("asterSnapshotProfitCloseIntents").document(action_hash)
    try:
        action_ref.create({
            "uid": uid,
            "scope": scope,
            "status": "prepared",
            "minimumProfitUsd": MINIMUM_PROFIT_USD,
            "comparison": "strictly_greater_than",
            "createdAt": datetime.now(timezone.utc),
        })
    except google_exceptions.AlreadyExists:
        existing = action_ref.get().to_dict() or {}
        if existing.get("status") == "completed":
            return {**(existing.get("result") or {}), "duplicate": True}
        raise HTTPException(409, "Deze winstsluiting wordt al verwerkt; er worden geen dubbele orders geplaatst")

    strategy_ref = aster_strategy2_reference(uid)
    queue_token = _acquire_strategy2_queue_lease(strategy_ref)
    if not queue_token:
        action_ref.set({"status": "blocked", "reason": "strategy2_order_busy", "updatedAt": datetime.now(timezone.utc)}, merge=True)
        raise HTTPException(409, "Strategy 2 verwerkt nog een order; probeer het zo opnieuw")

    closed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    try:
        client = _portfolio_growth_client(user, live=True)
        initial = strictly_profitable_positions(client.position_risk(), side=scope)
        for index, candidate in enumerate(initial, 1):
            symbol = candidate["symbol"]
            side = candidate["side"]

            # Exchange truth is re-read immediately before every order. The
            # $0.50 floor is intentionally strict here: exactly $0.50 is skipped.
            live_rows = client.position_risk()
            current = next((row for row in live_rows
                if str(row.get("symbol", "")).upper() == symbol
                and str(row.get("positionSide", "")).upper() == side
                and abs(safe_float(row.get("positionAmt"))) > 0), None)
            if current is None:
                skipped.append({**candidate, "reason": "positie bestaat niet meer"})
                continue
            current_profit = position_profit(current)
            live_quantity = abs(safe_float(current.get("positionAmt")))
            mark = safe_float(current.get("markPrice"))
            if current_profit is None or current_profit <= MINIMUM_PROFIT_USD or live_quantity <= 0 or mark <= 0:
                skipped.append({
                    **candidate,
                    "currentProfitUsd": current_profit,
                    "reason": "niet langer meer dan $0,50 groen",
                })
                continue

            try:
                plan = PairExecutionPlan(
                    symbol,
                    Decimal(str(live_quantity)),
                    Decimal(str(live_quantity * mark)),
                    max(1, int(safe_float(current.get("leverage")) or 1)),
                )
                result = execute_aster_leg(
                    client,
                    plan,
                    side=PositionSide(side),
                    action="CLOSE",
                    id_prefix=f"tm-snapshot-profit-{action_hash[:10]}-{index}",
                    confirm=True,
                    manual_loss_confirmation=True,
                )
                tolerance = max(1e-12, live_quantity * 1e-9)
                remaining = next((row for row in client.position_risk()
                    if str(row.get("symbol", "")).upper() == symbol
                    and str(row.get("positionSide", "")).upper() == side
                    and abs(safe_float(row.get("positionAmt"))) > tolerance), None)
                if remaining is not None:
                    raise RuntimeError("Aster heeft de volledige sluiting nog niet bevestigd")
                closed.append({
                    "symbol": symbol,
                    "side": side,
                    "closedSize": live_quantity,
                    "profitAtSubmitUsd": current_profit,
                    "order": result,
                })
            except Exception as exc:
                failed.append({"symbol": symbol, "side": side, "reason": str(exc)[:240]})

        result = {
            "scope": scope,
            "closedCount": len(closed),
            "skippedCount": len(skipped),
            "failedCount": len(failed),
            "profitAtSubmitUsd": round(sum(item["profitAtSubmitUsd"] for item in closed), 8),
            "closed": closed,
            "skipped": skipped,
            "failed": failed,
            "minimumProfitUsd": MINIMUM_PROFIT_USD,
            "comparison": "strictly_greater_than",
            "message": f"{len(closed)} {scope.lower()} winstpositie(s) gesloten · {len(skipped)} overgeslagen · {len(failed)} mislukt",
        }
        action_ref.set({"status": "completed", "result": result, "completedAt": datetime.now(timezone.utc)}, merge=True)
        strategy_ref.collection("audit").document().set({
            "event": "SNAPSHOT_BULK_PROFIT_CLOSE_COMPLETED",
            "uid": uid,
            "scope": scope,
            "actionId": action_hash,
            "closedCount": len(closed),
            "skippedCount": len(skipped),
            "failedCount": len(failed),
            "profitAtSubmitUsd": result["profitAtSubmitUsd"],
            "timestamp": datetime.now(timezone.utc),
        })
        return {**result, "duplicate": False}
    except HTTPException:
        raise
    except Exception as exc:
        action_ref.set({
            "status": "PARTIAL_FAIL_CLOSED" if closed else "FAILED_BEFORE_CLOSE",
            "reason": str(exc)[:500],
            "updatedAt": datetime.now(timezone.utc),
        }, merge=True)
        raise HTTPException(502, "Winstsluiting is veilig gestopt; onbekende posities worden niet opnieuw besteld") from exc
    finally:
        _release_strategy2_queue_lease(strategy_ref, queue_token)
