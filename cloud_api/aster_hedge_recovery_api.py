"""Interactive Aster hedge-recovery API installer.

The routes registered here are deliberately stateful and fail-closed. A preview
stores the exact order plan, explicit confirmation reserves one action, and each
live step executes at most one market order. That makes mobile refresh/retry and
Stop safe without inventing background order state.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import math
import os
import secrets as python_secrets
from typing import Any, Callable

from fastapi import Depends, HTTPException
from firebase_admin import firestore
from pydantic import BaseModel, Field

from aster_execution import PairExecutionPlan, execute_leg_once, plan_pair, planning_brackets
from aster_gateway import ContractRules, PositionSide
from aster_profit_close import profit_preview, position_notional
from aster_strategy2 import Strategy2Config
from aster_universe import build_snapshot, entry_fill_symbols, side_entry_candidates
from mexc_gateway import safe_float
from aster_hedge_recovery import (
    apply_notional_impact,
    average_start_margin,
    average_start_margin_with_fallback,
    correction_step_reached,
    normalize_settings,
    portfolio_exposure,
    ranked_close_candidates,
    recommended_actions,
    step_target_percent,
    strategy_fallback_start_margin,
    validate_recovery_direction,
    would_exceed_step_target,
)


class HedgeSettingsRequest(BaseModel):
    target_percent: float = Field(ge=1, le=200)
    healthy_min_percent: float = Field(ge=0, le=200)
    healthy_max_percent: float = Field(gt=0, le=250)
    max_correction_percent: float = Field(ge=1, le=100)


class HedgePreviewRequest(BaseModel):
    action: str = Field(pattern="^(OPEN_SHORT|OPEN_LONG|CLOSE_SHORT|CLOSE_LONG)$")
    seat_count: int = Field(ge=1, le=100)


class HedgeStartRequest(BaseModel):
    preview_id: str = Field(min_length=8, max_length=120)
    idempotency_key: str = Field(min_length=16, max_length=180)
    confirm: bool


class HedgeStepRequest(BaseModel):
    confirm: bool


class HedgeStopRequest(BaseModel):
    confirm: bool


def _config_ref(user: dict[str, Any], user_reference: Callable[[dict[str, Any]], Any]):
    return user_reference(user).collection("asterHedgeRecovery").document("config")


def load_hedge_settings(user: dict[str, Any], user_reference: Callable[[dict[str, Any]], Any]) -> dict[str, float]:
    raw = _config_ref(user, user_reference).get().to_dict() or {}
    source = raw.get("settings") if isinstance(raw.get("settings"), dict) else raw
    return normalize_settings(source)


def _dynamic_impact(rows: list[dict[str, Any]], selected: list[dict[str, Any]], settings: dict[str, float]) -> dict[str, Any]:
    before = portfolio_exposure(rows, settings)
    removed_long = removed_short = 0.0
    for row in selected:
        side = str(row.get("side") or row.get("positionSide") or "").upper()
        notional = position_notional(row)
        if notional is None or notional <= 0:
            continue
        if side == "LONG": removed_long += notional
        elif side == "SHORT": removed_short += notional
    after = before
    if removed_long:
        after = apply_notional_impact(after, "CLOSE_LONG", removed_long, settings,
                                     seat_count=sum(str(x.get("side") or x.get("positionSide") or "").upper() == "LONG" for x in selected))
    if removed_short:
        after = apply_notional_impact(after, "CLOSE_SHORT", removed_short, settings,
                                     seat_count=sum(str(x.get("side") or x.get("positionSide") or "").upper() == "SHORT" for x in selected))
    b = before.get("hedgeCoveragePercent"); a = after.get("hedgeCoveragePercent")
    protection = "unchanged"; impact = "neutral"; db = da = None
    if b is not None and a is not None:
        if a > b + .01: protection = "increases"
        elif a < b - .01: protection = "decreases"
        db = abs(b - settings["targetPercent"]); da = abs(a - settings["targetPercent"])
        if da + .05 < db: impact = "toward_target"
        elif da > db + .05: impact = "away_from_target"
    return {
        "before": before, "after": after,
        "removedLongExposureUsd": round(removed_long, 8),
        "removedShortExposureUsd": round(removed_short, 8),
        "impactType": impact, "protectionDirection": protection,
        "targetDistanceBefore": round(db, 6) if db is not None else None,
        "targetDistanceAfter": round(da, 6) if da is not None else None,
    }


def profit_preview_with_settings(rows: list[dict[str, Any]], settings: dict[str, float]) -> dict[str, Any]:
    """Keep the existing >=$0.50 selector but use the user's one hedge target everywhere."""
    materialized = list(rows)
    result = profit_preview(materialized)
    result["hedgeConfig"] = dict(settings)
    result["exposure"] = portfolio_exposure(materialized, settings)
    for key in ("long", "short", "all"):
        selected = list((result.get(key) or {}).get("eligible") or [])
        result[key]["impact"] = _dynamic_impact(materialized, selected, settings)
    return result


def install_aster_hedge_recovery_routes(
    app: Any,
    *,
    authenticated_user: Callable[..., Any],
    db: Any,
    user_reference: Callable[[dict[str, Any]], Any],
    aster_strategy2_reference: Callable[[str], Any],
    client_factory: Callable[..., Any],
    acquire_queue_lease: Callable[[Any], str | None],
    release_queue_lease: Callable[[Any, str], None],
    before_order_submit_factory: Callable[[str], Callable[[Any], None]],
) -> None:
    def root(user: dict[str, Any]): return _config_ref(user, user_reference)
    def strategy_mapping(user: dict[str, Any]) -> tuple[dict[str, Any], Strategy2Config]:
        stored = aster_strategy2_reference(str(user["uid"])).get().to_dict() or {}
        raw = stored.get("settings") if isinstance(stored.get("settings"), dict) else stored.get("config") if isinstance(stored.get("config"), dict) else stored
        return raw, Strategy2Config.from_mapping(raw)

    def fallback_margin(raw: dict[str, Any], config: Strategy2Config, side: str) -> float:
        try: return strategy_fallback_start_margin(raw, side)
        except ValueError:
            if config.base_notional > 0 and config.leverage > 0:
                return config.base_notional / config.leverage
            raise

    def state_payload(user: dict[str, Any]) -> dict[str, Any]:
        settings = load_hedge_settings(user, user_reference)
        raw, config = strategy_mapping(user)
        client = client_factory(user, live=False)
        try: rows = client.position_risk()
        except Exception as exc: raise HTTPException(502, "Actuele Aster-posities konden niet betrouwbaar worden gelezen") from exc
        exposure = portfolio_exposure(rows, settings)
        if not exposure["reliable"]: raise HTTPException(409, "Niet alle open Aster-exposure kon betrouwbaar worden geclassificeerd")
        try:
            long_margin = average_start_margin_with_fallback(rows, "LONG", lambda: fallback_margin(raw, config, "LONG"))
            short_margin = average_start_margin_with_fallback(rows, "SHORT", lambda: fallback_margin(raw, config, "SHORT"))
        except ValueError as exc: raise HTTPException(409, str(exc)) from exc
        return {
            "reliable": True, "settings": settings, "exposure": exposure,
            "averageStartMargin": {"LONG": long_margin, "SHORT": short_margin},
            "actions": recommended_actions(exposure["status"]),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }

    def available_usdt(client: Any) -> float:
        rows = client.account_balance()
        usdt = next((x for x in rows if str(x.get("asset", "")).upper() == "USDT"), {})
        return max(0.0, safe_float(usdt.get("availableBalance")))

    def active_keys(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
        return {(str(x.get("symbol", "")).upper(), str(x.get("positionSide", "")).upper()) for x in rows
                if abs(safe_float(x.get("positionAmt"))) > 0 and str(x.get("positionSide", "")).upper() in {"LONG", "SHORT"}}

    def blocked_symbols(raw: dict[str, Any]) -> set[str]:
        values: list[Any] = []
        for key in ("blockedSymbols", "blockedPairs", "blockedCoins", "focusBlockedPairs"):
            candidate = raw.get(key)
            if isinstance(candidate, (list, tuple, set)): values.extend(candidate)
        return {str(x).upper().strip() for x in values if str(x).strip()}

    def best_open_plan(client: Any, symbol_row: dict[str, Any], price: float, margin: float,
                       configured_leverage: int, bulk_brackets: list[dict[str, Any]],
                       existing_rows: list[dict[str, Any]]) -> PairExecutionPlan | None:
        symbol = str(symbol_row.get("symbol", "")).upper()
        bracket_rows = planning_brackets(client, bulk_brackets, symbol, max(1, configured_leverage))
        existing_notional = sum(position_notional(row) or 0.0 for row in existing_rows)
        if existing_rows:
            leverages = {max(1, int(safe_float(row.get("leverage")) or 1)) for row in existing_rows}
            candidates = sorted(leverages, reverse=True) if len(leverages) == 1 else []
        else:
            candidates = sorted({max(1, int(safe_float(row.get("initialLeverage")) or configured_leverage)) for row in bracket_rows}, reverse=True)
            if configured_leverage > 0: candidates = sorted(set(candidates + [configured_leverage]), reverse=True)
        for leverage in candidates:
            try:
                target_notional = margin * leverage
                return plan_pair(symbol_row, bracket_rows, price, target_notional,
                                 accepted_leverage=leverage, existing_contract_notional=existing_notional)
            except Exception:
                continue
        return None

    def refresh_open_execution_plan(user: dict[str, Any], client: Any, current_rows: list[dict[str, Any]],
                                    item: dict[str, Any]) -> PairExecutionPlan:
        """Re-run the same market/order planner immediately before one confirmed OPEN seat."""
        raw, config = strategy_mapping(user)
        symbol = str(item.get("symbol", "")).upper(); side = str(item.get("side", "")).upper()
        requested_margin = safe_float(item.get("requestedMarginUsd")) or safe_float(item.get("plannedMarginUsd"))
        if requested_margin <= 0:
            raise RuntimeError("Bevestigde startmargin van deze stoel ontbreekt")
        available = available_usdt(client)
        if available + 1e-9 < requested_margin:
            raise RuntimeError(f"Onvoldoende beschikbare margin voor de volgende stoel; nodig US$ {requested_margin:.2f}, beschikbaar US$ {available:.2f}")
        exchange_info = client.public_exchange_info()
        prices = {str(x.get("symbol", "")).upper(): safe_float(x.get("price")) for x in client.ticker_prices() if safe_float(x.get("price")) > 0}
        rows_by_symbol = {str(x.get("symbol", "")).upper(): x for x in exchange_info.get("symbols", []) if isinstance(x, dict)}
        market = build_snapshot(exchange_info, client.ticker_24h(), config.universe_top_n,
                                minimum_quote_volume_24h_usdt=config.minimum_quote_volume_24h_usdt)
        symbols = entry_fill_symbols([x.symbol for x in market.selected], rows_by_symbol, prices)
        symbols = [x for x in side_entry_candidates(symbols, active_keys(current_rows), side) if x not in blocked_symbols(raw)]
        if symbol not in symbols:
            raise RuntimeError("De bevestigde coin is niet langer een geldige vrije hedge-stoel; maak een nieuwe preview")
        side_cap = config.maximum_short_positions if side == "SHORT" else config.maximum_long_positions
        current_side_count = sum(1 for row in current_rows if str(row.get("positionSide", "")).upper() == side and abs(safe_float(row.get("positionAmt"))) > 0)
        if side_cap is not None and current_side_count >= int(side_cap):
            raise RuntimeError(f"De actuele {side}-stoelcapaciteit is volledig bezet")
        symbol_row = rows_by_symbol.get(symbol); price = prices.get(symbol, 0)
        if not symbol_row or price <= 0:
            raise RuntimeError("Aster gaf geen betrouwbare actuele contractprijs voor de bevestigde coin")
        bulk_brackets = client.leverage_brackets()
        contract_rows = [row for row in current_rows if str(row.get("symbol", "")).upper() == symbol]
        fresh = best_open_plan(client, symbol_row, price, requested_margin, max(1, config.leverage), bulk_brackets, contract_rows)
        if fresh is None:
            raise RuntimeError("De bevestigde hedge-stoel voldoet niet langer aan de actuele leverage/orderregels")
        if int(fresh.leverage) != int(item.get("leverage", 0)):
            raise RuntimeError("De geldige leverage is gewijzigd sinds bevestiging; maak een nieuwe preview")
        if not math.isclose(float(fresh.notional_per_leg), float(item.get("plannedNotionalUsd", 0)), rel_tol=.015, abs_tol=.05):
            raise RuntimeError("De uitvoerbare notional is materieel gewijzigd sinds bevestiging; maak een nieuwe preview")
        return fresh

    def after_for_items(before: dict[str, Any], action: str, items: list[dict[str, Any]], settings: dict[str, float]) -> dict[str, Any]:
        return apply_notional_impact(before, action, sum(float(x["plannedNotionalUsd"]) for x in items), settings, seat_count=len(items))

    def limit_items_to_step(before: dict[str, Any], action: str, items: list[dict[str, Any]], settings: dict[str, float]) -> list[dict[str, Any]]:
        start_coverage = before.get("hedgeCoveragePercent")
        if not items or start_coverage is None: return items
        target = step_target_percent(start_coverage, settings)
        if target is None: return items
        allowed: list[dict[str, Any]] = []
        for item in items:
            candidate = allowed + [item]
            after = after_for_items(before, action, candidate, settings)
            coverage = after.get("hedgeCoveragePercent")
            if coverage is None or would_exceed_step_target(start_coverage, coverage, target):
                break
            allowed = candidate
            if correction_step_reached(start_coverage, coverage, target):
                break
        return allowed

    def build_preview(user: dict[str, Any], action: str, seat_count: int, *, persist: bool = True) -> dict[str, Any]:
        action = str(action).upper().strip(); settings = load_hedge_settings(user, user_reference)
        raw, config = strategy_mapping(user); client = client_factory(user, live=False)
        try:
            rows = client.position_risk(); before = portfolio_exposure(rows, settings)
            if not before["reliable"]: raise ValueError("Actuele exposure bevat onbetrouwbare open posities")
            validate_recovery_direction(before["status"], action)
            side = "SHORT" if action.endswith("SHORT") else "LONG"
            margin_evidence = average_start_margin_with_fallback(rows, side, lambda: fallback_margin(raw, config, side))
            margin_per_seat = float(margin_evidence["marginUsd"])
            available = available_usdt(client)
            items: list[dict[str, Any]] = []
            margin_capacity = int(available // margin_per_seat) if margin_per_seat > 0 else 0
            max_by_margin = seat_count
            if action.startswith("OPEN"):
                if margin_capacity < seat_count:
                    raise HTTPException(409, f"Onvoldoende beschikbare margin voor {seat_count} stoelen. Maximaal mogelijk met huidige beschikbare margin: {margin_capacity} stoelen")
                if not client.position_mode(): raise ValueError("Aster Hedge Mode staat niet aan")
                exchange_info = client.public_exchange_info(); prices = {str(x.get("symbol", "")).upper(): safe_float(x.get("price")) for x in client.ticker_prices() if safe_float(x.get("price")) > 0}
                rows_by_symbol = {str(x.get("symbol", "")).upper(): x for x in exchange_info.get("symbols", []) if isinstance(x, dict)}
                market = build_snapshot(exchange_info, client.ticker_24h(), config.universe_top_n,
                                        minimum_quote_volume_24h_usdt=config.minimum_quote_volume_24h_usdt)
                symbols = entry_fill_symbols([x.symbol for x in market.selected], rows_by_symbol, prices)
                symbols = [x for x in side_entry_candidates(symbols, active_keys(rows), side) if x not in blocked_symbols(raw)]
                side_cap = config.maximum_short_positions if side == "SHORT" else config.maximum_long_positions
                slot_capacity = max(0, int(side_cap) - int(before[f"{side.lower()}PositionCount"])) if side_cap is not None else len(symbols)
                max_by_margin = min(len(symbols), slot_capacity, margin_capacity)
                bulk_brackets = client.leverage_brackets()
                by_contract: dict[str, list[dict[str, Any]]] = {}
                for row in rows: by_contract.setdefault(str(row.get("symbol", "")).upper(), []).append(row)
                for symbol in symbols:
                    if len(items) >= min(seat_count, max_by_margin): break
                    symbol_row = rows_by_symbol.get(symbol); price = prices.get(symbol, 0)
                    if not symbol_row or price <= 0: continue
                    plan = best_open_plan(client, symbol_row, price, margin_per_seat, max(1, config.leverage), bulk_brackets, by_contract.get(symbol, []))
                    if plan is None: continue
                    items.append({"index": len(items), "symbol": symbol, "side": side,
                                  "quantity": float(plan.quantity), "plannedNotionalUsd": float(plan.notional_per_leg),
                                  "leverage": int(plan.leverage), "requestedMarginUsd": margin_per_seat,
                                  "plannedMarginUsd": float(plan.notional_per_leg) / max(1, plan.leverage)})
                max_by_margin = min(max_by_margin, len(items) if len(items) < seat_count else max_by_margin)
            else:
                candidates = ranked_close_candidates(rows, side)
                max_by_margin = len(candidates)
                for candidate in candidates[:seat_count]:
                    leverage = next((max(1, int(safe_float(row.get("leverage")) or 1)) for row in rows
                                     if str(row.get("symbol", "")).upper() == candidate["symbol"] and str(row.get("positionSide", "")).upper() == side), 1)
                    items.append({"index": len(items), "symbol": candidate["symbol"], "side": side,
                                  "quantity": candidate["quantity"], "plannedNotionalUsd": candidate["notionalUsd"],
                                  "leverage": leverage, "plannedMarginUsd": 0.0,
                                  "unrealizedPnlUsd": candidate["unrealizedPnlUsd"]})
            if len(items) < seat_count:
                raise HTTPException(409, f"Voor deze herstelactie zijn nu maximaal {len(items)} veilige stoel(en) planbaar")
            step_items = limit_items_to_step(before, action, items, settings)
            if len(step_items) < seat_count:
                raise HTTPException(409, f"Je maximale correctie per stap laat nu maximaal {len(step_items)} stoel(en) toe. Verlaag het aantal of pas de stapgrootte aan.")
            items = step_items
            after = after_for_items(before, action, items, settings)
            total_margin = sum(float(x["plannedMarginUsd"]) for x in items)
            total_notional = sum(float(x["plannedNotionalUsd"]) for x in items)
            now = datetime.now(timezone.utc); expires = now + timedelta(seconds=75)
            preview_id = python_secrets.token_urlsafe(18)
            payload = {
                "reliable": True, "previewId": preview_id, "uid": str(user["uid"]), "action": action,
                "seatCount": len(items), "marginPerSeatUsd": margin_per_seat, "marginSource": margin_evidence["source"],
                "totalMarginUsd": round(total_margin, 8), "plannedNotionalUsd": round(total_notional, 8),
                "maximumSeatsByMargin": margin_capacity if action.startswith("OPEN") else max_by_margin, "maximumSeatsPlanable": max_by_margin,
                "before": before, "after": after, "settings": settings,
                "stepTargetPercent": step_target_percent(before.get("hedgeCoveragePercent"), settings),
                "items": items, "generatedAt": now.isoformat(), "expiresAt": expires.isoformat(),
            }
            if persist:
                root(user).collection("previews").document(preview_id).set({**payload, "expiresAt": expires, "createdAt": now})
            return payload
        except HTTPException: raise
        except Exception as exc: raise HTTPException(409, f"Hedge-herstelpreview is veilig gestopt: {str(exc)[:260]}") from exc

    def preview_matches(saved: dict[str, Any], fresh: dict[str, Any]) -> bool:
        if saved.get("action") != fresh.get("action") or int(saved.get("seatCount", 0)) != int(fresh.get("seatCount", -1)): return False
        a = saved.get("items") or []; b = fresh.get("items") or []
        if len(a) != len(b): return False
        for left, right in zip(a, b):
            if str(left.get("symbol")) != str(right.get("symbol")) or str(left.get("side")) != str(right.get("side")): return False
            if not math.isclose(float(left.get("quantity", 0)), float(right.get("quantity", 0)), rel_tol=1e-7, abs_tol=1e-10): return False
            if not math.isclose(float(left.get("plannedNotionalUsd", 0)), float(right.get("plannedNotionalUsd", 0)), rel_tol=.015, abs_tol=.05): return False
        return True

    def clear_active(user: dict[str, Any], action_id: str) -> None:
        doc = root(user).get().to_dict() or {}
        if str(doc.get("activeActionId", "")) == action_id:
            root(user).set({"activeActionId": "", "activeUpdatedAt": datetime.now(timezone.utc)}, merge=True)

    def public_status(user: dict[str, Any], action_id: str, action_data: dict[str, Any] | None = None) -> dict[str, Any]:
        ref = root(user).collection("actions").document(action_id); data = action_data or ref.get().to_dict() or {}
        if not data or str(data.get("uid", "")) != str(user["uid"]): raise HTTPException(404, "Hedge-herstelactie niet gevonden")
        try:
            current_rows = client_factory(user, live=False).position_risk(); current = portfolio_exposure(current_rows, load_hedge_settings(user, user_reference))
        except Exception: current = data.get("lastKnown") or data.get("before")
        completed = int(data.get("completedCount", 0)); seats = int(data.get("seatCount", 0)); status = str(data.get("status", "FAILED"))
        remaining = 0 if status in {"COMPLETED", "STOPPED"} else max(0, seats - completed)
        return {
            "actionId": action_id, "status": status, "action": data.get("action"), "seatCount": seats,
            "completedCount": completed, "activeCount": 1 if data.get("processing") else 0, "remainingCount": remaining,
            "before": data.get("before"), "current": current, "expectedAfter": data.get("expectedAfter"),
            "results": data.get("results") or [], "error": data.get("error", ""),
        }

    @app.get("/v1/me/aster/hedge-recovery/state")
    def get_state(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]: return state_payload(user)

    @app.put("/v1/me/aster/hedge-recovery/settings")
    def put_settings(request: HedgeSettingsRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        try:
            settings = normalize_settings({"targetPercent": request.target_percent, "healthyMinPercent": request.healthy_min_percent,
                                           "healthyMaxPercent": request.healthy_max_percent, "maxCorrectionPercent": request.max_correction_percent})
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        root(user).set({"uid": str(user["uid"]), "settings": settings, "updatedAt": datetime.now(timezone.utc)}, merge=True)
        return state_payload(user)

    @app.post("/v1/me/aster/hedge-recovery/preview")
    def post_preview(request: HedgePreviewRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        return build_preview(user, request.action, request.seat_count)

    @app.get("/v1/me/aster/hedge-recovery/active")
    def get_active(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        data = root(user).get().to_dict() or {}; action_id = str(data.get("activeActionId", ""))
        if not action_id: return {"active": False}
        status = public_status(user, action_id)
        if status["status"] in {"COMPLETED", "STOPPED"}: clear_active(user, action_id); return {"active": False}
        return {"active": True, **status}

    @app.post("/v1/me/aster/hedge-recovery/start")
    def start(request: HedgeStartRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        if not request.confirm: raise HTTPException(422, "Bevestig hedge-herstel expliciet")
        if os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "false").lower() != "true": raise HTTPException(423, "Aster productie-uitvoering staat centraal uit")
        preview_ref = root(user).collection("previews").document(request.preview_id); stored = preview_ref.get().to_dict() or {}
        if not stored or stored.get("uid") != str(user["uid"]): raise HTTPException(409, "De hedge-herstelpreview bestaat niet")
        expires = stored.get("expiresAt"); now = datetime.now(timezone.utc)
        if not isinstance(expires, datetime) or expires <= now: raise HTTPException(409, "De hedge-herstelpreview is verlopen; bereken opnieuw")
        fresh = build_preview(user, str(stored["action"]), int(stored["seatCount"]), persist=False)
        if not preview_matches(stored, fresh): raise HTTPException(409, "Markt/orderplan is gewijzigd. Bekijk eerst een nieuwe hedge-preview.")
        action_id = hashlib.sha256(f"{user['uid']}:{request.idempotency_key}".encode()).hexdigest(); action_ref = root(user).collection("actions").document(action_id)
        transaction = db.transaction()
        @firestore.transactional
        def reserve(txn):
            existing = action_ref.get(transaction=txn)
            if existing.exists: return existing.to_dict() or {}
            config_doc = root(user).get(transaction=txn).to_dict() or {}; active_id = str(config_doc.get("activeActionId", ""))
            if active_id:
                active_ref = root(user).collection("actions").document(active_id); active = active_ref.get(transaction=txn).to_dict() or {}
                if active.get("status") not in {"COMPLETED", "STOPPED"}: raise HTTPException(409, "Er loopt al een hedge-herstelactie")
            data = {"uid": str(user["uid"]), "status": "ACTIVE", "action": fresh["action"], "seatCount": fresh["seatCount"],
                    "completedCount": 0, "nextIndex": 0, "processing": False, "plan": fresh["items"], "before": fresh["before"],
                    "expectedAfter": fresh["after"], "settings": fresh["settings"], "stepTargetPercent": fresh.get("stepTargetPercent"),
                    "results": [], "createdAt": now, "previewId": request.preview_id}
            txn.set(action_ref, data); txn.set(root(user), {"activeActionId": action_id, "activeUpdatedAt": now}, merge=True); return data
        data = reserve(transaction)
        return public_status(user, action_id, data)

    @app.get("/v1/me/aster/hedge-recovery/{action_id}")
    def get_action(action_id: str, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]: return public_status(user, action_id)

    @app.post("/v1/me/aster/hedge-recovery/{action_id}/step")
    def step(action_id: str, request: HedgeStepRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        if not request.confirm: raise HTTPException(422, "Bevestig de hedge-herstelstap expliciet")
        if os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "false").lower() != "true": raise HTTPException(423, "Aster productie-uitvoering staat centraal uit")
        action_ref = root(user).collection("actions").document(action_id); token = python_secrets.token_hex(12); now = datetime.now(timezone.utc); transaction = db.transaction()
        @firestore.transactional
        def claim(txn):
            data = action_ref.get(transaction=txn).to_dict() or {}
            if not data or data.get("uid") != str(user["uid"]): raise HTTPException(404, "Hedge-herstelactie niet gevonden")
            if data.get("status") != "ACTIVE": return data
            if data.get("processing"): raise HTTPException(409, "Deze hedge-herstelstap wordt al verwerkt")
            index = int(data.get("nextIndex", 0)); plan = list(data.get("plan") or [])
            if index >= len(plan):
                txn.set(action_ref, {"status": "COMPLETED", "completedAt": now}, merge=True); return {**data, "status": "COMPLETED"}
            txn.set(action_ref, {"processing": True, "processingToken": token, "processingAt": now}, merge=True); return data
        data = claim(transaction)
        if data.get("status") != "ACTIVE": clear_active(user, action_id); return public_status(user, action_id, data)
        index = int(data.get("nextIndex", 0)); item = list(data.get("plan") or [])[index]; strategy_ref = aster_strategy2_reference(str(user["uid"])); lease = acquire_queue_lease(strategy_ref)
        if not lease:
            action_ref.set({"processing": False, "processingToken": "", "error": "Strategy 2 verwerkt nog een order; herstel wacht veilig.", "updatedAt": datetime.now(timezone.utc)}, merge=True)
            raise HTTPException(409, "Strategy 2 verwerkt nog een order; probeer het zo opnieuw")
        try:
            live = client_factory(user, live=True); current_rows = live.position_risk(); current_settings = load_hedge_settings(user, user_reference)
            current = portfolio_exposure(current_rows, current_settings)
            if current["status"] == "within_target":
                action_ref.set({"status": "COMPLETED", "seatCount": index, "processing": False, "processingToken": "", "lastKnown": current, "completedAt": datetime.now(timezone.utc)}, merge=True)
                clear_active(user, action_id); return public_status(user, action_id)
            try: validate_recovery_direction(current["status"], str(data["action"]))
            except ValueError:
                action_ref.set({"status": "STOPPED", "seatCount": index, "processing": False, "processingToken": "", "lastKnown": current,
                                "error": "De actuele markt/exposure vraagt niet langer om dezelfde herstelrichting.", "stoppedAt": datetime.now(timezone.utc)}, merge=True)
                clear_active(user, action_id); return public_status(user, action_id)
            initial_coverage = (data.get("before") or {}).get("hedgeCoveragePercent")
            current_coverage = current.get("hedgeCoveragePercent"); step_target = data.get("stepTargetPercent")
            if correction_step_reached(initial_coverage, current_coverage, step_target):
                action_ref.set({"status": "COMPLETED", "seatCount": index, "processing": False, "processingToken": "", "lastKnown": current,
                                "completedAt": datetime.now(timezone.utc), "error": "Maximale correctie voor deze herstelstap is bereikt."}, merge=True)
                clear_active(user, action_id); return public_status(user, action_id)
            symbol = str(item["symbol"]).upper(); side = str(item["side"]).upper(); preview_quantity = float(item["quantity"]); action = str(data["action"])
            matching = next((row for row in current_rows if str(row.get("symbol", "")).upper() == symbol and str(row.get("positionSide", "")).upper() == side and abs(safe_float(row.get("positionAmt"))) > 0), None)
            if action.startswith("OPEN") and matching is not None: raise RuntimeError("Doelstoel is sinds de preview al bezet; er wordt niet dubbel geopend")
            if action.startswith("CLOSE"):
                if matching is None: raise RuntimeError("De te sluiten positie bestaat niet meer; er wordt niet opnieuw gesloten")
                live_qty = abs(safe_float(matching.get("positionAmt"))); tolerance = max(1e-10, preview_quantity * 1e-7)
                if abs(live_qty - preview_quantity) > tolerance: raise RuntimeError("De te sluiten positieomvang is gewijzigd; maak een nieuwe preview")
                mark = safe_float(matching.get("markPrice")); leverage = max(1, int(safe_float(matching.get("leverage")) or 1))
                if mark <= 0: raise RuntimeError("Aster gaf geen betrouwbare actuele marktprijs")
                execution_plan = PairExecutionPlan(symbol, Decimal(str(live_qty)), Decimal(str(live_qty * mark)), leverage)
            else:
                execution_plan = refresh_open_execution_plan(user, live, current_rows, item)
            execution_notional = float(execution_plan.notional_per_leg)
            projected = apply_notional_impact(current, action, execution_notional, current_settings, seat_count=1)
            if would_exceed_step_target(initial_coverage, projected.get("hedgeCoveragePercent"), step_target):
                action_ref.set({"status": "COMPLETED", "seatCount": index, "processing": False, "processingToken": "", "lastKnown": current,
                                "completedAt": datetime.now(timezone.utc), "error": "Een extra stoel zou de maximale correctie per stap overschrijden."}, merge=True)
                clear_active(user, action_id); return public_status(user, action_id)
            if action.startswith("CLOSE"):
                result = execute_leg_once(live, execution_plan, side=PositionSide(side), action="CLOSE", id_prefix=f"tmhr-{action_id[:8]}-{index}",
                                          confirm=True, manual_loss_confirmation=True, before_submit=before_order_submit_factory(str(user["uid"])),
                                          fill_poll_attempts=8, fill_poll_delay_seconds=.35)
            else:
                result = execute_leg_once(live, execution_plan, side=PositionSide(side), action="OPEN", id_prefix=f"tmhr-{action_id[:8]}-{index}", confirm=True,
                                          before_submit=before_order_submit_factory(str(user["uid"])), new_position_leverage=int(execution_plan.leverage),
                                          fill_poll_attempts=8, fill_poll_delay_seconds=.35)
            after_rows = live.position_risk(); after = portfolio_exposure(after_rows, current_settings); results = list(data.get("results") or [])
            results.append({"index": index, "symbol": symbol, "side": side, "status": "FILLED", "notionalUsd": execution_notional, "order": result})
            next_index = index + 1; final = next_index >= int(data.get("seatCount", 0)); update = {"completedCount": next_index, "nextIndex": next_index,
                "processing": False, "processingToken": "", "results": results, "lastKnown": after, "updatedAt": datetime.now(timezone.utc), "error": ""}
            if final: update.update({"status": "COMPLETED", "completedAt": datetime.now(timezone.utc)})
            action_ref.set(update, merge=True)
            if final: clear_active(user, action_id)
            return public_status(user, action_id)
        except HTTPException: raise
        except Exception as exc:
            action_ref.set({"status": "FAILED", "processing": False, "processingToken": "", "error": str(exc)[:300], "failedAt": datetime.now(timezone.utc)}, merge=True)
            raise HTTPException(409, f"Hedge-herstel is fail-closed gestopt: {str(exc)[:240]}") from exc
        finally:
            release_queue_lease(strategy_ref, lease)

    @app.post("/v1/me/aster/hedge-recovery/{action_id}/stop")
    def stop(action_id: str, request: HedgeStopRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        if not request.confirm: raise HTTPException(422, "Bevestig stoppen expliciet")
        action_ref = root(user).collection("actions").document(action_id); data = action_ref.get().to_dict() or {}
        if not data or data.get("uid") != str(user["uid"]): raise HTTPException(404, "Hedge-herstelactie niet gevonden")
        if data.get("processing"): raise HTTPException(409, "Er wordt nu één order verwerkt; wacht op de definitieve Aster-status en stop daarna")
        if data.get("status") not in {"ACTIVE", "FAILED"}: return public_status(user, action_id, data)
        try:
            live = client_factory(user, live=True); prefix = f"tmhr-{action_id[:8]}-"
            for order in live.open_orders():
                client_id = str(order.get("clientOrderId", ""))
                if client_id.startswith(prefix):
                    live.cancel_order(str(order.get("symbol", "")), order_id=order.get("orderId"), client_order_id=client_id)
            current = portfolio_exposure(live.position_risk(), load_hedge_settings(user, user_reference))
        except Exception as exc: raise HTTPException(409, f"Stoppen wacht op betrouwbare Aster-reconciliatie: {str(exc)[:220]}") from exc
        completed = int(data.get("completedCount", 0)); action_ref.set({"status": "STOPPED", "seatCount": completed, "lastKnown": current,
            "stoppedAt": datetime.now(timezone.utc), "error": ""}, merge=True); clear_active(user, action_id)
        return public_status(user, action_id)
