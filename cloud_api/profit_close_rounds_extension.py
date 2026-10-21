"""Close Profits 2.1 — HTTP routes for resumable Close Profits rounds.

Every order still goes through the existing individual close route ``main.close_one_aster_position`` (unchanged);
this router only stores the round and decides, per item, whether to call it, skip it, or first ask Aster.
No new Firestore index: document reads/writes only.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from google.api_core import exceptions as google_exceptions
from pydantic import BaseModel, Field

import main
from aster_execution import client_order_id
from manual_profit_close_planner import build_profit_close_plan, filters_from_aster_exchange_info
import profit_close_rounds as rounds

router = APIRouter()


class ProfitCloseRoundTarget(BaseModel):
    symbol: str = Field(min_length=2, max_length=30)
    side: str = Field(pattern="^SHORT$")
    quantity: float = Field(gt=0)


class ProfitCloseRoundCreateRequest(BaseModel):
    confirm: bool
    percentage: int
    idempotency_key: str = Field(min_length=16, max_length=120)
    targets: list[ProfitCloseRoundTarget] = Field(min_length=1, max_length=rounds.MAX_ITEMS)


def _env() -> rounds.RoundEnv:
    return rounds.RoundEnv(
        db=main.db,
        transactional=main.firestore.transactional,
        already_exists=google_exceptions.AlreadyExists,
        http_exception=HTTPException,
        close_route=main.close_one_aster_position,
        make_request=lambda **kw: main.AsterManualCloseRequest(**kw),
        client_for=lambda user: main._portfolio_growth_client(user, live=False),
        plan=lambda rows, percentage, filters: build_profit_close_plan(
            rows, percentage, filters, hedge_links={}, include_short_below_minimum=True),
        filters=filters_from_aster_exchange_info,
        client_order_id=client_order_id,
    )


def _call(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except rounds.RoundError as exc:
        # String detail only (the web client reads `detail` as text); the active round is fetched via /active.
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("/v1/me/aster/profit-close-rounds/active")
def active_profit_close_round(user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    return {"round": _call(rounds.get_active, _env(), str(user["uid"]))}


@router.post("/v1/me/aster/profit-close-rounds")
def create_profit_close_round(
    request: ProfitCloseRoundCreateRequest, user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(422, "Bevestiging voor Close Profits ontbreekt")
    return _call(rounds.create_round, _env(), user, percentage=request.percentage,
                 idempotency_key=request.idempotency_key, targets=[t.model_dump() for t in request.targets])


@router.get("/v1/me/aster/profit-close-rounds/{round_id}")
def get_profit_close_round(round_id: str, user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    return {"round": _call(rounds.get_round, _env(), str(user["uid"]), round_id)}


@router.post("/v1/me/aster/profit-close-rounds/{round_id}/advance")
def advance_profit_close_round(round_id: str,
                               user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    return _call(rounds.advance, _env(), user, round_id)


@router.post("/v1/me/aster/profit-close-rounds/{round_id}/resume")
def resume_profit_close_round(round_id: str,
                              user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    return _call(rounds.resume, _env(), user, round_id)


@router.post("/v1/me/aster/profit-close-rounds/{round_id}/abandon")
def abandon_profit_close_round(round_id: str,
                               user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    return _call(rounds.abandon, _env(), user, round_id)
