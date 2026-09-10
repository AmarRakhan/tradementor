"""One-order-per-tick Dynamic Hedge execution overlay for Aster Strategy 2.

The overlay is account-scoped and runs inside Strategy 2's existing scheduler
lease. It never blind-retries a pending order. Risk-adding orders require an
independent raw-Aster verification plus a conservative projected-maintenance
check. Strategy 2 remains responsible for the dominant trading side while this
controller exclusively owns the smaller hedge side.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import math
import os
from typing import Any

from aster_close_guard import CloseEvidence
from aster_cross_risk import cross_account_risk
from aster_dynamic_hedge import DynamicHedgeConfig, assess_dynamic_hedge, dynamic_target_range, robust_hedge_coverage, safety_status
from aster_dynamic_hedge_verify import verify_read_only_projection
from aster_execution import PairExecutionPlan, client_order_id, execute_leg_once, plan_pair
from aster_gateway import AsterOrderIntent, AsterSubmissionUncertain, AsterValidationError, LeverageBracket, PositionSide


def _n(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict) and abs(_n(row.get("positionAmt", row.get("quantity")))) > 1e-12]


def _side(row: dict[str, Any]) -> str:
    return str(row.get("positionSide", row.get("side", ""))).upper().strip()


def _qty(row: dict[str, Any]) -> float:
    return abs(_n(row.get("positionAmt", row.get("quantity"))))


def _mark(row: dict[str, Any]) -> float:
    return _n(row.get("markPrice")) or _n(row.get("entryPrice"))


def _notional(row: dict[str, Any]) -> float:
    direct = _n(row.get("notional"))
    return abs(direct) if direct else _qty(row) * _mark(row)


def _position_map(rows: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    return {
        (str(row.get("symbol", "")).upper(), _side(row)): _qty(row)
        for row in _active(rows)
        if str(row.get("symbol", "")).strip() and _side(row) in {"LONG", "SHORT"}
    }


def validate_single_intent_delta(
    before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]], *,
    symbol: str, side: str, action: str, expected_quantity: float,
) -> dict[str, Any]:
    before = _position_map(before_rows); after = _position_map(after_rows)
    key = (symbol.upper(), side.upper())
    b = before.get(key, 0.0); a = after.get(key, 0.0)
    tolerance = max(1e-9, expected_quantity * 0.02)
    for other in set(before) | set(after):
        if other == key:
            continue
        if abs(after.get(other, 0.0) - before.get(other, 0.0)) > max(1e-9, before.get(other, 0.0) * 1e-9):
            raise RuntimeError(f"Onverwachte gelijktijdige positiewijziging {other[0]} {other[1]}")
    delta = a - b
    if action.upper() == "OPEN":
        if delta < expected_quantity - tolerance:
            raise RuntimeError(f"Aster bevestigt onvoldoende {side}-toename: verwacht {expected_quantity:.12g}, werkelijk {max(0.0, delta):.12g}")
    elif action.upper() == "CLOSE":
        if -delta < expected_quantity - tolerance or a > b + tolerance:
            raise RuntimeError(f"Aster bevestigt de bedoelde {side}-reductie niet")
    else:
        raise ValueError("Onbekende Dynamic Hedge actie")
    return {"symbol": key[0], "side": key[1], "action": action.upper(), "beforeQuantity": b, "afterQuantity": a, "deltaQuantity": delta}


def _bracket_rows(payload: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    for row in payload or []:
        if str(row.get("symbol", "")).upper() == symbol.upper():
            return [item for item in row.get("brackets", []) if isinstance(item, dict)]
    return [row for row in payload or [] if isinstance(row, dict) and "initialLeverage" in row]


def _bracket_for(rows: list[dict[str, Any]], notional: float) -> LeverageBracket | None:
    parsed = []
    for row in rows:
        try: parsed.append(LeverageBracket.from_mapping(row))
        except Exception: continue
    value = Decimal(str(max(0.0, notional)))
    for bracket in sorted(parsed, key=lambda item: item.floor):
        if value >= bracket.floor and (bracket.cap <= 0 or value <= bracket.cap):
            return bracket
    return None


def projected_margin_candidate(
    *, account: dict[str, Any], positions: list[dict[str, Any]], symbol: str,
    add_notional_usd: float, leverage: int, bracket_rows: list[dict[str, Any]],
    fee_rate: float = 0.0005, slippage_rate: float = 0.001,
) -> dict[str, float] | None:
    risk = cross_account_risk(account, positions)
    if not verify_read_only_projection(account, positions, risk)["passed"]:
        return None
    equity = _n(risk.get("equity")); maintenance = _n(risk.get("maintenanceMarginUsd"))
    available = _n(account.get("availableBalance"))
    if equity <= 0 or maintenance < 0 or add_notional_usd <= 0 or leverage <= 0:
        return None
    contract_gross = sum(_notional(row) for row in _active(positions) if str(row.get("symbol", "")).upper() == symbol.upper())
    current_bracket = _bracket_for(bracket_rows, contract_gross) if contract_gross > 0 else None
    projected_contract = contract_gross + add_notional_usd
    projected_bracket = _bracket_for(bracket_rows, projected_contract)
    if projected_bracket is None:
        return None
    current_mmr = float(current_bracket.maintenance_margin_ratio) if current_bracket is not None else 0.0
    projected_mmr = float(projected_bracket.maintenance_margin_ratio)
    if projected_mmr < 0 or not math.isfinite(projected_mmr):
        return None
    # Ignore cumulative tier deductions deliberately: charging the full MMR is
    # conservative. A tier jump is charged to the already-open contract too.
    incremental_maintenance = add_notional_usd * projected_mmr + contract_gross * max(0.0, projected_mmr - current_mmr)
    costs = add_notional_usd * max(0.0, fee_rate + slippage_rate)
    projected_equity = equity - costs
    projected_maintenance = maintenance + incremental_maintenance
    projected_buffer = projected_equity - projected_maintenance
    projected_ratio = projected_equity / projected_maintenance if projected_maintenance > 0 else float("inf")
    required_margin = add_notional_usd / leverage + costs
    if available + 1e-9 < required_margin:
        return None
    return {
        "currentMarginBufferUsd": _n(risk.get("marginBufferUsd")),
        "currentBufferRatio": _n(risk.get("bufferRatio"), float("inf")),
        "projectedMarginBufferUsd": projected_buffer,
        "projectedBufferRatio": projected_ratio,
        "projectedMaintenanceMarginUsd": projected_maintenance,
        "projectedEquity": projected_equity,
        "requiredAvailableMarginUsd": required_margin,
        "incrementalMaintenanceMarginUsd": incremental_maintenance,
        "estimatedOpeningCostsUsd": costs,
    }


def _configured_step_notional(settings: Any, side: str, leverage: int, *, entry: bool) -> float:
    is_short = side == "SHORT"
    if entry:
        margin = _n(getattr(settings, "entry_margin_short_usd" if is_short else "entry_margin_long_usd", 0))
        if str(getattr(settings, "entry_sizing_mode", "margin")).lower() == "notional":
            return _n(getattr(settings, "entry_notional_usd", 0))
    else:
        margin = _n(getattr(settings, "short_dca_margin_usd" if is_short else "long_dca_margin_usd", 0))
    return margin * max(1, leverage)


def _allowed_symbols(settings: Any, desired_side: str, info: dict[str, Any], tickers: list[dict[str, Any]]) -> list[str]:
    if bool(getattr(settings, "manual_symbol_selection_enabled", False)):
        return [str(symbol).upper() for symbol, side in getattr(settings, "manual_symbols", ()) if str(side).upper() == desired_side]
    allowed = {
        str(row.get("symbol", "")).upper()
        for row in info.get("symbols", []) if isinstance(row, dict)
        and str(row.get("status", "TRADING")).upper() == "TRADING"
        and str(row.get("quoteAsset", "USDT")).upper() == "USDT"
    }
    ranked = []
    for row in tickers:
        symbol = str(row.get("symbol", "")).upper()
        volume = _n(row.get("quoteVolume", row.get("quoteVolume24h")))
        if symbol in allowed and volume > 0:
            ranked.append((volume, symbol))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [symbol for _volume, symbol in ranked[:max(1, int(getattr(settings, "universe_top_n", 100)))]]


def _plan_add_candidate(client: Any, settings: Any, positions: list[dict[str, Any]], account: dict[str, Any], desired_side: str, needed: float) -> dict[str, Any] | None:
    info = client.public_exchange_info()
    info_map = {str(row.get("symbol", "")).upper(): row for row in info.get("symbols", []) if isinstance(row, dict)}
    price_map = {str(row.get("symbol", "")).upper(): _n(row.get("price")) for row in client.ticker_prices() if isinstance(row, dict)}
    active = _active(positions)
    side_rows = [row for row in active if _side(row) == desired_side]
    side_rows.sort(key=lambda row: (_notional(row), str(row.get("symbol", ""))))
    candidates: list[tuple[str, dict[str, Any] | None]] = [(str(row.get("symbol", "")).upper(), row) for row in side_rows]
    active_symbols = {str(row.get("symbol", "")).upper() for row in active}
    side_count = len(side_rows)
    side_cap = int(getattr(settings, "short_slots" if desired_side == "SHORT" else "long_slots", 0) or 0)
    if side_cap <= 0 or side_count < side_cap:
        for symbol in _allowed_symbols(settings, desired_side, info, client.ticker_24h()):
            if symbol not in active_symbols:
                candidates.append((symbol, None))
    fee_rate = _n(os.getenv("ASTER_DYNAMIC_HEDGE_TAKER_FEE_RATE", "0.0005"), 0.0005)
    slippage = _n(os.getenv("ASTER_DYNAMIC_HEDGE_SLIPPAGE_RATE", "0.001"), 0.001)
    for symbol, existing in candidates:
        market = info_map.get(symbol)
        price = _mark(existing) if existing is not None else price_map.get(symbol, 0.0)
        if market is None or price <= 0:
            continue
        if existing is not None:
            leverage = max(1, int(_n(existing.get("leverage"), 1)))
        else:
            leverage = 0
        try:
            raw_brackets = client.leverage_brackets(symbol)
            brackets = _bracket_rows(raw_brackets, symbol)
        except Exception:
            continue
        levels = sorted({int(_n(row.get("initialLeverage"))) for row in brackets if int(_n(row.get("initialLeverage"))) > 0}, reverse=True)
        if existing is None:
            minimum = max(1, int(getattr(settings, "minimum_leverage", 1)))
            levels = [value for value in levels if value >= minimum]
            if not levels:
                continue
        else:
            levels = [leverage]
        for leverage in levels:
            configured_step = _configured_step_notional(settings, desired_side, leverage, entry=existing is None)
            requested = min(needed, configured_step)
            if requested <= 0:
                continue
            contract_notional = sum(_notional(row) for row in active if str(row.get("symbol", "")).upper() == symbol)
            try:
                plan = plan_pair(market, brackets, price, requested, accepted_leverage=leverage, existing_contract_notional=contract_notional)
            except Exception:
                continue
            projected = projected_margin_candidate(
                account=account, positions=positions, symbol=symbol,
                add_notional_usd=float(plan.notional_per_leg), leverage=leverage,
                bracket_rows=brackets, fee_rate=fee_rate, slippage_rate=slippage,
            )
            if projected is None:
                continue
            return {"symbol": symbol, "side": desired_side, "plan": plan, "projected": projected, "existing": existing is not None}
    return None


def _close_evidence(client: Any, uid: str, row: dict[str, Any], reason: str) -> CloseEvidence:
    symbol = str(row.get("symbol", "")).upper(); side = _side(row); qty = _qty(row); mark = _mark(row); entry = _n(row.get("entryPrice"))
    fills = client.user_trades(symbol, limit=1000)
    income = client.income_history(symbol=symbol, limit=1000)
    entry_fees = sum(abs(_n(item.get("commission"))) for item in fills if isinstance(item, dict))
    funding = sum(_n(item.get("income")) for item in income if isinstance(item, dict) and str(item.get("incomeType", "")).upper() == "FUNDING_FEE")
    gross = (mark - entry) * qty if side == "LONG" else (entry - mark) * qty
    notional = mark * qty
    return CloseEvidence(
        uid, symbol, side, "dynamic_hedge", reason, qty, entry, mark, gross,
        entry_fees, notional * 0.0005, funding, notional * 0.0005,
        ownership_reliable=True, fills_reliable=True, prices_reliable=True, costs_reliable=True,
    )


def _plan_profitable_reduction(client: Any, uid: str, positions: list[dict[str, Any]], side: str, reason: str, *, maximum_notional_usd: float | None = None) -> dict[str, Any] | None:
    candidates = [row for row in _active(positions) if _side(row) == side and _n(row.get("unRealizedProfit", row.get("unrealizedPnl"))) > 0]
    candidates.sort(key=lambda row: (_notional(row), -_n(row.get("unRealizedProfit", row.get("unrealizedPnl"))), str(row.get("symbol", ""))))
    for row in candidates:
        row_notional=_notional(row)
        if maximum_notional_usd is not None and row_notional > max(0.0, float(maximum_notional_usd)) * 1.001:
            continue
        try:
            evidence = _close_evidence(client, uid, row, reason)
        except Exception:
            continue
        if evidence.expected_net <= max(0.01, evidence.minimum_positive_buffer or 0.0):
            continue
        qty = _qty(row); mark = _mark(row)
        if qty <= 0 or mark <= 0:
            continue
        plan = PairExecutionPlan(str(row.get("symbol", "")).upper(), Decimal(str(qty)), Decimal(str(qty * mark)), max(1, int(_n(row.get("leverage"), 1))))
        return {"symbol": plan.symbol, "side": side, "plan": plan, "evidence": evidence}
    return None


def _fingerprint_quantities(rows: list[dict[str, Any]]) -> str:
    parts = [f"{symbol}:{side}:{qty:.12g}" for (symbol, side), qty in sorted(_position_map(rows).items())]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _pending_result(control_ref: Any, client: Any, positions: list[dict[str, Any]]) -> dict[str, Any] | None:
    stored = control_ref.get().to_dict() or {}
    pending = stored.get("pendingIntent") if isinstance(stored.get("pendingIntent"), dict) else {}
    if not pending:
        return None
    symbol = str(pending.get("symbol", "")).upper(); side = str(pending.get("side", "")).upper(); action = str(pending.get("action", "")).upper()
    before_qty = _n(pending.get("beforeQuantity")); quantity = _n(pending.get("quantity")); intent_id = str(pending.get("clientOrderId", ""))
    current = _position_map(positions).get((symbol, side), 0.0)
    completed = (action == "OPEN" and current >= before_qty + quantity * 0.98) or (action == "CLOSE" and current <= max(0.0, before_qty - quantity * 0.98))
    if completed:
        now = _now(); control_ref.set({"pendingIntent": {}, "ownershipState": "ADOPTING", "stableReads": 0, "positionFingerprint": "", "lastAction": f"{action}_{side}_EXCHANGE_CONFIRMED", "lastActionAt": now, "lastReason": "Eerdere Dynamic Hedge order via exchange-state bevestigd; opnieuw adopteren vóór vervolgactie", "updatedAt": now}, merge=True)
        return {"status": "reconciled", "ordersSent": 0, "action": f"{action}_{side}", "reason": "pending_exchange_confirmed"}
    try:
        order = client.query_order(symbol, intent_id) if intent_id else {}
    except Exception:
        order = {}
    status = str(order.get("status", "")).upper()
    if status in {"CANCELED", "REJECTED", "EXPIRED"}:
        now = _now(); control_ref.set({"pendingIntent": {}, "ownershipState": "ADOPTING", "stableReads": 0, "positionFingerprint": "", "lastAction": "PENDING_ORDER_TERMINAL", "lastActionAt": now, "lastReason": f"Eerdere Dynamic Hedge order eindigde als {status}; eerst exchange-state opnieuw adopteren", "updatedAt": now}, merge=True)
        return {"status": "waiting", "ordersSent": 0, "action": "HOLD", "reason": f"pending_{status.lower()}"}
    return {"status": "uncertain", "ordersSent": 0, "action": "HOLD", "reason": "pending_order_requires_reconciliation"}


def dynamic_strategy_order_guard(control_ref: Any, intent: AsterOrderIntent, account: dict[str, Any], positions: list[dict[str, Any]]) -> None:
    stored = control_ref.get().to_dict() or {}
    if not bool(stored.get("enabled", False)):
        return
    owner = str(stored.get("ownershipState", "ADOPTING")).upper()
    if owner != "DYNAMIC_HEDGE_ACTIVE":
        raise AsterValidationError(f"Dynamic Hedge {owner}: Strategy 2 order gepauzeerd tot reconciliatie klaar is")
    risk = cross_account_risk(account, positions)
    verification = verify_read_only_projection(account, positions, risk)
    if not verification["passed"]:
        raise AsterValidationError("Dynamic Hedge blokkeert Strategy 2: Aster safety-data niet onafhankelijk geverifieerd")
    long_value = _n(risk.get("longNotional")); short_value = _n(risk.get("shortNotional"))
    if abs(long_value - short_value) < 1e-9:
        hedge_side = "BOTH"
    else:
        hedge_side = "SHORT" if long_value > short_value else "LONG"
    side = intent.position_side.value
    if hedge_side == "BOTH" or side == hedge_side:
        raise AsterValidationError(f"Dynamic Hedge bezit de {side}-hedge-exposure; Strategy 2 mag deze leg nu niet wijzigen")
    if intent.action == "OPEN" and safety_status(risk, DynamicHedgeConfig()) != "VEILIG":
        raise AsterValidationError("Dynamic Hedge blokkeert nieuwe dominante exposure zolang de marginstatus niet VEILIG is")


def run_dynamic_hedge_overlay(
    *, client: Any, control_ref: Any, settings: Any, uid: str,
    account: dict[str, Any], positions: list[dict[str, Any]], open_orders: list[dict[str, Any]],
    timestamp_ms: int, dry_run: bool = False, order_budget: int | None = None,
    before_order: Any = None,
) -> dict[str, Any]:
    stored = control_ref.get().to_dict() or {}
    if not bool(stored.get("enabled", False)):
        return {"handled": False, "ordersSent": 0, "status": "off", "action": "MONITORING"}
    owner = str(stored.get("ownershipState", "ADOPTING")).upper()
    # A previously submitted Dynamic Hedge intent is reconciled from exchange
    # truth before ownership-state gating. This permits safe recovery from a
    # 503/restart while still preventing any second POST.
    pending = _pending_result(control_ref, client, positions)
    if pending is not None:
        return {"handled": True, **pending}
    if owner != "DYNAMIC_HEDGE_ACTIVE":
        return {"handled": True, "ordersSent": 0, "status": "waiting", "action": "HOLD", "reason": f"ownership_{owner.lower()}"}
    risk = cross_account_risk(account, positions)
    verification = verify_read_only_projection(account, positions, risk)
    if not verification["passed"]:
        return {"handled": True, "ordersSent": 0, "status": "data-hold", "action": "HOLD", "reason": "read_only_verification_failed"}
    if open_orders:
        return {"handled": True, "ordersSent": 0, "status": "waiting", "action": "HOLD", "reason": "open_order_reconciliation"}
    policy = DynamicHedgeConfig().validated()
    status = safety_status(risk, policy)
    long_value = _n(risk.get("longNotional")); short_value = _n(risk.get("shortNotional"))
    target = dynamic_target_range(risk, policy)
    coverage = robust_hedge_coverage(long_value, short_value)
    dominant_side = "LONG" if long_value > short_value else "SHORT" if short_value > long_value else "FLAT"
    desired_side = "SHORT" if dominant_side == "LONG" else "LONG" if dominant_side == "SHORT" else ""
    action: dict[str, Any] | None = None
    reason = "HEDGE_STABLE"

    if status == "KRITIEK":
        reduction_side = dominant_side if dominant_side in {"LONG", "SHORT"} else ""
        if reduction_side:
            action = _plan_profitable_reduction(client, uid, positions, reduction_side, "CRITICAL_MARGIN_GROSS_REDUCTION")
        reason = "CRITICAL_MARGIN_REDUCE_GROSS"
    elif coverage is not None and target and coverage > target[1] + policy.target_hysteresis_pct:
        hedge_side = "SHORT" if dominant_side == "LONG" else "LONG" if dominant_side == "SHORT" else ""
        if hedge_side:
            dominant_value=max(long_value,short_value); hedge_value=min(long_value,short_value)
            maximum_close=max(0.0,hedge_value-dominant_value*target[1]/100.0)
            action = _plan_profitable_reduction(client, uid, positions, hedge_side, "DYNAMIC_HEDGE_ABOVE_TARGET", maximum_notional_usd=maximum_close)
        reason = "HEDGE_ABOVE_DYNAMIC_TARGET"
    elif coverage is not None and target and coverage < target[0] - policy.target_hysteresis_pct and desired_side:
        dominant_value = max(long_value, short_value)
        hedge_value = min(long_value, short_value)
        needed = max(0.0, dominant_value * target[0] / 100.0 - hedge_value)
        candidate = _plan_add_candidate(client, settings, positions, account, desired_side, needed)
        if candidate is not None:
            assessment = assess_dynamic_hedge(
                enabled=True, ownership_state=owner,
                exposure={"reliable": True, "longExposureUsd": long_value, "shortExposureUsd": short_value},
                risk=risk, candidate=candidate["projected"], config=policy,
            )
            if assessment.get("riskAddingAllowed"):
                action = candidate
            else:
                reason = str(assessment.get("reasonCode", "PROJECTED_MARGIN_BLOCK"))
        else:
            reason = "NO_MARGIN_SAFE_HEDGE_ORDER_AVAILABLE"

    if action is None:
        return {"handled": True, "ordersSent": 0, "status": "waiting", "action": "HOLD", "reason": reason, "safetyStatus": status, "hedgeCoveragePercent": coverage, "targetRange": target}

    plan: PairExecutionPlan = action["plan"]
    side = str(action["side"]).upper()
    is_close = "evidence" in action
    verb = "CLOSE" if is_close else "OPEN"
    if not dry_run and os.getenv("ASTER_DYNAMIC_HEDGE_EXECUTION_ENABLED", "false").lower() != "true":
        return {"handled": True, "ordersSent": 0, "status": "paused", "action": f"{verb}_{side}", "reason": "LIVE_EXECUTION_GATE_CLOSED", "plannedNotionalUsd": float(plan.notional_per_leg)}
    if order_budget is not None and int(order_budget) < 1:
        return {"handled": True, "ordersSent": 0, "status": "waiting", "action": "HOLD", "reason": "ORDER_BUDGET_EXHAUSTED"}
    if dry_run:
        return {"handled": True, "ordersSent": 0, "wouldSendCount": 1, "status": "simulated", "action": f"{verb}_{side}", "symbol": plan.symbol, "plannedQuantity": float(plan.quantity), "plannedNotionalUsd": float(plan.notional_per_leg), "projectedMargin": action.get("projected"), "safetyStatus": status, "targetRange": target}

    before_rows = list(positions)
    before_qty = _position_map(before_rows).get((plan.symbol, side), 0.0)
    id_prefix = f"dh-{hashlib.sha256((uid+_fingerprint_quantities(before_rows)+verb+side+plan.symbol+str(plan.quantity)).encode()).hexdigest()[:16]}"
    intent_id = client_order_id(id_prefix, verb.lower(), side.lower())
    now = _now()
    control_ref.set({
        "pendingIntent": {"clientOrderId": intent_id, "idPrefix": id_prefix, "symbol": plan.symbol, "side": side, "action": verb, "quantity": float(plan.quantity), "notionalUsd": float(plan.notional_per_leg), "beforeQuantity": before_qty, "createdAt": now},
        "lastAction": f"{verb}_{side}_SUBMITTING", "lastActionAt": now,
        "lastReason": reason, "updatedAt": now,
    }, merge=True)
    try:
        result = execute_leg_once(
            client, plan, side=PositionSide(side), action=verb, id_prefix=id_prefix, confirm=True,
            close_evidence=action.get("evidence"),
            before_submit=before_order,
            new_position_leverage=(plan.leverage if verb == "OPEN" else None),
            allow_existing_contract_leverage_change=bool(action.get("existing", False)),
            fill_poll_attempts=3, fill_poll_delay_seconds=0.15,
        )
        after_rows = client.position_risk()
        proof = validate_single_intent_delta(before_rows, after_rows, symbol=plan.symbol, side=side, action=verb, expected_quantity=float(plan.quantity))
        fresh_account = client.account_information()
        fresh_risk = cross_account_risk(fresh_account, after_rows)
        fresh_verify = verify_read_only_projection(fresh_account, after_rows, fresh_risk)
        if not fresh_verify["passed"]:
            raise RuntimeError("Na Dynamic Hedge order wijkt de onafhankelijke Aster safety-verificatie af")
        completed = _now()
        control_ref.set({
            "pendingIntent": {}, "ownershipState": "ADOPTING", "stableReads": 0, "positionFingerprint": "",
            "lastAction": f"{verb}_{side}_CONFIRMED", "lastActionAt": completed,
            "lastReason": "Dynamic Hedge order side-safe door Aster bevestigd; eerst nieuwe account-state adopteren",
            "lastExecutionProof": proof, "lastVerification": fresh_verify, "updatedAt": completed,
        }, merge=True)
        return {"handled": True, "ordersSent": 1, "status": "ok", "action": f"{verb}_{side}", "symbol": plan.symbol, "execution": result, "proof": proof}
    except AsterSubmissionUncertain as exc:
        control_ref.set({"ownershipState": "MANUAL_ACTION_LOCK", "lastAction": "DYNAMIC_ORDER_UNCERTAIN", "lastActionAt": _now(), "lastReason": str(exc)[:500], "updatedAt": _now()}, merge=True)
        return {"handled": True, "ordersSent": 0, "status": "uncertain", "action": "HOLD", "reason": str(exc)}
    except Exception as exc:
        # Pending intent deliberately remains when submit/fill outcome may be ambiguous.
        control_ref.set({"ownershipState": "MANUAL_ACTION_LOCK", "lastAction": "DYNAMIC_ORDER_FAIL_CLOSED", "lastActionAt": _now(), "lastReason": str(exc)[:500], "updatedAt": _now()}, merge=True)
        return {"handled": True, "ordersSent": 0, "status": "data-hold", "action": "HOLD", "reason": str(exc)}
