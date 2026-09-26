"""Owner-only manual Legacy Hedge Recovery routes.

A confirmed action scales an already HEDGED Auto Hedge pair by one common coin
quantity on LONG and SHORT.  It is deliberately separate from every DCA state
machine: no DCA counter, trigger, history or strategy cycle is touched.

The execution contract is fail-closed:
- exchange truth is re-read before planning and before submission;
- one common exchange-valid quantity is used for both legs;
- client order ids are stable per operation/stage for idempotency;
- an interrupted user-confirmed operation can be resumed without duplicate POSTs;
- partial fills are topped up/reconciled, otherwise only newly-added excess is
  rolled back; legacy quantity is never used for rollback.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
import re
import threading
from typing import Any

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field

import main
from aster_gateway import (
    AsterApiError,
    AsterAutomationConfig,
    AsterOrderIntent,
    AsterValidationError,
    ContractRules,
    PositionSide,
)
from aster_legacy_hedge_scale import (
    DEFAULT_TAKER_FEE_RATE,
    EVENT_TYPE,
    excess_rollback_action,
    leverage_capacity_guidance,
    lower_leverage_candidates,
    parity_repair_action,
    parity_tolerance,
    plan_legacy_hedge_scale,
    stable_scale_intent_id,
)
from aster_position_loss_auto_hedge import (
    _confirmed_fill,
    _query_existing,
    position_quantity,
)
from aster_position_loss_auto_hedge_extension import (
    _audit,
    _client,
    _doc,
    _leg_view,
    _owner_uid,
    _pair_doc,
    _position_map,
)


OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")
TERMINAL_OPERATION_STATUSES = {"SUCCEEDED", "SUCCEEDED_PARTIAL", "FAILED", "ROLLED_BACK"}
RECOVERABLE_OPERATION_STATUSES = {"EXECUTING", "RECONCILING"}
_scale_lock_guard = threading.RLock()
_scale_locks: dict[tuple[str, str], threading.RLock] = {}


class LegacyHedgeScalePreviewRequest(BaseModel):
    marginPerSideUsd: float = Field(gt=0, le=100_000)
    clientBuild: str = Field(default="", max_length=32)


class LegacyHedgeScaleExecuteRequest(LegacyHedgeScalePreviewRequest):
    operationId: str = Field(min_length=8, max_length=64)
    confirm: bool = False


def _operation_collection(uid: str):
    return _doc(uid).collection("legacyScaleOperations")


def _operation_doc(uid: str, operation_id: str):
    return _operation_collection(uid).document(str(operation_id))


def _pair_lock(uid: str, symbol: str) -> threading.RLock:
    key = (str(uid), str(symbol).upper())
    with _scale_lock_guard:
        lock = _scale_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _scale_locks[key] = lock
        return lock


def _claim_persisted_pair_lock(uid: str, symbol: str, operation_id: str) -> bool:
    """Fence the same pair across Cloud Run instances; same operation may resume."""
    ref = _pair_doc(uid, symbol)
    transaction = main.db.transaction()

    @main.firestore.transactional
    def claim(txn):
        state = ref.get(transaction=txn).to_dict() or {}
        lock = state.get("legacyScaleLock") if isinstance(state.get("legacyScaleLock"), dict) else {}
        active = bool(lock.get("active"))
        current_id = str(lock.get("operationId") or "")
        if active and current_id and current_id != operation_id:
            return False
        now = datetime.now(timezone.utc)
        txn.set(ref, {
            "legacyScaleLock": {
                "active": True,
                "operationId": operation_id,
                "claimedAt": lock.get("claimedAt") or now,
                "updatedAt": now,
            },
            "updatedAt": now,
        }, merge=True)
        return True

    return bool(claim(transaction))


def _release_persisted_pair_lock(uid: str, symbol: str, operation_id: str, *, reason: str) -> None:
    ref = _pair_doc(uid, symbol)
    transaction = main.db.transaction()

    @main.firestore.transactional
    def release(txn):
        state = ref.get(transaction=txn).to_dict() or {}
        lock = state.get("legacyScaleLock") if isinstance(state.get("legacyScaleLock"), dict) else {}
        if str(lock.get("operationId") or "") != operation_id:
            return False
        now = datetime.now(timezone.utc)
        txn.set(ref, {
            "legacyScaleLock": {
                "active": False,
                "operationId": operation_id,
                "releasedAt": now,
                "releaseReason": reason,
            },
            "updatedAt": now,
        }, merge=True)
        return True

    release(transaction)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if result == result and result not in {float("inf"), float("-inf")} else default


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol).upper().strip()
    if not re.fullmatch(r"^[A-Z0-9]{2,36}USDT$", normalized):
        raise HTTPException(422, "Ongeldig Aster USDT-symbool")
    return normalized


def _fee_rate() -> float:
    value = _number(os.getenv("ASTER_LEGACY_HEDGE_SCALE_TAKER_FEE_RATE", DEFAULT_TAKER_FEE_RATE), -1.0)
    if value < 0 or value > 0.05:
        return DEFAULT_TAKER_FEE_RATE
    return value


def _contract_rules(client: Any, symbol: str) -> ContractRules:
    payload = client.public_exchange_info()
    rows = payload.get("symbols", []) if isinstance(payload, dict) else []
    raw = next(
        (
            row for row in rows
            if isinstance(row, dict) and str(row.get("symbol", "")).upper() == symbol
        ),
        None,
    )
    if raw is None:
        raise HTTPException(409, f"{symbol}: exchange contractregels zijn niet beschikbaar")
    return ContractRules.from_exchange_info(raw)


def _quote_prices(
    client: Any,
    symbol: str,
    long_row: dict[str, Any],
    short_row: dict[str, Any],
) -> tuple[float, float, float, str]:
    long_mark = _number(long_row.get("markPrice"), _number(long_row.get("entryPrice")))
    short_mark = _number(short_row.get("markPrice"), _number(short_row.get("entryPrice")))
    bid = 0.0
    ask = 0.0
    try:
        quote = client.book_ticker(symbol)
        bid = _number(quote.get("bidPrice"))
        ask = _number(quote.get("askPrice"))
    except Exception:
        pass

    valid_book = bid > 0 and ask > 0 and ask >= bid
    if valid_book:
        current_price = (bid + ask) / 2.0
        current_source = "ASTER_BOOK_TICKER_MID"
    else:
        marks = [value for value in (long_mark, short_mark) if value > 0]
        current_price = sum(marks) / len(marks) if marks else 0.0
        current_source = "ASTER_POSITION_RISK_MARK"

    long_price = ask if ask > 0 else (long_mark if long_mark > 0 else current_price)
    short_price = bid if bid > 0 else (short_mark if short_mark > 0 else current_price)
    if long_price <= 0 or short_price <= 0 or current_price <= 0:
        raise HTTPException(409, "Actuele koersdata is niet betrouwbaar beschikbaar; laad de preview opnieuw")
    return long_price, short_price, current_price, current_source


def _position_break_even(row: dict[str, Any]) -> tuple[float, str]:
    explicit = _number(row.get("breakEvenPrice"))
    if explicit > 0:
        return explicit, "ASTER_POSITION_RISK.breakEvenPrice"
    entry = _number(row.get("entryPrice"))
    if entry > 0:
        return entry, "ASTER_POSITION_RISK.entryPrice_FALLBACK"
    raise HTTPException(409, "Break-evenbasis is niet betrouwbaar beschikbaar; laad de preview opnieuw")


def _truth_rows(client: Any, symbol: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    rows = list(client.position_risk(symbol) or [])
    pmap = _position_map(rows)
    long_row = pmap.get((symbol, "LONG"))
    short_row = pmap.get((symbol, "SHORT"))
    if not long_row or not short_row:
        raise HTTPException(409, "Legacy Hedge Recovery vereist een open LONG én SHORT")
    return long_row, short_row, rows


def _opening_capacity(
    client: Any,
    symbol: str,
    long_leverage: int,
    short_leverage: int,
) -> tuple[float, str]:
    leverages = sorted({int(long_leverage), int(short_leverage)})
    if not leverages or any(value < 1 for value in leverages):
        raise AsterValidationError("Actuele Aster leverage is niet betrouwbaar beschikbaar")
    values = [
        client.remaining_openable_notional_value(symbol, leverage)
        for leverage in leverages
    ]
    if not values:
        raise AsterValidationError("Aster openingsruimte is niet betrouwbaar beschikbaar")
    return min(values), "ASTER_REMAINING_OPENABLE_NOTIONAL_VALUE"


def _recommended_lower_leverage(
    *,
    client: Any,
    symbol: str,
    current_leverage: int,
    margin_per_side: float,
    available: float,
    current_long_qty: float,
    current_short_qty: float,
    long_entry: float,
    short_entry: float,
    long_price: float,
    short_price: float,
    rules: ContractRules,
    current_price: float,
    long_break_even: float,
    short_break_even: float,
) -> int | None:
    """Find the highest lower Aster leverage that can fund the requested full budget."""
    try:
        bracket_payload = client.leverage_brackets(symbol)
    except Exception:
        return None
    for candidate in lower_leverage_candidates(bracket_payload, current_leverage):
        try:
            capacity = client.remaining_openable_notional_value(symbol, candidate)
            if _number(capacity, -1.0) <= 0:
                continue
            candidate_plan = plan_legacy_hedge_scale(
                symbol=symbol,
                margin_per_side_usd=margin_per_side,
                available_balance=available,
                current_long_qty=current_long_qty,
                current_short_qty=current_short_qty,
                long_entry=long_entry,
                short_entry=short_entry,
                long_execution_price=long_price,
                short_execution_price=short_price,
                long_leverage=candidate,
                short_leverage=candidate,
                rules=rules,
                taker_fee_rate=_fee_rate(),
                current_price=current_price,
                long_break_even=long_break_even,
                short_break_even=short_break_even,
                remaining_openable_notional_usd=capacity,
            )
            if candidate_plan.get("capacityLimited") is not True:
                return candidate
        except Exception:
            continue
    return None


def _capacity_guidance(
    *,
    client: Any,
    symbol: str,
    current_leverage: int,
    margin_per_side: float,
    available: float,
    current_long_qty: float,
    current_short_qty: float,
    long_entry: float,
    short_entry: float,
    long_price: float,
    short_price: float,
    rules: ContractRules,
    current_price: float,
    long_break_even: float,
    short_break_even: float,
) -> str:
    recommended = _recommended_lower_leverage(
        client=client,
        symbol=symbol,
        current_leverage=current_leverage,
        margin_per_side=margin_per_side,
        available=available,
        current_long_qty=current_long_qty,
        current_short_qty=current_short_qty,
        long_entry=long_entry,
        short_entry=short_entry,
        long_price=long_price,
        short_price=short_price,
        rules=rules,
        current_price=current_price,
        long_break_even=long_break_even,
        short_break_even=short_break_even,
    )
    return leverage_capacity_guidance(
        symbol,
        current_leverage,
        recommended,
        margin_per_side,
    )


def _fresh_plan(
    uid: str,
    symbol: str,
    margin_per_side: float,
    *,
    live_client: bool,
    require_clean_orders: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], Any, ContractRules]:
    pair = _pair_doc(uid, symbol).get().to_dict() or {}
    if str(pair.get("status", "")).upper() != "HEDGED":
        raise HTTPException(409, "Hedge-lock vergroten is alleen beschikbaar voor een volledig HEDGED pair")
    persisted_lock = pair.get("legacyScaleLock") if isinstance(pair.get("legacyScaleLock"), dict) else {}
    if bool(persisted_lock.get("active")):
        raise HTTPException(
            409,
            "Voor dit pair wordt al een bevestigde Legacy Hedge Recovery uitgevoerd of gereconcileerd",
        )

    client = _client(uid, live=live_client)
    try:
        if not bool(client.position_mode()):
            raise HTTPException(409, "Aster Hedge Mode staat niet aan")
        long_row, short_row, _ = _truth_rows(client, symbol)
        open_orders = list(client.open_orders(symbol) or [])
        if require_clean_orders and open_orders:
            raise HTTPException(409, "Er staat al een open Aster-order op dit pair; wacht tot die is afgerond")
        account = client.account_information() or {}
        available = _number(account.get("availableBalance"), -1.0)
        rules = _contract_rules(client, symbol)
        long_price, short_price, current_price, current_price_source = _quote_prices(
            client, symbol, long_row, short_row,
        )
        long_break_even, long_break_even_source = _position_break_even(long_row)
        short_break_even, short_break_even_source = _position_break_even(short_row)
        long_leverage = int(_number(long_row.get("leverage")))
        short_leverage = int(_number(short_row.get("leverage")))
        remaining_capacity, capacity_source = _opening_capacity(
            client, symbol, long_leverage, short_leverage,
        )
        if remaining_capacity <= 0:
            current_leverage = min(long_leverage, short_leverage)
            raise HTTPException(
                409,
                _capacity_guidance(
                    client=client,
                    symbol=symbol,
                    current_leverage=current_leverage,
                    margin_per_side=margin_per_side,
                    available=available,
                    current_long_qty=position_quantity(long_row),
                    current_short_qty=position_quantity(short_row),
                    long_entry=_number(long_row.get("entryPrice")),
                    short_entry=_number(short_row.get("entryPrice")),
                    long_price=long_price,
                    short_price=short_price,
                    rules=rules,
                    current_price=current_price,
                    long_break_even=long_break_even,
                    short_break_even=short_break_even,
                ),
            )
        plan = plan_legacy_hedge_scale(
            symbol=symbol,
            margin_per_side_usd=margin_per_side,
            available_balance=available,
            current_long_qty=position_quantity(long_row),
            current_short_qty=position_quantity(short_row),
            long_entry=_number(long_row.get("entryPrice")),
            short_entry=_number(short_row.get("entryPrice")),
            long_execution_price=long_price,
            short_execution_price=short_price,
            long_leverage=long_leverage,
            short_leverage=short_leverage,
            rules=rules,
            taker_fee_rate=_fee_rate(),
            current_price=current_price,
            long_break_even=long_break_even,
            short_break_even=short_break_even,
            remaining_openable_notional_usd=remaining_capacity,
        )
    except HTTPException:
        raise
    except (AsterApiError, AsterValidationError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc

    plan.update({
        "availableSource": "ASTER_ACCOUNT_INFORMATION.availableBalance",
        "priceSource": current_price_source,
        "executionPriceSource": "ASTER_BOOK_TICKER_BID_ASK_WITH_POSITION_MARK_FALLBACK",
        "longBreakEvenSource": long_break_even_source,
        "shortBreakEvenSource": short_break_even_source,
        "openingCapacitySource": capacity_source,
        "estimated": True,
        "dataFresh": True,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "pairCycleId": str(pair.get("generationId", "")),
        "pairStatus": "HEDGED",
        "ownerOnly": True,
    })
    return plan, pair, client, rules


def _submit_or_recover(
    *,
    client: Any,
    uid: str,
    symbol: str,
    operation_id: str,
    side: str,
    stage: str,
    quantity: float,
    action: str,
) -> dict[str, Any]:
    if quantity <= 0:
        raise RuntimeError("Orderquantity moet positief zijn")
    intent_id = stable_scale_intent_id(uid, symbol, operation_id, side, stage, quantity)
    existing = _query_existing(client, symbol, intent_id)
    submitted_now = existing is None
    if existing is not None:
        result = existing
        recovered = True
    else:
        intent = AsterOrderIntent(
            intent_id=intent_id,
            symbol=symbol,
            position_side=PositionSide(str(side).upper()),
            quantity=Decimal(str(quantity)),
            action="OPEN" if str(action).upper() == "OPEN" else "CLOSE",
        )
        result, recovered = client.submit_order_once(
            intent,
            config=AsterAutomationConfig(enabled=True, mode="live"),
            confirm=True,
            hedge_mode_confirmed=True,
            risk_approved=True,
        )
    confirmed = _confirmed_fill(client, symbol, intent_id, result)
    filled = abs(_number(confirmed.get("executedQty", confirmed.get("origQty", quantity))))
    return {
        "side": str(side).upper(),
        "stage": stage,
        "action": str(action).upper(),
        "requestedQty": float(quantity),
        "filledQty": filled,
        "status": str(confirmed.get("status", "")),
        "exchangeOrderId": confirmed.get("orderId"),
        "clientOrderId": intent_id,
        "submittedNow": submitted_now,
        "recovered": bool(recovered),
    }


def _current_pair_quantities(client: Any, symbol: str) -> tuple[float, float, dict[str, Any], dict[str, Any]]:
    long_row, short_row, _ = _truth_rows(client, symbol)
    return (
        position_quantity(long_row),
        position_quantity(short_row),
        long_row,
        short_row,
    )


def _validated_market_delta(rules: ContractRules, quantity: float, price: float) -> float:
    value = rules.market_quantity(Decimal(str(quantity)), Decimal(str(price)))
    return float(value)


def _actual_fees(client: Any, symbol: str, fills: list[dict[str, Any]], fallback: float) -> tuple[float, str]:
    ids = {str(row.get("exchangeOrderId")) for row in fills if row.get("exchangeOrderId") is not None}
    if not ids:
        return fallback, "ESTIMATE"
    try:
        trades = list(client.user_trades(symbol, limit=100) or [])
        selected = [
            row for row in trades
            if isinstance(row, dict) and str(row.get("orderId")) in ids
        ]
        if selected:
            value = sum(abs(_number(row.get("commission"))) for row in selected)
            return value, "ASTER_USER_TRADES"
    except Exception:
        pass
    return fallback, "ESTIMATE"


def _update_pair_after_scale(
    *,
    uid: str,
    symbol: str,
    operation_id: str,
    pair_before: dict[str, Any],
    pre_long_qty: float,
    pre_short_qty: float,
    current_long_qty: float,
    current_short_qty: float,
    long_row: dict[str, Any],
    short_row: dict[str, Any],
    fills: list[dict[str, Any]],
) -> dict[str, Any]:
    protected_side = str(pair_before.get("protectedSide", "")).upper()
    hedge_side = str(pair_before.get("hedgeSide", "")).upper()
    if protected_side not in {"LONG", "SHORT"} or hedge_side not in {"LONG", "SHORT"}:
        raise RuntimeError("Auto Hedge pair mist protectedSide/hedgeSide metadata")
    current_protected = current_long_qty if protected_side == "LONG" else current_short_qty
    current_hedge = current_long_qty if hedge_side == "LONG" else current_short_qty
    common_added = max(0.0, min(current_long_qty - pre_long_qty, current_short_qty - pre_short_qty))

    pair_live = _pair_doc(uid, symbol).get().to_dict() or pair_before
    operation_ids = [str(x) for x in pair_live.get("legacyScaleOperationIds", []) if str(x)]
    already_applied = operation_id in operation_ids
    reserved = max(0.0, _number(pair_live.get("reservedHedgeQty")))
    auto_added = max(0.0, _number(pair_live.get("autoHedgeAddedQty")))
    legacy_added = max(0.0, _number(pair_live.get("legacyScaleAddedQty")))
    if not already_applied:
        reserved += common_added
        auto_added += common_added
        legacy_added += common_added
        operation_ids.append(operation_id)
    reserved = min(reserved, current_hedge)

    long_leg = _leg_view(long_row)
    short_leg = _leg_view(short_row)
    protected_leg = long_leg if protected_side == "LONG" else short_leg
    hedge_leg = long_leg if hedge_side == "LONG" else short_leg
    exchange_ids = [str(x) for x in pair_live.get("exchangeOrderIds", []) if str(x)]
    client_ids = [str(x) for x in pair_live.get("clientOrderIds", []) if str(x)]
    for row in fills:
        if row.get("exchangeOrderId") is not None:
            exchange_ids.append(str(row["exchangeOrderId"]))
        if row.get("clientOrderId"):
            client_ids.append(str(row["clientOrderId"]))

    now = datetime.now(timezone.utc)
    update = {
        "status": "HEDGED",
        "currentProtectedQty": current_protected,
        "currentHedgeQty": current_hedge,
        "reservedHedgeQty": reserved,
        "autoHedgeAddedQty": auto_added,
        "legacyScaleAddedQty": legacy_added,
        "normalFreeQty": max(0.0, current_hedge - reserved),
        "protectedLeg": protected_leg,
        "hedgeLeg": hedge_leg,
        "hedgeRatio": (current_hedge / current_protected * 100.0) if current_protected > 0 else None,
        "legacyScaleOperationIds": operation_ids[-50:],
        "exchangeOrderIds": exchange_ids[-100:],
        "clientOrderIds": client_ids[-100:],
        "lastAction": {
            "eventType": EVENT_TYPE,
            "operationId": operation_id,
            "addedQuantity": common_added,
        },
        "lastReason": "LEGACY_HEDGE_SCALE_SUCCEEDED",
        "lastReconciledAt": now,
        "updatedAt": now,
    }
    _pair_doc(uid, symbol).set(update, merge=True)
    return {**pair_live, **update}


def _execute_operation(uid: str, operation_id: str, operation: dict[str, Any]) -> dict[str, Any]:
    symbol = _normalize_symbol(str(operation.get("symbol", "")))
    planned_qty = _number(operation.get("plannedExtraQuantity"))
    pre_long = _number(operation.get("preLongQty"))
    pre_short = _number(operation.get("preShortQty"))
    step = _number(operation.get("marketQuantityStep"))
    if planned_qty <= 0 or pre_long <= 0 or pre_short <= 0 or step <= 0:
        raise RuntimeError("Recovery-operatie mist een geldige opgeslagen execution-plan")

    pair_before = _pair_doc(uid, symbol).get().to_dict() or {}
    client = _client(uid, live=True)
    if not bool(client.position_mode()):
        raise RuntimeError("Aster Hedge Mode staat niet aan")
    rules = _contract_rules(client, symbol)
    fills: list[dict[str, Any]] = []
    tolerance = parity_tolerance(rules)

    current_long, current_short, long_row, short_row = _current_pair_quantities(client, symbol)
    if current_long + tolerance < pre_long or current_short + tolerance < pre_short:
        raise RuntimeError("Legacy basisquantity is tijdens recovery afgenomen; automatische schaalrecovery stopt")

    initial_ids = [
        stable_scale_intent_id(uid, symbol, operation_id, side, "initial", planned_qty)
        for side in ("LONG", "SHORT")
    ]
    initial_exists = any(_query_existing(client, symbol, intent_id) is not None for intent_id in initial_ids)
    no_new_exposure = (
        abs(current_long - pre_long) <= tolerance
        and abs(current_short - pre_short) <= tolerance
    )
    if no_new_exposure and not initial_exists:
        try:
            account = client.account_information() or {}
            available = _number(account.get("availableBalance"), -1.0)
            long_price, short_price, current_price, _ = _quote_prices(
                client, symbol, long_row, short_row,
            )
            long_break_even, _ = _position_break_even(long_row)
            short_break_even, _ = _position_break_even(short_row)
            long_leverage = int(_number(long_row.get("leverage")))
            short_leverage = int(_number(short_row.get("leverage")))
            remaining_capacity, _ = _opening_capacity(
                client, symbol, long_leverage, short_leverage,
            )
            if remaining_capacity <= 0:
                guidance = _capacity_guidance(
                    client=client,
                    symbol=symbol,
                    current_leverage=min(long_leverage, short_leverage),
                    margin_per_side=_number(operation.get("requestedMarginPerSideUsd")),
                    available=available,
                    current_long_qty=current_long,
                    current_short_qty=current_short,
                    long_entry=_number(long_row.get("entryPrice")),
                    short_entry=_number(short_row.get("entryPrice")),
                    long_price=long_price,
                    short_price=short_price,
                    rules=rules,
                    current_price=current_price,
                    long_break_even=long_break_even,
                    short_break_even=short_break_even,
                )
                raise RuntimeError("RECOVERY_REPLAN_REQUIRED: " + guidance)
            fresh = plan_legacy_hedge_scale(
                symbol=symbol,
                margin_per_side_usd=_number(operation.get("requestedMarginPerSideUsd")),
                available_balance=available,
                current_long_qty=current_long,
                current_short_qty=current_short,
                long_entry=_number(long_row.get("entryPrice")),
                short_entry=_number(short_row.get("entryPrice")),
                long_execution_price=long_price,
                short_execution_price=short_price,
                long_leverage=long_leverage,
                short_leverage=short_leverage,
                rules=rules,
                taker_fee_rate=_fee_rate(),
                current_price=current_price,
                long_break_even=long_break_even,
                short_break_even=short_break_even,
                remaining_openable_notional_usd=remaining_capacity,
            )
        except (AsterApiError, AsterValidationError, ValueError, RuntimeError) as exc:
            raise RuntimeError(
                "RECOVERY_REPLAN_REQUIRED: De actuele Aster leverage/openingsruimte laat "
                f"de opgeslagen recovery niet meer veilig toe. {exc}"
            ) from exc
        if _number(fresh.get("extraQuantity")) + tolerance < planned_qty:
            raise RuntimeError(
                "RECOVERY_REPLAN_REQUIRED: De actuele Aster leverage, koers of openingsruimte "
                "vereist een kleinere quantity. Laad de preview opnieuw."
            )

    # Initial intents are replay-safe.  If a process died after LONG, the same
    # LONG client id resolves to the existing order and only the missing SHORT is sent.
    for side in ("LONG", "SHORT"):
        try:
            row = _submit_or_recover(
                client=client,
                uid=uid,
                symbol=symbol,
                operation_id=operation_id,
                side=side,
                stage="initial",
                quantity=planned_qty,
                action="OPEN",
            )
            fills.append(row)
        except Exception as exc:
            current_long, current_short, _, _ = _current_pair_quantities(client, symbol)
            long_added = max(0.0, current_long - pre_long)
            short_added = max(0.0, current_short - pre_short)
            if max(long_added, short_added) <= tolerance:
                raise RuntimeError(f"Geen recovery-quantity toegevoegd: {exc}") from exc
            break

    # One bounded top-up per side attempts to reach the originally quoted common quantity.
    current_long, current_short, long_row, short_row = _current_pair_quantities(client, symbol)
    for side, current, pre, price in (
        ("LONG", current_long, pre_long, _number(long_row.get("markPrice"), _number(long_row.get("entryPrice")))),
        ("SHORT", current_short, pre_short, _number(short_row.get("markPrice"), _number(short_row.get("entryPrice")))),
    ):
        missing = planned_qty - max(0.0, current - pre)
        if missing > tolerance:
            try:
                quantity = _validated_market_delta(rules, missing, price)
                fills.append(_submit_or_recover(
                    client=client,
                    uid=uid,
                    symbol=symbol,
                    operation_id=operation_id,
                    side=side,
                    stage="topup",
                    quantity=quantity,
                    action="OPEN",
                ))
            except Exception:
                pass

    # Reconcile any residual mismatch by opening the missing newly-added side.
    current_long, current_short, long_row, short_row = _current_pair_quantities(client, symbol)
    repair = parity_repair_action(
        pre_long_qty=pre_long,
        pre_short_qty=pre_short,
        current_long_qty=current_long,
        current_short_qty=current_short,
        step=step,
    )
    if repair is not None:
        try:
            target_row = long_row if repair["side"] == "LONG" else short_row
            price = _number(target_row.get("markPrice"), _number(target_row.get("entryPrice")))
            quantity = _validated_market_delta(rules, repair["quantity"], price)
            fills.append(_submit_or_recover(
                client=client,
                uid=uid,
                symbol=symbol,
                operation_id=operation_id,
                side=repair["side"],
                stage="reconcile-open",
                quantity=quantity,
                action="OPEN",
            ))
        except Exception:
            pass

    # If opening the missing side could not restore parity, roll back only the
    # newly-created excess.  Never close quantity that existed before this operation.
    current_long, current_short, long_row, short_row = _current_pair_quantities(client, symbol)
    repair = parity_repair_action(
        pre_long_qty=pre_long,
        pre_short_qty=pre_short,
        current_long_qty=current_long,
        current_short_qty=current_short,
        step=step,
    )
    if repair is not None:
        rollback = excess_rollback_action(
            pre_long_qty=pre_long,
            pre_short_qty=pre_short,
            current_long_qty=current_long,
            current_short_qty=current_short,
            step=step,
        )
        if rollback is not None:
            target_row = long_row if rollback["side"] == "LONG" else short_row
            price = _number(target_row.get("markPrice"), _number(target_row.get("entryPrice")))
            try:
                quantity = _validated_market_delta(rules, rollback["quantity"], price)
                fills.append(_submit_or_recover(
                    client=client,
                    uid=uid,
                    symbol=symbol,
                    operation_id=operation_id,
                    side=rollback["side"],
                    stage="rollback-excess",
                    quantity=quantity,
                    action="CLOSE",
                ))
            except Exception as exc:
                raise RuntimeError(
                    "Partial-fill recovery kon het nieuw toegevoegde excess niet veilig terugdraaien"
                ) from exc

    current_long, current_short, long_row, short_row = _current_pair_quantities(client, symbol)
    if abs(current_long - current_short) > tolerance:
        raise RuntimeError(
            f"Hedge ratio is na reconciliation niet exact 1:1 (LONG {current_long:g}, SHORT {current_short:g})"
        )
    common_added = max(0.0, min(current_long - pre_long, current_short - pre_short))
    if common_added <= tolerance:
        raise RuntimeError("Recovery-operatie eindigde zonder nieuwe gemeenschappelijke quantity")

    updated_pair = _update_pair_after_scale(
        uid=uid,
        symbol=symbol,
        operation_id=operation_id,
        pair_before=pair_before,
        pre_long_qty=pre_long,
        pre_short_qty=pre_short,
        current_long_qty=current_long,
        current_short_qty=current_short,
        long_row=long_row,
        short_row=short_row,
        fills=fills,
    )
    fallback_fee = _number(operation.get("estimatedFeesUsd"))
    actual_fees, fee_source = _actual_fees(client, symbol, fills, fallback_fee)
    completed_fully = common_added + tolerance >= planned_qty
    result = {
        "eventType": EVENT_TYPE,
        "operationId": operation_id,
        "symbol": symbol,
        "status": "SUCCEEDED" if completed_fully else "SUCCEEDED_PARTIAL",
        "completedFully": completed_fully,
        "requestedMarginPerSideUsd": _number(operation.get("requestedMarginPerSideUsd")),
        "plannedExtraQuantity": planned_qty,
        "actualAddedQuantity": common_added,
        "preLongQty": pre_long,
        "preShortQty": pre_short,
        "longQtyAfter": current_long,
        "shortQtyAfter": current_short,
        "longEntryAfter": _number(long_row.get("entryPrice")),
        "shortEntryAfter": _number(short_row.get("entryPrice")),
        "hedgeRatioAfter": 100.0,
        "actualFeesUsd": actual_fees,
        "feesSource": fee_source,
        "fills": fills,
        "pairStatusAfter": str(updated_pair.get("status", "")),
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }
    return result


def _resume_operation(uid: str, operation_id: str) -> dict[str, Any]:
    ref = _operation_doc(uid, operation_id)
    stored = ref.get().to_dict() or {}
    status = str(stored.get("status", "")).upper()
    if status in TERMINAL_OPERATION_STATUSES and isinstance(stored.get("result"), dict):
        return stored["result"]
    if status == "FAILED":
        raise RuntimeError(
            "RECOVERY_REPLAN_REQUIRED: De vorige poging eindigde zonder nieuwe exposure. "
            "Laad een nieuwe preview zodat leverage en Aster openingsruimte opnieuw worden berekend."
        )
    if stored.get("userConfirmed") is not True:
        raise RuntimeError("Recovery-operatie mist expliciete gebruikersbevestiging")
    symbol = _normalize_symbol(str(stored.get("symbol", "")))

    lock = _pair_lock(uid, symbol)
    with lock:
        current = ref.get().to_dict() or stored
        status = str(current.get("status", "")).upper()
        if status in TERMINAL_OPERATION_STATUSES and isinstance(current.get("result"), dict):
            return current["result"]
        if not _claim_persisted_pair_lock(uid, symbol, operation_id):
            raise RuntimeError("Voor dit pair is al een andere Legacy Hedge Recovery actief")
        ref.set({
            "status": "RECONCILING" if status in RECOVERABLE_OPERATION_STATUSES else "EXECUTING",
            "lastAttemptAt": datetime.now(timezone.utc),
        }, merge=True)
        token = main._acquire_aster_account_coordination(
            uid, "LEGACY_HEDGE_SCALE", f"{symbol}:{operation_id}",
        )
        if not token:
            ref.set({
                "status": "RECONCILING",
                "lastError": "ACCOUNT_COORDINATION_BUSY",
                "lastAttemptAt": datetime.now(timezone.utc),
            }, merge=True)
            raise RuntimeError(
                "Recovery is bevestigd en wacht op vrije Aster accountcoördinatie; "
                "dezelfde operation ID wordt veilig hervat"
            )
        try:
            result = _execute_operation(uid, operation_id, current)
            ref.set({
                "status": result["status"],
                "result": result,
                "completedAt": datetime.now(timezone.utc),
                "lastError": "",
            }, merge=True)
            _release_persisted_pair_lock(
                uid, symbol, operation_id, reason=str(result["status"]),
            )
            _audit(uid, {
                "eventType": EVENT_TYPE,
                "operationId": operation_id,
                "symbol": symbol,
                "qtyBefore": {
                    "long": current.get("preLongQty"),
                    "short": current.get("preShortQty"),
                },
                "requestedMarginPerSideUsd": current.get("requestedMarginPerSideUsd"),
                "calculatedExtraQty": current.get("plannedExtraQuantity"),
                "expectedExecutionPrice": {
                    "long": current.get("longExecutionPrice"),
                    "short": current.get("shortExecutionPrice"),
                },
                "longEntryBefore": current.get("longEntryBefore"),
                "shortEntryBefore": current.get("shortEntryBefore"),
                "longEntryAfter": result.get("longEntryAfter"),
                "shortEntryAfter": result.get("shortEntryAfter"),
                "qtyAfter": {
                    "long": result.get("longQtyAfter"),
                    "short": result.get("shortQtyAfter"),
                },
                "hedgeRatioAfter": result.get("hedgeRatioAfter"),
                "estimatedMargin": current.get("estimatedTotalMarginUsd"),
                "fees": result.get("actualFeesUsd"),
                "feesSource": result.get("feesSource"),
                "fills": result.get("fills"),
                "result": result.get("status"),
                "reason": "USER_CONFIRMED_LEGACY_HEDGE_SCALE",
            })
            return result
        except Exception as exc:
            # Determine whether any confirmed/new quantity may remain. If yes (or
            # exchange truth cannot be re-read), keep the persisted pair lock and
            # RECONCILING state so startup recovery resumes the same stable order
            # ids. A clean no-fill failure is terminal and releases the pair.
            next_status = "RECONCILING"
            exposure_changed = True
            try:
                probe = _client(uid, live=False)
                current_long, current_short, _, _ = _current_pair_quantities(probe, symbol)
                pre_long = _number(current.get("preLongQty"))
                pre_short = _number(current.get("preShortQty"))
                step = max(1e-12, _number(current.get("marketQuantityStep")))
                long_added = max(0.0, current_long - pre_long)
                short_added = max(0.0, current_short - pre_short)
                exposure_changed = max(long_added, short_added) >= step / 1000.0
            except Exception:
                exposure_changed = True
            if not exposure_changed:
                next_status = "FAILED"
                _release_persisted_pair_lock(
                    uid, symbol, operation_id, reason="FAILED_NO_NEW_EXPOSURE",
                )
            ref.set({
                "status": next_status,
                "lastError": str(exc)[:1000],
                "failedAt": datetime.now(timezone.utc) if next_status == "FAILED" else None,
                "lastAttemptAt": datetime.now(timezone.utc),
            }, merge=True)
            _audit(uid, {
                "eventType": EVENT_TYPE,
                "operationId": operation_id,
                "symbol": symbol,
                "result": next_status,
                "reason": str(exc)[:500],
            })
            if next_status == "RECONCILING":
                raise RuntimeError(
                    "De bevestigde recovery is nog niet definitief afgerond en blijft veilig in reconciliation; "
                    "dezelfde operation ID wordt hervat. " + str(exc)
                ) from exc
            raise RuntimeError(
                "RECOVERY_REPLAN_REQUIRED: De poging is zonder nieuwe exposure gestopt. "
                "Leverage en Aster openingsruimte worden bij de volgende preview opnieuw gelezen. "
                + str(exc)
            ) from exc
        finally:
            main._release_aster_account_coordination(uid, token)


@main.app.post("/v1/me/aster/position-loss-auto-hedge/pairs/{symbol}/scale/preview")
def preview_legacy_hedge_scale(
    symbol: str,
    request: LegacyHedgeScalePreviewRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    uid = main.require_continuity_owner(user)
    normalized = _normalize_symbol(symbol)
    plan, _, _, _ = _fresh_plan(
        uid,
        normalized,
        float(request.marginPerSideUsd),
        live_client=False,
        require_clean_orders=True,
    )
    response.headers["Cache-Control"] = "no-store"
    return plan


@main.app.post("/v1/me/aster/position-loss-auto-hedge/pairs/{symbol}/scale")
def execute_legacy_hedge_scale(
    symbol: str,
    request: LegacyHedgeScaleExecuteRequest,
    response: Response,
    user: dict[str, Any] = Depends(main.authenticated_user),
) -> dict[str, Any]:
    uid = main.require_continuity_owner(user)
    normalized = _normalize_symbol(symbol)
    operation_id = str(request.operationId).strip()
    if not OPERATION_ID_RE.fullmatch(operation_id):
        raise HTTPException(422, "Ongeldige operation ID voor Legacy Hedge Recovery")
    if request.confirm is not True:
        raise HTTPException(422, "Bevestig handmatig dat beide posities mogen worden verhoogd")

    ref = _operation_doc(uid, operation_id)
    existing = ref.get().to_dict() or {}
    if existing:
        if str(existing.get("symbol", "")).upper() != normalized:
            raise HTTPException(409, "Deze operation ID hoort al bij een ander symbool")
        status = str(existing.get("status", "")).upper()
        if status in TERMINAL_OPERATION_STATUSES and isinstance(existing.get("result"), dict):
            response.headers["Cache-Control"] = "no-store"
            return existing["result"]
        try:
            result = _resume_operation(uid, operation_id)
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc
        response.headers["Cache-Control"] = "no-store"
        return result

    lock = _pair_lock(uid, normalized)
    with lock:
        if ref.get().exists:
            current = ref.get().to_dict() or {}
            if isinstance(current.get("result"), dict):
                return current["result"]
            raise HTTPException(409, "Deze recovery-operatie is al gestart")

        plan, pair, _, rules = _fresh_plan(
            uid,
            normalized,
            float(request.marginPerSideUsd),
            live_client=False,
            require_clean_orders=True,
        )
        if not _claim_persisted_pair_lock(uid, normalized, operation_id):
            raise HTTPException(409, "Voor dit pair is al een andere Legacy Hedge Recovery actief")
        now = datetime.now(timezone.utc)
        operation = {
            "eventType": EVENT_TYPE,
            "operationId": operation_id,
            "symbol": normalized,
            "status": "EXECUTING",
            "userConfirmed": True,
            "clientBuild": str(request.clientBuild or "")[:32],
            "requestedMarginPerSideUsd": plan["requestedMarginPerSideUsd"],
            "plannedExtraQuantity": plan["extraQuantity"],
            "marketQuantityStep": float(rules.market_quantity_step),
            "preLongQty": plan["long"]["currentQuantity"],
            "preShortQty": plan["short"]["currentQuantity"],
            "longEntryBefore": plan["long"]["currentEntry"],
            "shortEntryBefore": plan["short"]["currentEntry"],
            "longExecutionPrice": plan["long"]["executionPrice"],
            "shortExecutionPrice": plan["short"]["executionPrice"],
            "estimatedLongMarginUsd": plan["estimatedLongMarginUsd"],
            "estimatedShortMarginUsd": plan["estimatedShortMarginUsd"],
            "estimatedTotalMarginUsd": plan["estimatedTotalMarginUsd"],
            "estimatedFeesUsd": plan["estimatedFeesUsd"],
            "plannedOpenNotionalUsd": plan.get("plannedOpenNotionalUsd"),
            "remainingOpenableNotionalAtConfirm": plan.get("remainingOpenableNotionalUsd"),
            "capacityLimitedAtConfirm": bool(plan.get("capacityLimited")),
            "longLeverageAtConfirm": plan["long"]["leverage"],
            "shortLeverageAtConfirm": plan["short"]["leverage"],
            "availableAtConfirm": plan["availableBalance"],
            "pairCycleId": str(pair.get("generationId", "")),
            "createdAt": now,
            "lastAttemptAt": now,
        }
        try:
            ref.set(operation)
        except Exception:
            _release_persisted_pair_lock(
                uid, normalized, operation_id, reason="OPERATION_RECORD_WRITE_FAILED",
            )
            raise

    try:
        result = _resume_operation(uid, operation_id)
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return result


def _recover_user_confirmed_operations() -> None:
    """Best-effort startup recovery for a crash between the two user-confirmed legs."""
    try:
        uid = _owner_uid()
        if not uid:
            return
        for snapshot in _operation_collection(uid).stream():
            row = snapshot.to_dict() or {}
            if row.get("userConfirmed") is not True:
                continue
            if str(row.get("status", "")).upper() not in RECOVERABLE_OPERATION_STATUSES:
                continue
            try:
                _resume_operation(uid, snapshot.id)
            except Exception:
                # The operation record and audit already carry the concrete failure.
                continue
    except Exception:
        return


@main.app.on_event("startup")
def recover_interrupted_legacy_hedge_scale() -> None:
    thread = threading.Thread(
        target=_recover_user_confirmed_operations,
        name="legacy-hedge-scale-recovery",
        daemon=True,
    )
    thread.start()
