"""Strategy-2 Focus trailing DCA / temporary hedge state-machine.

This is the authoritative live engine for Focus 2.0 simple mode.

Contract:
- every new v6 cycle starts with a primary leg plus configurable start hedge;
- a DCA cross adds primary exposure and hedges the configured ratio of the total primary position;
- while the hedge is active, the next DCA stays fixed one configured DCA-step beyond the last confirmed DCA fill;
- the hedge is fully released after the configured recovery from the last confirmed DCA fill;
- each deeper DCA replaces both the next-DCA and hedge-release references;
- after release, trailing resumes immediately from the confirmed release/current price;
- full TP closes the primary only when the hedge is flat, then optionally auto-restarts the complete cycle.

Percent settings in Strategy2Config are stored as decimal ratios (0.003 == 0.30%).
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, Callable
import hashlib
import math
import time

from aster_execution import execute_leg_once
from aster_gateway import PositionSide
from aster_strategy2 import Strategy2Config
from aster_strategy2_focus import dca_notional_sequence
from aster_strategy2_focus_v2 import (
    _audit,
    _fill,
    _notional,
    _plan,
    _resolved_leverage,
    _row,
    _selected_symbol,
    f,
)
from aster_strategy2_runtime import active_position_map, owned_from_mapping, owned_to_mapping
from aster_strategy2_state import OwnedLeg

ROLE_PRIMARY_LONG = "FOCUS_V2_LONG"
ROLE_PRIMARY_SHORT = "FOCUS_V2_SHORT"
ROLE_HEDGE_SHORT = "FOCUS_V2_HEDGE"
ROLE_HEDGE_LONG = "FOCUS_V2_HEDGE_LONG"
DCA_TRAILING = "TRAILING"
DCA_FROZEN = "FIXED_DURING_HEDGE"
HEDGE_OFF = "OFF"
HEDGE_ACTIVE = "ACTIVE"
HEDGE_RELEASE_EXECUTING = "RELEASE_EXECUTING"
HEDGE_STARTING = "START_HEDGE_EXECUTING"


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _ratio(value: Any, default: float, *, maximum: float = 0.25) -> float:
    number = _finite(value, default)
    if number <= 0:
        return default
    return min(maximum, number)


def dca_distance(settings: Strategy2Config) -> float:
    """Current configurable trailing DCA distance as a decimal ratio."""
    return _ratio(getattr(settings, "focus_dca_distance", 0.003), 0.003)


def hedge_ratio(settings: Strategy2Config) -> float:
    """Configured hedge ratio of total primary exposure after each DCA."""
    return min(1.0, _ratio(getattr(settings, "focus_v2_hedge_ratio", 1.0), 1.0, maximum=1.0))



def start_hedge_ratio(settings: Strategy2Config) -> float:
    """Configured hedge ratio opened together with every new v6 cycle."""
    return min(1.0, _ratio(getattr(settings, "focus_v2_start_hedge_ratio", 1.0), 1.0, maximum=1.0))


def _amount_to_notional(settings: Strategy2Config, amount: float, leverage: int) -> float:
    """v6 wizard amounts are real margin USD; legacy configs remain notional until re-saved."""
    value = max(0.0, amount)
    return value * max(1, leverage) if getattr(settings, "focus_v2_amounts_are_margin", False) else value


def take_profit_reached(settings: Strategy2Config, primary_pnl: float, primary_notional: float) -> bool:
    value = max(0.0, _finite(getattr(settings, "focus_v2_take_profit_value", 0.0)))
    if value <= 0 or primary_pnl <= 0:
        return False
    mode = str(getattr(settings, "focus_v2_take_profit_mode", "usdt")).lower()
    if mode == "percent":
        return primary_notional > 0 and primary_pnl / primary_notional >= value
    return primary_pnl >= value


def hedge_release_recovery(settings: Strategy2Config) -> float:
    """Recovery from the last confirmed DCA fill required to fully release the hedge."""
    explicit = getattr(settings, "focus_v2_hedge_release_recovery_pct", None)
    if explicit is not None:
        return _ratio(explicit, 0.0015)
    legacy = getattr(settings, "focus_v2_hedge_release_distance_pct", None)
    if legacy is not None:
        return _ratio(legacy, 0.0015)
    return _ratio(getattr(settings, "focus_v2_recovery_rebound_pct", 0.0015), 0.0015)


def hedge_release_distance(settings: Strategy2Config) -> float:
    """Backward-compatible alias for tests/older callers."""
    return hedge_release_recovery(settings)


def next_dca_from_anchor(anchor: float, side: str, distance: float) -> float:
    if anchor <= 0 or distance <= 0:
        return 0.0
    return anchor * (1.0 - distance) if side.upper() == "LONG" else anchor * (1.0 + distance)


def dca_crossed(mark: float, next_dca: float, side: str) -> bool:
    if mark <= 0 or next_dca <= 0:
        return False
    return mark <= next_dca if side.upper() == "LONG" else mark >= next_dca


def release_price_from_last_dca(last_dca_fill: float, side: str, recovery: float) -> float:
    if last_dca_fill <= 0 or recovery <= 0:
        return 0.0
    return last_dca_fill * (1.0 + recovery) if side.upper() == "LONG" else last_dca_fill * (1.0 - recovery)


def hedge_release_crossed(mark: float, release_price: float, side: str) -> bool:
    if mark <= 0 or release_price <= 0:
        return False
    return mark >= release_price if side.upper() == "LONG" else mark <= release_price


def recovery_from_last_dca(mark: float, last_dca_fill: float, side: str) -> float:
    if mark <= 0 or last_dca_fill <= 0:
        return 0.0
    if side.upper() == "LONG":
        return max(0.0, (mark - last_dca_fill) / last_dca_fill)
    return max(0.0, (last_dca_fill - mark) / last_dca_fill)


def release_distance_from_frozen(mark: float, frozen_dca: float, side: str) -> float:
    """Legacy diagnostic helper only; v5 release no longer uses frozen-next-DCA distance."""
    if mark <= 0 or frozen_dca <= 0:
        return 0.0
    if side.upper() == "LONG":
        return max(0.0, (mark - frozen_dca) / mark)
    return max(0.0, (frozen_dca - mark) / mark)


def _slot_side(settings: Strategy2Config, symbol: str) -> str:
    for raw in settings.focus_slots:
        if not isinstance(raw, dict):
            continue
        pair = str(raw.get("pair", raw.get("symbol", ""))).upper().strip()
        if pair == symbol.upper():
            return "SHORT" if str(raw.get("side", "LONG")).upper() == "SHORT" else "LONG"
    return "LONG"


def _roles(primary_side: str) -> tuple[str, str]:
    if primary_side == "SHORT":
        return ROLE_PRIMARY_SHORT, ROLE_HEDGE_LONG
    return ROLE_PRIMARY_LONG, ROLE_HEDGE_SHORT


def _position_side(side: str) -> PositionSide:
    return PositionSide.SHORT if side.upper() == "SHORT" else PositionSide.LONG


def _opposite(side: str) -> str:
    return "LONG" if side.upper() == "SHORT" else "SHORT"


def _owned(raw: dict[str, Any]) -> list[OwnedLeg]:
    result: list[OwnedLeg] = []
    for row in raw.get("ownedLegs", ()) if isinstance(raw.get("ownedLegs"), list) else ():
        try:
            result.append(owned_from_mapping(row))
        except Exception:
            pass
    return result


def _leg(owned: list[OwnedLeg], role: str) -> OwnedLeg | None:
    return next((x for x in owned if str(x.role).upper() == role), None)


def _upsert_owned(
    owned: list[OwnedLeg], *, settings: Strategy2Config, cycle_id: str, symbol: str,
    role: str, side: str, quantity: float, price: float, client_id: str,
    order_id: str, dca: bool, timestamp_ms: int,
) -> list[OwnedLeg]:
    old = _leg(owned, role)
    if old is None:
        new = OwnedLeg(
            settings.strategy_id, "strategy2", symbol, side, cycle_id, settings.version,
            quantity, price, 1 if dca else 0, role,
            tuple(x for x in (client_id,) if x), tuple(x for x in (order_id,) if x), (),
            timestamp_ms, last_order_at_ms=timestamp_ms,
        )
        return [*owned, new]
    total = old.quantity + quantity
    average = ((old.quantity * old.weighted_entry) + (quantity * price)) / max(total, 1e-12)
    new = replace(
        old, quantity=total, weighted_entry=average,
        dca_count=old.dca_count + (1 if dca else 0),
        intent_ids=tuple(dict.fromkeys((*old.intent_ids, *((client_id,) if client_id else ())))),
        fill_ids=tuple(dict.fromkeys((*old.fill_ids, *((order_id,) if order_id else ())))),
        last_order_at_ms=timestamp_ms,
    )
    return [new if x is old else x for x in owned]


def _reduce_owned(owned: list[OwnedLeg], role: str, quantity: float, timestamp_ms: int) -> list[OwnedLeg]:
    old = _leg(owned, role)
    if old is None:
        return owned
    remaining = max(0.0, old.quantity - quantity)
    if remaining <= 1e-12:
        return [x for x in owned if x is not old]
    new = replace(old, quantity=remaining, last_order_at_ms=timestamp_ms)
    return [new if x is old else x for x in owned]


def _state(raw_state: dict[str, Any], *, symbol: str, primary_side: str) -> dict[str, Any]:
    raw = raw_state.get("focusV2State")
    state = dict(raw) if isinstance(raw, dict) else {}
    state.setdefault("cycleId", "")
    state.setdefault("symbol", symbol)
    state.setdefault("primarySide", primary_side)
    state.setdefault("dcaCount", 0)
    state.setdefault("dcaMode", DCA_TRAILING)
    state.setdefault("hedgeState", HEDGE_OFF)
    state.setdefault("trailingHigh", 0.0)
    state.setdefault("trailingLow", 0.0)
    state.setdefault("nextDcaPrice", 0.0)
    state.setdefault("frozenDcaReference", 0.0)  # legacy v4 field
    state.setdefault("lastDcaFillPrice", 0.0)
    state.setdefault("hedgeReleasePrice", 0.0)
    state.setdefault("hedgeTargetQty", 0.0)
    state.setdefault("hedgeCycleId", "")
    state.setdefault("startHedgePercent", 0.0)
    state.setdefault("hedgeTargetPercent", 0.0)
    state.setdefault("tpMode", "usdt")
    state.setdefault("tpValue", 0.0)
    state.setdefault("autoRestart", False)
    state.setdefault("pausedAfterTp", False)
    state.setdefault("restartPending", False)
    state.setdefault("totalHarvestedProfit", 0.0)
    state.setdefault("lastHarvestProfit", 0.0)
    state.setdefault("lastAction", "IDLE")
    state.setdefault("lastReason", "")
    return state


def _persist(ref: Any, state: dict[str, Any], owned: list[OwnedLeg], **extra: Any) -> None:
    payload: dict[str, Any] = {
        "focusV2State": state,
        "ownedLegs": [owned_to_mapping(x) for x in owned],
        "phase": "FOCUS_V2_LIVE",
    }
    payload.update(extra)
    ref.set(payload, merge=True)


def _prefix(cycle_id: str, cycle_no: int, action: str) -> str:
    digest = hashlib.sha256(f"{cycle_id}|{cycle_no}|{action}".encode()).hexdigest()[:18]
    return f"s2tr-{digest}"[:36]


def _execute_with_precision_retry(
    *, client: Any, symbol: str, mark: float, notional: float, leverage: int,
    side: str, action: str, prefix: str, new_position_leverage: int | None = None,
) -> tuple[float, float, str, str]:
    """Build from current exchange filters and retry once after an Aster -1111.

    `_plan` uses ContractRules.market_quantity, so quantity is quantized to the
    symbol step/min-notional rules. Rebuilding after an explicit -1111 refreshes
    exchangeInfo before the controlled retry.
    """
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            plan = _plan(client, symbol, mark, notional, leverage)
            result = execute_leg_once(
                client, plan, side=_position_side(side), action=action,
                id_prefix=prefix, confirm=True,
                manual_loss_confirmation=(action == "CLOSE"),
                new_position_leverage=(new_position_leverage if action == "OPEN" else None),
            )
            return _fill(result)
        except Exception as exc:
            last_error = exc
            message = str(exc)
            if attempt == 0 and ("-1111" in message or "Precision is over" in message):
                # Force a fresh metadata read before rebuilding the normalized plan.
                client.public_exchange_info()
                continue
            raise
    assert last_error is not None
    raise last_error


def _dca_notional(settings: Strategy2Config, count: int, remaining_budget: float) -> float:
    if settings.focus_dca_amount_mode == "linear":
        amount = settings.focus_dca_notional + settings.focus_dca_increment * count
    else:
        seq = dca_notional_sequence(
            amount=settings.focus_dca_notional,
            multiplier=settings.focus_dca_multiplier,
            count=count + 1,
        )
        amount = seq[-1] if seq else settings.focus_dca_notional
    return max(0.0, min(amount, remaining_budget))


def _long_or_short_pnl(row: dict[str, Any] | None, mark: float, side: str) -> float:
    if not row:
        return 0.0
    reported = _finite(row.get("unRealizedProfit"), float("nan"))
    if math.isfinite(reported):
        return reported
    qty = abs(_finite(row.get("positionAmt")))
    entry = _finite(row.get("entryPrice"))
    if qty <= 0 or entry <= 0:
        return 0.0
    return (mark - entry) * qty if side == "LONG" else (entry - mark) * qty


def _executable_hedge_close_price(client: Any, symbol: str, hedge_side: str, mark: float) -> float:
    """Best executable close proxy: ask to buy back SHORT, bid to sell LONG hedge.

    Fail closed to mark when bookTicker is unavailable; the explicit fee/slippage
    buffers below keep the green gate conservative rather than optimistic.
    """
    try:
        payload = client._public_get(
            f"/fapi/v1/ticker/bookTicker?symbol={symbol.upper()}",
            ttl_seconds=1,
            invalid_message="Aster bookTicker niet beschikbaar voor hedge-release",
        )
        if isinstance(payload, dict):
            key = "askPrice" if hedge_side.upper() == "SHORT" else "bidPrice"
            value = _finite(payload.get(key))
            if value > 0:
                return value
    except Exception:
        pass
    return mark


def expected_net_hedge_close_pnl(
    client: Any, symbol: str, hedge_side: str, hedge_row: dict[str, Any] | None, mark: float,
) -> tuple[float, float, float, float, float]:
    """Expected full round-trip net PnL for the remaining protection hedge."""
    if not hedge_row:
        return 0.0, mark, 0.0, 0.0, 0.0
    qty = abs(_finite(hedge_row.get("positionAmt")))
    entry = _finite(hedge_row.get("entryPrice"))
    if qty <= 0 or entry <= 0 or mark <= 0:
        return 0.0, mark, 0.0, 0.0, 0.0
    close_price = _executable_hedge_close_price(client, symbol, hedge_side, mark)
    gross = (entry - close_price) * qty if hedge_side.upper() == "SHORT" else (close_price - entry) * qty
    # Conservative defaults; the gate requires strictly positive result after a
    # complete estimated round trip, not merely green mark-price PnL.
    fee_rate = 0.0005
    slippage_rate = 0.0002
    fees = (entry + close_price) * qty * fee_rate
    slippage = close_price * qty * slippage_rate
    return gross - fees - slippage, close_price, gross, fees, slippage


def _history(state: dict[str, Any], *, mark: float, dca_ratio: float, release_ratio: float,
             primary_notional: float, hedge_notional: float, primary_pnl: float, hedge_pnl: float) -> dict[str, Any]:
    frozen = _finite(state.get("frozenDcaReference"))
    last_dca = _finite(state.get("lastDcaFillPrice"))
    release_price = _finite(state.get("hedgeReleasePrice"))
    side = str(state.get("primarySide", "LONG")).upper()
    return {
        "cycleId": state.get("cycleId", ""),
        "primarySide": side,
        "livePrice": mark,
        "trailingHigh": _finite(state.get("trailingHigh")),
        "trailingLow": _finite(state.get("trailingLow")),
        "nextDcaPrice": _finite(state.get("nextDcaPrice")),
        "dcaAnchorPrice": _finite(state.get("trailingHigh")) if side == "LONG" else _finite(state.get("trailingLow")),
        "dcaMode": state.get("dcaMode", DCA_TRAILING),
        "frozenDcaReference": frozen,
        "distanceToFrozenDca": release_distance_from_frozen(mark, frozen, side),  # legacy diagnostic
        "lastDcaFillPrice": last_dca,
        "hedgeReleasePrice": release_price,
        "recoverySinceLastDcaPct": recovery_from_last_dca(mark, last_dca, side),
        "dcaDistancePct": dca_ratio,
        "hedgeReleaseRecoveryPct": release_ratio,
        "hedgeTargetQty": _finite(state.get("hedgeTargetQty")),
        "hedgeState": state.get("hedgeState", HEDGE_OFF),
        "dcaCount": int(_finite(state.get("dcaCount"))),
        "primaryNotional": primary_notional,
        "hedgeNotional": hedge_notional,
        "longNotional": primary_notional if side == "LONG" else hedge_notional,
        "shortNotional": primary_notional if side == "SHORT" else hedge_notional,
        "primaryPnl": primary_pnl,
        "hedgePnl": hedge_pnl,
        "startHedgePercent": _finite(state.get("startHedgePercent")),
        "hedgeTargetPercent": _finite(state.get("hedgeTargetPercent")),
        "tpMode": str(state.get("tpMode", "usdt")),
        "tpValue": _finite(state.get("tpValue")),
        "autoRestart": bool(state.get("autoRestart", False)),
        "cycleStatus": str(state.get("cycleStatus", state.get("lastAction", "HOLD"))),
        "distanceToDcaPct": ((mark / _finite(state.get("nextDcaPrice")) - 1.0) if _finite(state.get("nextDcaPrice")) > 0 else 0.0),
        "distanceToTp": max(0.0, _finite(state.get("tpValue")) - primary_pnl) if str(state.get("tpMode", "usdt")) == "usdt" else 0.0,
        "stateMachineVersion": 6,
    }


def run_focus_v2_live_step(
    *, client: Any, ref: Any, raw_state: dict[str, Any], settings: Strategy2Config,
    uid: str, account: dict[str, Any], positions: list[dict[str, Any]], timestamp_ms: int,
    dry_run: bool = False, order_budget: int | None = None,
    reserve_order: Callable | None = None, open_orders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one deterministic Focus 2.0 trailing-DCA state-machine step."""
    owned = _owned(raw_state)
    existing_state = raw_state.get("focusV2State") if isinstance(raw_state.get("focusV2State"), dict) else {}
    symbol_hint = str(existing_state.get("symbol", "") or "").upper()
    symbol = _selected_symbol(client, settings, type("S", (), {"symbol": symbol_hint})())
    if not symbol:
        return {"status": "waiting", "action": "FOCUS_V2_NO_PAIR", "ordersSent": 0}

    simple_requested = bool(getattr(settings, "focus_v2_simple_mode_enabled", False))
    primary_side = "LONG" if simple_requested else str(existing_state.get("primarySide", "") or _slot_side(settings, symbol)).upper()
    if primary_side not in {"LONG", "SHORT"}:
        primary_side = "LONG"
    hedge_side = _opposite(primary_side)
    primary_role, hedge_role = _roles(primary_side)
    state = _state(raw_state, symbol=symbol, primary_side=primary_side)

    primary_row = _row(positions, symbol, primary_side)
    hedge_row = _row(positions, symbol, hedge_side)
    mark = _finite((primary_row or hedge_row or {}).get("markPrice"))
    if mark <= 0:
        prices = {
            str(x.get("symbol", "")).upper(): _finite(x.get("price"))
            for x in client.ticker_prices() if isinstance(x, dict)
        }
        mark = prices.get(symbol, 0.0)
    if mark <= 0:
        raise RuntimeError("Focus 2.0 trailing engine heeft geen betrouwbare markprijs")

    if dry_run or settings.mode != "live":
        return {"status": "simulated", "action": "FOCUS_V2_TRAILING_HOLD", "symbol": symbol, "ordersSent": 0}

    dca_ratio = dca_distance(settings)
    release_ratio = hedge_release_recovery(settings)
    simple_flow = bool(getattr(settings, "focus_v2_simple_mode_enabled", False))
    configured_hedge_ratio = 1.0 if simple_flow else hedge_ratio(settings)
    configured_start_hedge_ratio = 1.0 if simple_flow else start_hedge_ratio(settings)
    tp_mode = str(getattr(settings, "focus_v2_take_profit_mode", "usdt")).lower()
    tp_value = max(0.0, _finite(getattr(settings, "focus_v2_take_profit_value", 0.0)))
    state["startHedgePercent"] = configured_start_hedge_ratio
    state["hedgeTargetPercent"] = configured_hedge_ratio
    state["tpMode"] = tp_mode
    state["tpValue"] = tp_value
    state["autoRestart"] = bool(getattr(settings, "focus_v2_auto_restart", True))
    state["configSnapshotVersion"] = int(getattr(settings, "version", 1))
    state["dcaDistancePct"] = dca_ratio
    state["hedgeReleaseRecoveryPct"] = release_ratio
    state["hedgeRatio"] = configured_hedge_ratio
    state["stateMachineVersion"] = 6

    primary_notional = _notional(primary_row)
    hedge_notional = _notional(hedge_row)
    primary_qty = abs(_finite((primary_row or {}).get("positionAmt")))
    hedge_qty = abs(_finite((hedge_row or {}).get("positionAmt")))

    if bool(state.get("pausedAfterTp")) and not bool(getattr(settings, "focus_v2_auto_restart", True)):
        return {"status": "waiting", "action": "FOCUS_V2_TP_CLOSED_PAUSED", "symbol": symbol, "ordersSent": 0}
    if bool(state.get("pausedAfterTp")) and bool(getattr(settings, "focus_v2_auto_restart", True)):
        state["pausedAfterTp"] = False

    # Crash/restart recovery between confirmed primary open and confirmed start hedge.
    if state.get("cycleId") and str(state.get("hedgeState", "")) == HEDGE_STARTING and primary_qty > 0 and hedge_qty <= 1e-12:
        if order_budget is not None and order_budget < 1:
            return {"status": "budget-exhausted", "action": "FOCUS_V2_WAIT_START_HEDGE_RECOVERY", "ordersSent": 0}
        leverage = _resolved_leverage(client, settings, symbol, primary_row)
        target = primary_notional * configured_start_hedge_ratio
        required_margin = target / max(1, leverage)
        if required_margin > _finite(account.get("availableBalance")):
            return {"status": "waiting", "action": "FOCUS_V2_START_HEDGE_MARGIN_BLOCK", "ordersSent": 0}
        prefix = _prefix(str(state["cycleId"]), 0, "START_HEDGE_OPEN")
        hq, hp, hcid, hoid = _execute_with_precision_retry(client=client, symbol=symbol, mark=mark, notional=target,
            leverage=leverage, side=hedge_side, action="OPEN", prefix=prefix, new_position_leverage=leverage)
        owned = _upsert_owned(owned, settings=settings, cycle_id=str(state["cycleId"]), symbol=symbol, role=hedge_role,
            side=hedge_side, quantity=hq, price=hp, client_id=hcid, order_id=hoid, dca=False, timestamp_ms=timestamp_ms)
        state.update({"hedgeState": HEDGE_ACTIVE, "cycleStatus": "TRAILING_HEDGED", "lastHedgeEntryOrderId": hoid,
            "lastAction": "START_HEDGE_RECOVERED", "lastReason": "starthedge na restart exact hervat"})
        _persist(ref, state, owned)
        _audit(ref, "FOCUS_V2_START_HEDGE_RECOVERED", cycleId=state["cycleId"], symbol=symbol, hedgeQty=hq, hedgePrice=hp)
        return {"status": "executed", "action": "FOCUS_V2_START_HEDGE_RECOVERED", "symbol": symbol, "ordersSent": 1}

    # Existing live Focus V2 cycles are reconciled rather than blindly closed.
    if state.get("cycleId"):
        if primary_notional <= 0:
            remaining = [x for x in owned if not str(x.role).upper().startswith("FOCUS_V2")]
            if bool(getattr(settings, "focus_v2_auto_restart", True)):
                _persist(ref, {}, remaining, focusV2LastCycle={"cycleId": state.get("cycleId"), "closedAt": timestamp_ms})
            else:
                paused = {"cycleId": "", "symbol": symbol, "primarySide": primary_side, "pausedAfterTp": True, "autoRestart": False, "cycleStatus": "TP_CLOSED"}
                _persist(ref, paused, remaining, focusV2LastCycle={"cycleId": state.get("cycleId"), "closedAt": timestamp_ms})
            return {"status": "executed", "action": "FOCUS_V2_CYCLE_FLAT", "symbol": symbol, "ordersSent": 0}
        if hedge_qty > 1e-12:
            state["hedgeState"] = HEDGE_ACTIVE
            last_dca = _finite(state.get("lastDcaFillPrice"))
            if int(_finite(state.get("dcaCount"))) == 0 and last_dca <= 0:
                # Start hedge is active, but DCA #1 MUST keep trailing with every new favorable extreme.
                state["dcaMode"] = DCA_TRAILING
                state["hedgeReleasePrice"] = 0.0
                state["hedgeTargetQty"] = primary_qty * configured_start_hedge_ratio
            else:
                if last_dca <= 0:
                    last_dca = _finite(state.get("dcaAnchorPrice"), mark)
                    state["lastDcaFillPrice"] = last_dca
                state["dcaMode"] = DCA_FROZEN
                state["nextDcaPrice"] = next_dca_from_anchor(last_dca, primary_side, dca_ratio)
                state["hedgeReleasePrice"] = 0.0 if simple_flow else release_price_from_last_dca(last_dca, primary_side, release_ratio)
                state["hedgeTargetQty"] = primary_qty * configured_hedge_ratio
            state["frozenDcaReference"] = 0.0
        else:
            state["dcaMode"] = DCA_TRAILING
            state["hedgeState"] = HEDGE_OFF
            state["frozenDcaReference"] = 0.0
            state["hedgeReleasePrice"] = 0.0
            state["hedgeTargetQty"] = 0.0

    # New Focus 2.0 v6 cycle: primary + configurable start hedge, persisted between confirmed legs.
    if not state.get("cycleId"):
        if order_budget is not None and order_budget < 2:
            return {"status": "budget-exhausted", "action": "FOCUS_V2_WAIT_START_HEDGE", "ordersSent": 0}
        focus_owned = [x for x in owned if str(x.role).upper().startswith("FOCUS")]
        if focus_owned or primary_row or hedge_row:
            return {"status": "waiting", "action": "FOCUS_V2_WAIT_FLAT", "reason": "bestaande positie wordt niet blind geadopteerd", "ordersSent": 0}
        leverage = _resolved_leverage(client, settings, symbol)
        start_amount = max(0.0, settings.focus_start_order_notional)
        start_notional = _amount_to_notional(settings, start_amount, leverage)
        if start_notional <= 0:
            raise RuntimeError("Focus 2.0 startbedrag is nul")
        start_hedge_notional = start_notional * configured_start_hedge_ratio
        available = _finite(account.get("availableBalance"))
        required_margin = (start_notional + start_hedge_notional) / max(1, leverage)
        if required_margin > available:
            return {"status": "waiting", "action": "FOCUS_V2_MARGIN_BLOCK", "ordersSent": 0}
        cycle_id = f"focusv2t-{hashlib.sha256(f'{uid}|{symbol}|{primary_side}|{timestamp_ms}'.encode()).hexdigest()[:14]}"
        prefix = _prefix(cycle_id, 0, "PRIMARY_OPEN")
        q, p, cid, oid = _execute_with_precision_retry(
            client=client, symbol=symbol, mark=mark, notional=start_notional, leverage=leverage,
            side=primary_side, action="OPEN", prefix=prefix, new_position_leverage=leverage,
        )
        owned = _upsert_owned(owned, settings=settings, cycle_id=cycle_id, symbol=symbol, role=primary_role,
            side=primary_side, quantity=q, price=p, client_id=cid, order_id=oid, dca=False, timestamp_ms=timestamp_ms)
        # Hedge the CONFIRMED primary fill, not the pre-fill requested notional.
        start_hedge_notional = q * p * configured_start_hedge_ratio
        state.update({
            "cycleId": cycle_id, "symbol": symbol, "primarySide": primary_side, "restartPending": False,
            "cycleStartEquity": _finite(account.get("totalMarginBalance"), _finite(account.get("totalWalletBalance"))),
            "openedAt": timestamp_ms, "originalEntry": p, "weightedEntry": p, "dcaCount": 0,
            "dcaMode": DCA_TRAILING, "hedgeState": HEDGE_STARTING, "cycleStatus": "START_HEDGED",
            "trailingHigh": p if primary_side == "LONG" else 0.0, "trailingLow": p if primary_side == "SHORT" else 0.0,
            "nextDcaPrice": next_dca_from_anchor(p, primary_side, dca_ratio), "lastDcaFillPrice": 0.0,
            "hedgeReleasePrice": 0.0, "hedgeTargetQty": q * configured_start_hedge_ratio,
            "startHedgePercent": configured_start_hedge_ratio, "hedgeTargetPercent": configured_hedge_ratio,
            "tpMode": tp_mode, "tpValue": tp_value, "autoRestart": bool(getattr(settings, "focus_v2_auto_restart", True)),
            "lastPrimaryOrderId": oid, "lastAction": "PRIMARY_OPEN_CONFIRMED", "stateMachineVersion": 6,
        })
        _persist(ref, state, owned)
        try:
            hedge_prefix = _prefix(cycle_id, 0, "START_HEDGE_OPEN")
            hq, hp, hcid, hoid = _execute_with_precision_retry(
                client=client, symbol=symbol, mark=p, notional=start_hedge_notional, leverage=leverage,
                side=hedge_side, action="OPEN", prefix=hedge_prefix, new_position_leverage=leverage,
            )
        except Exception:
            rollback_prefix = _prefix(cycle_id, 0, "START_PRIMARY_ROLLBACK")
            _execute_with_precision_retry(client=client, symbol=symbol, mark=p, notional=q*p, leverage=leverage,
                side=primary_side, action="CLOSE", prefix=rollback_prefix)
            remaining = [x for x in owned if not str(x.role).upper().startswith("FOCUS_V2")]
            _persist(ref, {}, remaining)
            _audit(ref, "FOCUS_V2_START_HEDGE_ROLLBACK", cycleId=cycle_id, symbol=symbol, reason="starthedge kon niet bevestigd worden")
            raise
        owned = _upsert_owned(owned, settings=settings, cycle_id=cycle_id, symbol=symbol, role=hedge_role,
            side=hedge_side, quantity=hq, price=hp, client_id=hcid, order_id=hoid, dca=False, timestamp_ms=timestamp_ms)
        state.update({"hedgeState": HEDGE_ACTIVE, "cycleStatus": "TRAILING_HEDGED", "lastHedgeEntryOrderId": hoid,
            "lastAction": "START_HEDGE_ACTIVE", "lastReason": "nieuwe cycle gestart met primary + starthedge; eerste DCA trailt volledig mee"})
        _persist(ref, state, owned, focusV2History=_history(state, mark=p, dca_ratio=dca_ratio, release_ratio=release_ratio,
            primary_notional=q*p, hedge_notional=hq*hp, primary_pnl=0.0, hedge_pnl=0.0))
        _audit(ref, "FOCUS_V2_TRAILING_CYCLE_STARTED_HEDGED", cycleId=cycle_id, symbol=symbol, primarySide=primary_side,
            startNotional=q*p, startHedgeNotional=hq*hp, startHedgePercent=configured_start_hedge_ratio, nextDca=state["nextDcaPrice"])
        return {"status": "executed", "action": "FOCUS_V2_START_HEDGED", "symbol": symbol, "ordersSent": 2, "cycleId": cycle_id}

    # Re-read current state values for active cycle.
    primary_pnl = _long_or_short_pnl(primary_row, mark, primary_side)
    hedge_pnl = _long_or_short_pnl(hedge_row, mark, hedge_side)

    # Hard invariant: a confirmed LONG DCA is not complete until SHORT equals total LONG.
    # This recovery path runs before normal DCA/release/TP logic, so a second DCA
    # cannot start while the hedge synchronization is pending.
    if simple_flow and str(state.get("cycleStatus", "")) == "DCA_HEDGE_SYNC_PENDING":
        target_qty = primary_qty
        qty_tolerance = max(1e-12, target_qty * 0.001)
        missing_qty = max(0.0, target_qty - hedge_qty)
        if missing_qty <= qty_tolerance:
            state.update({
                "hedgeState": HEDGE_ACTIVE if hedge_qty > qty_tolerance else HEDGE_OFF,
                "cycleStatus": "HEDGED" if hedge_qty > qty_tolerance else "LONG_ONLY",
                "lastAction": "DCA_HEDGE_SYNC_CONFIRMED",
                "lastReason": "pending DCA-hedge sync door actuele Aster-quantities bevestigd",
                "hedgeTargetQty": target_qty,
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_DCA_HEDGE_SYNC_CONFIRMED", cycleId=state.get("cycleId"), symbol=symbol, longQty=primary_qty, shortQty=hedge_qty)
            return {"status": "executed", "action": "DCA_HEDGE_SYNC_CONFIRMED", "symbol": symbol, "ordersSent": 0}

        if order_budget is not None and order_budget < 1:
            reason = {"reason": "ORDER_BUDGET_HEDGE_SYNC", "requiredShortQty": missing_qty, "longQty": primary_qty, "shortQty": hedge_qty, "orderBudget": order_budget}
            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)
            return {"status": "budget-exhausted", "action": "DCA_HEDGE_SYNC_PENDING", "ordersSent": 0, **reason}

        leverage = _resolved_leverage(client, settings, symbol, primary_row)
        required_notional = missing_qty * mark
        required_margin = required_notional / max(1, leverage)
        available = _finite(account.get("availableBalance"))
        equity = _finite(account.get("totalMarginBalance"), _finite(account.get("totalWalletBalance")))
        maint = _finite(account.get("totalMaintMargin")) / equity if equity > 0 else 1.0
        liq = _finite((primary_row or {}).get("liquidationPrice"))
        liq_distance = abs(mark - liq) / mark if liq > 0 else 1.0
        if required_margin > available or maint >= settings.emergency_margin_ratio or liq_distance < 0.05:
            block_reason = "INSUFFICIENT_MARGIN" if required_margin > available else ("EMERGENCY_MARGIN_RATIO" if maint >= settings.emergency_margin_ratio else "LIQUIDATION_DISTANCE")
            reason = {
                "reason": block_reason, "requiredShortQty": missing_qty, "requiredMargin": required_margin,
                "availableMargin": available, "maintenanceRatio": maint, "liquidationDistance": liq_distance,
                "longQty": primary_qty, "shortQty": hedge_qty,
            }
            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)
            return {"status": "waiting", "action": "DCA_HEDGE_SYNC_PENDING", "ordersSent": 0, **reason}

        cycle_no = int(_finite(state.get("dcaCount")))
        retry_prefix = _prefix(str(state.get("cycleId")), cycle_no, "DCA_HEDGE_SYNC_RETRY")
        hq, hp, hcid, hoid = _execute_with_precision_retry(
            client=client, symbol=symbol, mark=mark, notional=required_notional, leverage=leverage,
            side=hedge_side, action="OPEN", prefix=retry_prefix, new_position_leverage=leverage,
        )
        owned = _upsert_owned(
            owned, settings=settings, cycle_id=str(state.get("cycleId")), symbol=symbol, role=hedge_role,
            side=hedge_side, quantity=hq, price=hp, client_id=hcid, order_id=hoid, dca=False, timestamp_ms=timestamp_ms,
        )
        estimated_short_after = hedge_qty + hq
        remaining = max(0.0, target_qty - estimated_short_after)
        if remaining > qty_tolerance:
            state.update({
                "hedgeState": HEDGE_ACTIVE, "cycleStatus": "DCA_HEDGE_SYNC_PENDING",
                "lastAction": "DCA_HEDGE_SYNC_PENDING",
                "lastReason": "SHORT sync gedeeltelijk gevuld; volgende realtime tick opnieuw proberen",
                "hedgeTargetQty": target_qty,
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_DCA_HEDGE_SYNC_PARTIAL", cycleId=state.get("cycleId"), symbol=symbol, fillQty=hq, remainingShortQty=remaining)
            return {"status": "reconciling", "action": "DCA_HEDGE_SYNC_PENDING", "symbol": symbol, "ordersSent": 1, "requiredShortQty": remaining}

        state.update({
            "hedgeState": HEDGE_ACTIVE, "cycleStatus": "HEDGED",
            "lastAction": "DCA_HEDGE_SYNCED",
            "lastReason": "pending DCA-hedge sync voltooid; SHORT is weer gelijk aan totale LONG",
            "hedgeTargetQty": target_qty, "lastHedgeEntryOrderId": hoid,
        })
        _persist(ref, state, owned)
        _audit(ref, "FOCUS_DCA_HEDGE_SYNCED", cycleId=state.get("cycleId"), symbol=symbol, longQty=primary_qty, shortQty=estimated_short_after, orderId=hoid)
        return {"status": "executed", "action": "DCA_HEDGE_SYNCED", "symbol": symbol, "ordersSent": 1}

    # Primary-only OR initial start-hedge phase: DCA #1 moves on every fresh extreme.
    initial_hedged_trailing = hedge_qty > 1e-12 and int(_finite(state.get("dcaCount"))) == 0 and _finite(state.get("lastDcaFillPrice")) <= 0
    if hedge_qty <= 1e-12 or initial_hedged_trailing:
        if primary_side == "LONG":
            anchor = max(_finite(state.get("trailingHigh"), mark), mark)
            state["trailingHigh"] = anchor
        else:
            current = _finite(state.get("trailingLow"), mark)
            anchor = min(current, mark) if current > 0 else mark
            state["trailingLow"] = anchor
        state["nextDcaPrice"] = next_dca_from_anchor(anchor, primary_side, dca_ratio)
        state["dcaAnchorPrice"] = anchor
        state["dcaMode"] = DCA_TRAILING
        state["hedgeState"] = HEDGE_ACTIVE if initial_hedged_trailing else HEDGE_OFF
        state["cycleStatus"] = "TRAILING_HEDGED" if initial_hedged_trailing else "PRIMARY_ONLY"
        state["frozenDcaReference"] = 0.0
        state["hedgeReleasePrice"] = 0.0
        state["hedgeTargetQty"] = primary_qty * configured_start_hedge_ratio if initial_hedged_trailing else 0.0
    else:
        # v5: while hedged, BOTH directions stay fixed from the last confirmed DCA fill:
        # next DCA one step lower/higher against primary, hedge release one recovery step in favor.
        last_dca = _finite(state.get("lastDcaFillPrice"), _finite(state.get("dcaAnchorPrice"), mark))
        state["lastDcaFillPrice"] = last_dca
        state["nextDcaPrice"] = next_dca_from_anchor(last_dca, primary_side, dca_ratio)
        state["hedgeReleasePrice"] = 0.0 if simple_flow else release_price_from_last_dca(last_dca, primary_side, release_ratio)
        state["hedgeTargetQty"] = primary_qty * configured_hedge_ratio
        state["frozenDcaReference"] = 0.0
        state["dcaMode"] = DCA_FROZEN
        state["hedgeState"] = HEDGE_ACTIVE

    next_dca = _finite(state.get("nextDcaPrice"))
    dca_allowed = settings.focus_dca_enabled and (settings.focus_dca_unlimited or int(_finite(state.get("dcaCount"))) < settings.focus_max_dca)

    # DCA has priority on renewed downside/upside-against-primary, including while hedge is active.
    if dca_allowed and dca_crossed(mark, next_dca, primary_side):
        if order_budget is not None and order_budget < 2:
            reason = {"reason": "ORDER_BUDGET", "markPrice": mark, "nextDcaPrice": next_dca, "orderBudget": order_budget}
            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)
            return {"status": "budget-exhausted", "action": "FOCUS_DCA_BLOCKED", "ordersSent": 0, **reason}
        current_count = int(_finite(state.get("dcaCount")))
        used = primary_notional
        leverage = _resolved_leverage(client, settings, symbol, primary_row)
        budget_notional = _amount_to_notional(settings, settings.focus_max_budget_usd, leverage)
        remaining_budget = max(0.0, budget_notional - used)
        raw_dca_amount = _dca_notional(settings, current_count, settings.focus_max_budget_usd if getattr(settings, "focus_v2_amounts_are_margin", False) else remaining_budget)
        dca_notional = _amount_to_notional(settings, raw_dca_amount, leverage) if getattr(settings, "focus_v2_amounts_are_margin", False) else raw_dca_amount
        dca_notional = min(dca_notional, remaining_budget)
        if dca_notional <= 0:
            reason = {"reason": "DCA_BUDGET", "markPrice": mark, "nextDcaPrice": next_dca, "dcaCount": current_count, "remainingBudget": remaining_budget}
            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)
            return {"status": "waiting", "action": "FOCUS_DCA_BLOCKED", "ordersSent": 0, **reason}
        equity = _finite(account.get("totalMarginBalance"), _finite(account.get("totalWalletBalance")))
        maint = _finite(account.get("totalMaintMargin")) / equity if equity > 0 else 1.0
        liq = _finite((primary_row or {}).get("liquidationPrice"))
        liq_distance = abs(mark - liq) / mark if liq > 0 else 1.0
        expected_primary_after = primary_notional + dca_notional
        hedge_target = expected_primary_after * configured_hedge_ratio
        hedge_gap = max(0.0, hedge_target - hedge_notional)
        required_margin = (dca_notional + hedge_gap) / max(1, leverage)
        available = _finite(account.get("availableBalance"))
        if required_margin > available or maint >= settings.emergency_margin_ratio or liq_distance < 0.05:
            block_reason = "INSUFFICIENT_MARGIN" if required_margin > available else ("EMERGENCY_MARGIN_RATIO" if maint >= settings.emergency_margin_ratio else "LIQUIDATION_DISTANCE")
            reason = {
                "reason": block_reason, "markPrice": mark, "nextDcaPrice": next_dca,
                "dcaEnabled": bool(settings.focus_dca_enabled), "dcaCount": current_count,
                "maxDca": settings.focus_max_dca, "dcaUnlimited": bool(settings.focus_dca_unlimited),
                "orderBudget": order_budget, "requiredMargin": required_margin, "availableMargin": available,
                "maintenanceRatio": maint, "liquidationDistance": liq_distance,
                "dcaNotional": dca_notional, "hedgeGapNotional": hedge_gap,
            }
            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)
            return {"status": "waiting", "action": "FOCUS_DCA_BLOCKED", "ordersSent": 0, **reason}

        cycle_no = current_count + 1
        dca_prefix = _prefix(str(state["cycleId"]), cycle_no, "DCA_ENTRY")
        q, p, cid, oid = _execute_with_precision_retry(
            client=client, symbol=symbol, mark=mark, notional=dca_notional, leverage=leverage,
            side=primary_side, action="OPEN", prefix=dca_prefix, new_position_leverage=leverage,
        )
        actual_primary_after = primary_notional + q * p
        fresh_positions = client.position_risk(symbol)
        fresh_primary = _row(fresh_positions, symbol, primary_side)
        fresh_hedge = _row(fresh_positions, symbol, hedge_side)
        fresh_primary_notional = _notional(fresh_primary) or actual_primary_after
        fresh_primary_qty = abs(_finite((fresh_primary or {}).get("positionAmt"))) or (primary_qty + q)
        fresh_hedge_notional = _notional(fresh_hedge)
        fresh_hedge_qty = abs(_finite((fresh_hedge or {}).get("positionAmt")))
        target_after = fresh_primary_notional * configured_hedge_ratio
        target_qty_after = fresh_primary_qty * configured_hedge_ratio
        gap_qty = max(0.0, target_qty_after - fresh_hedge_qty)
        qty_tolerance = max(1e-12, target_qty_after * 0.001)
        gap = gap_qty * max(p, mark)
        hq = hp = 0.0
        hcid = hoid = ""
        try:
            if gap_qty > qty_tolerance:
                hedge_prefix = _prefix(str(state["cycleId"]), cycle_no, "HEDGE_ENTRY")
                hq, hp, hcid, hoid = _execute_with_precision_retry(
                    client=client, symbol=symbol, mark=p, notional=gap, leverage=leverage,
                    side=hedge_side, action="OPEN", prefix=hedge_prefix, new_position_leverage=leverage,
                )
        except Exception as exc:
            owned = _upsert_owned(
                owned, settings=settings, cycle_id=str(state["cycleId"]), symbol=symbol,
                role=primary_role, side=primary_side, quantity=q, price=p,
                client_id=cid, order_id=oid, dca=True, timestamp_ms=timestamp_ms,
            )
            state.update({
                "weightedEntry": _finite((fresh_primary or {}).get("entryPrice"), p),
                "dcaCount": cycle_no, "dcaMode": DCA_FROZEN, "hedgeState": HEDGE_ACTIVE,
                "lastDcaFillPrice": p, "nextDcaPrice": next_dca_from_anchor(p, primary_side, dca_ratio),
                "hedgeReleasePrice": 0.0, "hedgeTargetQty": target_qty_after,
                "cycleStatus": "DCA_HEDGE_SYNC_PENDING", "lastAction": "DCA_HEDGE_SYNC_PENDING",
                "lastReason": f"LONG DCA bevestigd; SHORT sync opnieuw proberen: {exc}",
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_DCA_HEDGE_SYNC_PENDING", cycleId=state["cycleId"], symbol=symbol, dcaCount=cycle_no, requiredShortQty=gap_qty, error=str(exc))
            return {"status": "reconciling", "action": "DCA_HEDGE_SYNC_PENDING", "symbol": symbol, "ordersSent": 1, "requiredShortQty": gap_qty}

        owned = _upsert_owned(
            owned, settings=settings, cycle_id=str(state["cycleId"]), symbol=symbol,
            role=primary_role, side=primary_side, quantity=q, price=p,
            client_id=cid, order_id=oid, dca=True, timestamp_ms=timestamp_ms,
        )
        if hq > 0:
            owned = _upsert_owned(
                owned, settings=settings, cycle_id=str(state["cycleId"]), symbol=symbol,
                role=hedge_role, side=hedge_side, quantity=hq, price=hp,
                client_id=hcid, order_id=hoid, dca=False, timestamp_ms=timestamp_ms,
            )
        new_qty = primary_qty + q
        entry = _finite((primary_row or {}).get("entryPrice"), _finite(state.get("weightedEntry"), p))
        new_entry = ((primary_qty * entry) + (q * p)) / max(new_qty, 1e-12)
        next_fixed_dca = next_dca_from_anchor(p, primary_side, dca_ratio)
        release_price = 0.0 if simple_flow else release_price_from_last_dca(p, primary_side, release_ratio)
        state.update({
            "weightedEntry": new_entry,
            "dcaCount": cycle_no,
            "dcaMode": DCA_FROZEN,
            "hedgeState": HEDGE_ACTIVE,
            "frozenDcaReference": 0.0,
            "lastDcaFillPrice": p,
            "nextDcaPrice": next_fixed_dca,
            "hedgeReleasePrice": release_price,
            "hedgeTargetQty": target_qty_after,
            "dcaAnchorPrice": p,
            "hedgeCycleId": f"{state['cycleId']}-dca-{cycle_no}",
            "lastDcaOrderId": oid,
            "lastHedgeEntryOrderId": hoid,
            "cycleStatus": "HEDGED",
            "lastAction": "DCA_HEDGE_SYNCED",
            "lastReason": "DCA geraakt: LONG bevestigd en SHORT naar totale LONG-quantity gesynchroniseerd",
            "stateMachineVersion": 6,
        })
        _persist(ref, state, owned, focusV2History=_history(
            state, mark=p, dca_ratio=dca_ratio, release_ratio=release_ratio,
            primary_notional=actual_primary_after, hedge_notional=fresh_hedge_notional + hq*hp,
            primary_pnl=primary_pnl, hedge_pnl=hedge_pnl,
        ))
        _audit(ref, "FOCUS_V2_TRAILING_DCA_HEDGE", cycleId=state["cycleId"], symbol=symbol, dcaCount=cycle_no, lastDcaFill=p, nextDca=next_fixed_dca, hedgeReleasePrice=release_price, hedgeTarget=target_after, hedgeTargetQty=target_qty_after)
        return {"status": "executed", "action": "FOCUS_V2_DCA_HEDGE_ACTIVE", "symbol": symbol, "ordersSent": 2 if hq > 0 else 1, "dcaCount": cycle_no, "lastDcaFillPrice": p, "nextDcaPrice": next_fixed_dca, "hedgeReleasePrice": release_price, "hedgeTargetQty": target_qty_after}

    # Active protection is checked on EVERY execution tick. In simple mode the
    # only strategic release gate is strictly positive expected NET hedge PnL.
    if hedge_qty > 1e-12:
        last_dca = _finite(state.get("lastDcaFillPrice"))
        release_price = 0.0 if simple_flow else (_finite(state.get("hedgeReleasePrice")) or release_price_from_last_dca(last_dca, primary_side, release_ratio))
        recovery = recovery_from_last_dca(mark, last_dca, primary_side)
        expected_net, executable_close, gross_close_pnl, estimated_fees, slippage_buffer = expected_net_hedge_close_pnl(client, symbol, hedge_side, hedge_row, mark)
        release_allowed = expected_net > 0.0 if simple_flow else (last_dca > 0 and hedge_release_crossed(mark, release_price, primary_side))
        if release_allowed:
            if order_budget is not None and order_budget < 1:
                return {"status": "budget-exhausted", "action": "FOCUS_V2_WAIT_HEDGE_RELEASE", "ordersSent": 0}
            state["hedgeState"] = HEDGE_RELEASE_EXECUTING
            _persist(ref, state, owned)
            leverage = int(_finite((hedge_row or {}).get("leverage"), settings.leverage))
            release_prefix = _prefix(str(state["cycleId"]), int(_finite(state.get("dcaCount"))), "HEDGE_RELEASE")
            cq, cp, ccid, coid = _execute_with_precision_retry(
                client=client, symbol=symbol, mark=mark, notional=hedge_qty*mark,
                leverage=leverage, side=hedge_side, action="CLOSE", prefix=release_prefix,
            )
            # Confirm exchange truth before re-enabling trailing.
            confirmed_positions = client.position_risk(symbol)
            confirmed_hedge = _row(confirmed_positions, symbol, hedge_side)
            remaining_hedge_qty = abs(_finite((confirmed_hedge or {}).get("positionAmt")))
            if remaining_hedge_qty > max(1e-12, hedge_qty * 0.001):
                state.update({
                    "hedgeState": HEDGE_RELEASE_EXECUTING,
                    "lastHedgeReleaseOrderId": coid,
                    "lastAction": "HEDGE_RELEASE_EXECUTING",
                    "lastReason": "reduce-only release verzonden; exchange bevestigt nog resterende hedge",
                })
                _persist(ref, state, owned)
                return {"status": "reconciling", "action": "FOCUS_V2_HEDGE_RELEASE_EXECUTING", "symbol": symbol, "ordersSent": 1, "hedgeRemainingQty": remaining_hedge_qty}
            owned = _reduce_owned(owned, hedge_role, cq, timestamp_ms)
            anchor = cp if cp > 0 else mark
            state.update({
                "dcaMode": DCA_TRAILING,
                "hedgeState": HEDGE_OFF,
                "frozenDcaReference": 0.0,
                "hedgeCycleId": "",
                "hedgeReleasePrice": 0.0,
                "hedgeTargetQty": 0.0,
                "trailingHigh": anchor if primary_side == "LONG" else 0.0,
                "trailingLow": anchor if primary_side == "SHORT" else 0.0,
                "dcaAnchorPrice": anchor,
                "nextDcaPrice": next_dca_from_anchor(anchor, primary_side, dca_ratio),
                "lastHedgeReleaseOrderId": coid,
                "cycleStatus": "LONG_ONLY",
                "lastAction": "HEDGE_RELEASED_NET_GREEN",
                "lastReason": "SHORT netto groen; volledige beschermingshedge gesloten; LONG blijft actief",
                "stateMachineVersion": 6,
            })
            _persist(ref, state, owned, focusV2History=_history(
                state, mark=anchor, dca_ratio=dca_ratio, release_ratio=release_ratio,
                primary_notional=primary_notional, hedge_notional=0.0,
                primary_pnl=primary_pnl, hedge_pnl=0.0,
            ))
            _audit(ref, "FOCUS_HEDGE_RELEASED_NET_GREEN", cycleId=state["cycleId"], symbol=symbol, lastDcaFill=last_dca, expectedNetClosePnl=expected_net, executableClosePrice=executable_close, grossClosePnl=gross_close_pnl, estimatedFees=estimated_fees, slippageBuffer=slippage_buffer, closeQty=cq, closePrice=cp)
            return {"status": "executed", "action": "FOCUS_HEDGE_RELEASED_NET_GREEN", "symbol": symbol, "ordersSent": 1, "expectedNetClosePnl": expected_net, "executableClosePrice": executable_close, "shortOrLongHedgeRemaining": 0.0}

        if simple_flow:
            state.update({
                "cycleStatus": "HEDGED", "lastAction": "HEDGE_HOLD_RED",
                "lastReason": "SHORT nog niet netto groen; volgende realtime tick opnieuw controleren",
                "hedgeReleasePrice": 0.0,
            })

    # v6 full-close TP is only legal in primary-only state.
    if hedge_qty <= 1e-12 and take_profit_reached(settings, primary_pnl, primary_notional):
        if order_budget is not None and order_budget < 1:
            return {"status": "budget-exhausted", "action": "FOCUS_V2_WAIT_FULL_TP", "ordersSent": 0}
        leverage = int(_finite((primary_row or {}).get("leverage"), settings.leverage))
        old_cycle_id = str(state["cycleId"])
        state.update({"cycleStatus": "TP_EXECUTING", "lastAction": "TP_EXECUTING", "lastReason": "full-close TP geraakt; primary volledig sluiten"})
        _persist(ref, state, owned)
        tp_prefix = _prefix(old_cycle_id, int(_finite(state.get("dcaCount"))), "FULL_TP")
        cq, cp, ccid, coid = _execute_with_precision_retry(client=client, symbol=symbol, mark=mark,
            notional=primary_qty*mark, leverage=leverage, side=primary_side, action="CLOSE", prefix=tp_prefix)
        confirmed_positions = client.position_risk(symbol)
        remaining_primary = _row(confirmed_positions, symbol, primary_side)
        remaining_qty = abs(_finite((remaining_primary or {}).get("positionAmt")))
        if remaining_qty > max(1e-12, primary_qty * 0.001):
            state.update({"lastPrimaryTpOrderId": coid, "lastReason": "full TP verzonden; exchange bevestigt nog resterende primary"})
            _persist(ref, state, owned)
            return {"status": "reconciling", "action": "FOCUS_V2_TP_EXECUTING", "symbol": symbol, "ordersSent": 1, "primaryRemainingQty": remaining_qty}
        owned = _reduce_owned(owned, primary_role, cq, timestamp_ms)
        last_cycle = {"cycleId": old_cycle_id, "closedAt": timestamp_ms, "closePrice": cp, "tpMode": tp_mode, "tpValue": tp_value, "fullTp": True}
        remaining_owned = [x for x in owned if not str(x.role).upper().startswith("FOCUS_V2")]
        auto_restart = bool(getattr(settings, "focus_v2_auto_restart", True))
        if auto_restart:
            restarting = {"cycleId": "", "symbol": symbol, "primarySide": primary_side, "restartPending": True,
                "autoRestart": True, "cycleStatus": "RESTARTING", "tpMode": tp_mode, "tpValue": tp_value, "stateMachineVersion": 6}
            _persist(ref, restarting, remaining_owned, focusV2LastCycle=last_cycle)
        else:
            paused = {"cycleId": "", "symbol": symbol, "primarySide": primary_side, "pausedAfterTp": True,
                "autoRestart": False, "cycleStatus": "TP_CLOSED", "tpMode": tp_mode, "tpValue": tp_value, "stateMachineVersion": 6}
            _persist(ref, paused, remaining_owned, focusV2LastCycle=last_cycle)
        _audit(ref, "FOCUS_V2_FULL_TP", cycleId=old_cycle_id, symbol=symbol, closeQty=cq, closePrice=cp, tpMode=tp_mode, tpValue=tp_value, primaryPnl=primary_pnl, autoRestart=auto_restart)
        if auto_restart:
            return {"status": "executed", "action": "FOCUS_V2_TP_CLOSED_RESTART_PENDING", "symbol": symbol, "ordersSent": 1, "autoRestart": True}
        return {"status": "executed", "action": "FOCUS_V2_TP_CLOSED_PAUSED", "symbol": symbol, "ordersSent": 1, "autoRestart": False}

    # Persist high/low movement and presentation state even when no order fires.
    state["lastAction"] = "HOLD"
    state["lastReason"] = "trailing/fixed-hedge state bijgewerkt; geen ordertrigger"
    _persist(ref, state, owned, focusV2History=_history(
        state, mark=mark, dca_ratio=dca_ratio, release_ratio=release_ratio,
        primary_notional=primary_notional, hedge_notional=hedge_notional,
        primary_pnl=primary_pnl, hedge_pnl=hedge_pnl,
    ))
    return {
        "status": "holding", "action": "FOCUS_V2_TRAILING_HOLD", "symbol": symbol,
        "ordersSent": 0, "dcaMode": state["dcaMode"], "hedgeState": state["hedgeState"],
        "nextDcaPrice": state["nextDcaPrice"], "lastDcaFillPrice": _finite(state.get("lastDcaFillPrice")),
        "hedgeReleasePrice": _finite(state.get("hedgeReleasePrice")), "hedgeTargetQty": _finite(state.get("hedgeTargetQty")),
        "recoverySinceLastDca": recovery_from_last_dca(mark, _finite(state.get("lastDcaFillPrice")), primary_side),
    }
