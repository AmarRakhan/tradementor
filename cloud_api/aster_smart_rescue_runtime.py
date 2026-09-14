from __future__ import annotations

"""Server-side execution gate for Smart Rescue DCA.

This module reuses the existing Multi-BB execution path for leverage, exchange
rules and idempotent order submission. It only decides *when* and *how large*
a Smart Rescue LONG add may be.
"""

from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Any

import aster_multi_bb_core as _core
from aster_execution import execute_leg_once, is_definite_contract_rejection
from aster_gateway import PositionSide
from aster_smart_rescue import advance_state, apply_failure, apply_fill


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def active_keys(raw_state: dict[str, Any]) -> set[str]:
    state = raw_state.get("multiBbPositions") if isinstance(raw_state.get("multiBbPositions"), dict) else {}
    return {
        str(key) for key, row in state.items()
        if isinstance(row, dict) and isinstance(row.get("smartRescue"), dict)
        and str(key).endswith("|LONG")
    }


def _position_map(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in positions:
        qty = abs(_f(row.get("positionAmt")))
        symbol = str(row.get("symbol") or "").upper()
        side = str(row.get("positionSide") or "").upper()
        if qty > 0 and symbol and side in {"LONG", "SHORT"}:
            out[f"{symbol}|{side}"] = row
    return out


def _tp_due(settings: Any, row: dict[str, Any]) -> bool:
    if str(getattr(settings, "take_profit_mode", "PER_TRADE")) != "PER_TRADE":
        return False
    if not bool(getattr(settings, "take_profit_enabled", True)):
        return False
    entry = _f(row.get("entryPrice")); mark = _f(row.get("markPrice"), entry)
    target = entry * (1 + _f(getattr(settings, "long_take_profit_value", getattr(settings, "take_profit", 0.0))))
    return entry > 0 and mark >= target


def run_gate(*, client: Any, ref: Any, raw_state: dict[str, Any], settings: Any,
             uid: str, account: dict[str, Any], positions: list[dict[str, Any]],
             open_orders: list[dict[str, Any]], timestamp_ms: int,
             dry_run: bool = False, order_budget: int | None = None,
             before_order: Any = None) -> dict[str, Any]:
    """Advance Smart Rescue state and execute at most one add per position/event."""
    state = deepcopy(raw_state.get("multiBbPositions") or {})
    configured_enabled = bool(getattr(settings, "smart_rescue_enabled", False))
    existing_keys = active_keys({"multiBbPositions": state})
    # Turning the global toggle OFF only affects new cycles. Existing Smart
    # Rescue cycles keep using the config snapshot stored in their position
    # state until they close, exactly like the normal strategy-cycle contract.
    if not configured_enabled and not existing_keys:
        return {"enabled": False, "handled": False, "ordersSent": 0, "actions": [], "state": state}

    pmap = _position_map(positions)
    order_keys = {(str(x.get("symbol", "")).upper(), str(x.get("positionSide", "")).upper()) for x in open_orders}
    info = client.public_exchange_info()
    info_map = {str(x.get("symbol", "")).upper(): x for x in info.get("symbols", [])}
    available = _f(account.get("availableBalance", account.get("availableMargin")))
    budget = max(0, 15 if order_budget is None else int(order_budget))
    sent = 0
    actions: list[dict[str, Any]] = []
    state_changed = False

    for key in sorted(existing_keys):
        row = pmap.get(key); st = state.get(key)
        if row is None or not isinstance(st, dict):
            continue
        symbol, side = key.rsplit("|", 1)
        if side != "LONG" or _tp_due(settings, row):
            continue
        smart = st.get("smartRescue")
        if not isinstance(smart, dict):
            continue
        mark = _f(row.get("markPrice"), _f(row.get("entryPrice")))
        qty = abs(_f(row.get("positionAmt")))
        leverage = max(1, _i(row.get("leverage"), _i(st.get("leverage"), 1)))
        if mark <= 0 or qty <= 0:
            continue

        # Crash/restart reconciliation: if Aster already shows a larger LONG
        # quantity while a rescue level is still ARMED, the order may have
        # filled after submission but before our state write. Consume that
        # armed level from exchange truth instead of ever submitting it twice.
        previous_qty = abs(_f(st.get("lastKnownQty")))
        previous_entry = _f(st.get("lastKnownEntry"))
        armed_index = _i(smart.get("armedIndex"))
        if (symbol, side) not in order_keys and armed_index > 0 and previous_qty > 0 and qty > previous_qty + 1e-12:
            current_entry = _f(row.get("entryPrice"), previous_entry)
            fill_qty = qty - previous_qty
            fill_price = _core._infer_external_add_fill_price(
                previous_qty=previous_qty, previous_entry=previous_entry,
                new_qty=qty, new_entry=current_entry, fallback=mark,
            )
            actual_margin = max(0.0, fill_price * fill_qty / leverage)
            reconciled = apply_fill(
                smart, level_index=armed_index, fill_price=fill_price,
                fill_qty=fill_qty, actual_margin_usd=actual_margin,
                order_id=None, timestamp_ms=timestamp_ms,
            )
            st = dict(st)
            st.update({
                "dcaCount": _i(st.get("dcaCount")) + 1,
                "lastBotFillPrice": fill_price, "lastDcaFillPrice": fill_price,
                "lastKnownQty": qty, "lastKnownEntry": current_entry,
                "lastBotDcaAtMs": timestamp_ms, "updatedAtMs": timestamp_ms,
                "leverage": leverage, "smartRescue": reconciled,
                "smartRescueReconciledAtMs": timestamp_ms,
            })
            state[key] = st; state_changed = True
            actions.append({
                "kind": "SMART_RESCUE_FILL_RECONCILED", "symbol": symbol,
                "side": side, "level": armed_index, "fillPrice": fill_price,
                "fillQty": fill_qty, "reason": "EXCHANGE_POSITION_INCREASE_AFTER_RESTART",
            })
            continue

        advanced, executable = advance_state(smart, mark_price=mark)
        if advanced != smart:
            st = dict(st); st["smartRescue"] = advanced; state[key] = st
            smart = advanced; state_changed = True
            actions.append({
                "kind": "SMART_RESCUE_STATE", "symbol": symbol, "side": side,
                "decision": smart.get("lastDecision"), "armedIndex": smart.get("armedIndex"),
                "localLow": smart.get("localLow"), "recoveryTriggerPrice": smart.get("recoveryTriggerPrice"),
            })
        if executable is None or sent >= budget or (symbol, side) in order_keys:
            continue

        level_index = _i(executable.get("levelIndex"))
        margin = _f(executable.get("orderMarginUsd"))
        if level_index <= 0 or margin <= 0 or bool(executable.get("amountDisplayCapped")):
            failed = apply_failure(smart, level_index=max(1, level_index), reason="SMART_RESCUE_ORDER_AMOUNT_NOT_EXECUTABLE", timestamp_ms=timestamp_ms, terminal=True)
            st = dict(st); st["smartRescue"] = failed; state[key] = st; state_changed = True
            actions.append({"kind": "SMART_RESCUE_BLOCKED", "symbol": symbol, "level": level_index, "reason": "ORDER_AMOUNT_NOT_EXECUTABLE"})
            continue

        row_info = info_map.get(symbol)
        if row_info is None:
            actions.append({"kind": "SMART_RESCUE_BLOCKED", "symbol": symbol, "level": level_index, "reason": "MARKET_METADATA_UNAVAILABLE"})
            continue
        try:
            plan, tier = _core._plan_add(client, row_info, mark, margin, leverage, qty * mark, settings.minimum_leverage)
        except Exception as exc:
            failed = apply_failure(smart, level_index=level_index, reason=str(exc), timestamp_ms=timestamp_ms)
            st = dict(st); st["smartRescue"] = failed; state[key] = st; state_changed = True
            actions.append({"kind": "SMART_RESCUE_BLOCKED", "symbol": symbol, "level": level_index, "reason": str(exc)})
            continue

        required = _f(tier.get("additionalMarginRequired"), margin)
        if available < required * 1.05:
            failed = apply_failure(smart, level_index=level_index, reason="INSUFFICIENT_AVAILABLE_MARGIN", timestamp_ms=timestamp_ms)
            st = dict(st); st["smartRescue"] = failed; state[key] = st; state_changed = True
            actions.append({"kind": "SMART_RESCUE_MARGIN_WAIT", "symbol": symbol, "level": level_index, "requiredMargin": required})
            continue

        action = {
            "kind": "SMART_RESCUE_DCA", "symbol": symbol, "side": "LONG", "level": level_index,
            "marginUsd": margin, "localLow": executable.get("localLow"),
            "recoveryTriggerPrice": executable.get("recoveryTriggerPrice"),
            "leverage": tier.get("leverage"), "projectedNotional": tier.get("projectedNotional"),
        }
        actions.append(action)
        if dry_run:
            sent += 1; available -= required
            continue

        cycle_id = str(st.get("cycleId") or "cycle")
        try:
            result = execute_leg_once(
                client, plan, side=PositionSide.LONG, action="OPEN",
                id_prefix=f"mbb-smart-rescue-{cycle_id}-{level_index}", confirm=True,
                new_position_leverage=int(tier["leverage"]),
                allow_existing_contract_leverage_change=True,
                before_submit=before_order,
            )
        except Exception as exc:
            failed = apply_failure(smart, level_index=level_index, reason=str(exc), timestamp_ms=timestamp_ms,
                                   terminal=is_definite_contract_rejection(exc))
            st = dict(st); st["smartRescue"] = failed; state[key] = st; state_changed = True
            actions.append({"kind": "SMART_RESCUE_ORDER_FAILED", "symbol": symbol, "level": level_index, "reason": str(exc)})
            if not is_definite_contract_rejection(exc):
                if state_changed:
                    ref.set({"multiBbPositions": state}, merge=True)
                raise
            continue

        fill = result.get("result") or {}
        fill_price = _f(fill.get("avgPrice"), mark)
        fill_qty = abs(_f(fill.get("executedQty"), float(plan.quantity)))
        actual_margin = fill_price * fill_qty / max(1, int(tier["leverage"]))
        new_qty = qty + fill_qty
        old_entry = _f(row.get("entryPrice"))
        new_entry = ((old_entry * qty) + (fill_price * fill_qty)) / new_qty if new_qty > 0 else old_entry
        fill_id = str(fill.get("orderId") or fill.get("clientOrderId") or fill.get("id") or "") or None
        updated_smart = apply_fill(smart, level_index=level_index, fill_price=fill_price, fill_qty=fill_qty,
                                   actual_margin_usd=actual_margin, order_id=fill_id, timestamp_ms=timestamp_ms)
        st = dict(st)
        st.update({
            "dcaCount": _i(st.get("dcaCount")) + 1,
            "lastBotFillPrice": fill_price, "lastDcaFillPrice": fill_price,
            "lastKnownQty": new_qty, "lastKnownEntry": new_entry,
            "lastBotDcaAtMs": timestamp_ms, "updatedAtMs": timestamp_ms,
            "leverage": int(tier["leverage"]), "smartRescue": updated_smart,
        })
        state[key] = st; state_changed = True
        ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                 "lastReason": f"Smart Rescue DCA {level_index} bevestigd op {symbol}"}, merge=True)
        try:
            ref.collection("audit").add({"event": "SMART_RESCUE_DCA", "user": uid, "symbol": symbol,
                "level": level_index, "fillPrice": fill_price, "fillQty": fill_qty,
                "marginUsd": actual_margin, "timestamp": datetime.now(timezone.utc)})
        except Exception:
            pass
        sent += 1; available -= required

    if state_changed and not dry_run and sent == 0:
        ref.set({"multiBbPositions": state}, merge=True)
    return {"enabled": configured_enabled or bool(existing_keys), "configuredEnabled": configured_enabled, "handled": sent > 0, "ordersSent": 0 if dry_run else sent,
            "simulatedOrders": sent if dry_run else 0, "actions": actions, "stateChanged": state_changed, "state": state}
