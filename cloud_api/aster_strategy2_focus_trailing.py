"""Strategy-2 Focus deterministic portfolio-cycle state-machine.

This is the authoritative live engine for Focus 2.0 simple mode.

Contract:
- every new v6 cycle starts with a primary leg plus configurable start hedge;
- a DCA cross adds primary exposure and hedges the configured ratio of the total primary position;
- in Simple Mode every DCA is a ratcheting trailing level: it follows fresh highs upward and never moves down during a pullback;
- the full hedge may release only after the configured recovery AND when the exact hedge close is net profitable after conservative round-trip fees/slippage;
- after each confirmed DCA the trailing anchor resets to that fill/current price and the next DCA starts one configured step below it;
- after release, trailing resumes immediately from the confirmed release/current price;
- the only full-cycle exit is portfolio equity growth versus cycleStartEquity; it closes both legs and can auto-restart.

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


def portfolio_target_reached(settings: Strategy2Config, current_equity: float, cycle_start_equity: float) -> bool:
    """Only cycle exit: actual account equity growth versus the persisted cycle baseline."""
    value = max(0.0, _finite(getattr(settings, "focus_v2_take_profit_value", 0.0)))
    if value <= 0 or current_equity <= 0 or cycle_start_equity <= 0:
        return False
    gain = current_equity - cycle_start_equity
    if gain < 0:
        return False
    mode = str(getattr(settings, "focus_v2_take_profit_mode", "usdt")).lower()
    if mode == "percent":
        return gain / cycle_start_equity >= value
    return gain >= value


def take_profit_reached(settings: Strategy2Config, primary_pnl: float, primary_notional: float) -> bool:
    value = max(0.0, _finite(getattr(settings, "focus_v2_take_profit_value", 0.0)))
    if value <= 0 or primary_pnl <= 0:
        return False
    mode = str(getattr(settings, "focus_v2_take_profit_mode", "usdt")).lower()
    return (primary_notional > 0 and primary_pnl / primary_notional >= value) if mode == "percent" else primary_pnl >= value


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
    state.setdefault("dcaTriggerPending", False)
    state.setdefault("dcaTriggerPrice", 0.0)
    state.setdefault("dcaTriggerMarkPrice", 0.0)
    state.setdefault("dcaTriggerAtMs", 0)
    state.setdefault("protectionReserveRequired", 0.0)
    state.setdefault("protectionReserveAvailable", 0.0)
    state.setdefault("protectionReserveSpendableMargin", 0.0)
    state.setdefault("protectionReserveReady", False)
    state.setdefault("protectionReserveShortfall", 0.0)
    state.setdefault("protectionReserveBufferPct", 0.0)
    state.setdefault("marketEventReceivedAt", 0)
    state.setdefault("dcaTriggerDetectedAt", 0)
    state.setdefault("dcaLongOrderSubmittedAt", 0)
    state.setdefault("dcaLongFillConfirmedAt", 0)
    state.setdefault("shortSyncSubmittedAt", 0)
    state.setdefault("shortSyncConfirmedAt", 0)
    state.setdefault("triggerToLongSubmitMs", 0)
    state.setdefault("longFillToShortSubmitMs", 0)
    state.setdefault("triggerToFullHedgeMs", 0)
    state.setdefault("frozenDcaReference", 0.0)  # legacy v4 field
    state.setdefault("lastDcaFillPrice", 0.0)
    state.setdefault("hedgeReleasePrice", 0.0)
    state.setdefault("cycleStartEquity", 0.0)
    state.setdefault("reHedgeArmed", False)
    state.setdefault("reHedgePrice", 0.0)
    state.setdefault("portfolioExitExecuting", False)
    state.setdefault("hedgeTargetQty", 0.0)
    state.setdefault("hedgeCycleId", "")
    state.setdefault("shortNetGreenReleasePrice", 0.0)
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


def net_green_hedge_release_price(hedge_row: dict[str, Any] | None, hedge_side: str) -> float:
    if not hedge_row:
        return 0.0
    entry=_finite(hedge_row.get("entryPrice"))
    if entry<=0:
        return 0.0
    fee_rate=0.0005
    slippage_rate=0.0002
    if hedge_side.upper()=="SHORT":
        return entry*(1.0-fee_rate)/(1.0+fee_rate+slippage_rate)
    denominator=1.0-fee_rate-slippage_rate
    return entry*(1.0+fee_rate)/denominator if denominator>0 else 0.0


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
        "shortNetGreenReleasePrice": _finite(state.get("shortNetGreenReleasePrice")),
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
        "stateMachineVersion": 7,
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
    state["stateMachineVersion"] = 8 if simple_flow else 7
    if simple_flow:
        # v7 uses only the explicit re-hedge trigger below. Legacy rebuild fields
        # are ignored but not allowed to drive strategy decisions.
        state.setdefault("reHedgeArmed", False)
        state.setdefault("reHedgePrice", 0.0)

    primary_notional = _notional(primary_row)
    hedge_notional = _notional(hedge_row)
    primary_qty = abs(_finite((primary_row or {}).get("positionAmt")))
    hedge_qty = abs(_finite((hedge_row or {}).get("positionAmt")))

    current_equity = _finite(account.get("totalMarginBalance"), _finite(account.get("totalWalletBalance")))
    cycle_start_equity = _finite(state.get("cycleStartEquity"))
    target_now = bool(simple_flow and state.get("cycleId") and portfolio_target_reached(settings, current_equity, cycle_start_equity))
    exit_in_progress = bool(simple_flow and state.get("cycleId") and state.get("portfolioExitExecuting"))
    if target_now or exit_in_progress:
        required_orders = int(primary_qty > 1e-12) + int(hedge_qty > 1e-12)
        if order_budget is not None and order_budget < required_orders:
            state.update({
                "portfolioExitExecuting": True, "cycleStatus": "PORTFOLIO_EXIT_EXECUTING",
                "lastAction": "PORTFOLIO_EXIT_WAIT_BUDGET",
                "lastReason": "portfolio-doel heeft absolute prioriteit; wachten op orderbudget om beide legs volledig te sluiten",
            })
            _persist(ref, state, owned)
            return {"status": "budget-exhausted", "action": "PORTFOLIO_EXIT_WAIT_BUDGET", "ordersSent": 0}

        old_cycle_id = str(state.get("cycleId"))
        state.update({
            "portfolioExitExecuting": True, "cycleStatus": "PORTFOLIO_EXIT_EXECUTING",
            "lastAction": "PORTFOLIO_EXIT_EXECUTING",
            "lastReason": "ingestelde portfoliogroei bereikt; alle Strategy-2 legs sluiten en oude cycle blokkeren",
            "dcaTriggerPending": False, "reHedgeArmed": False, "reHedgePrice": 0.0,
        })
        _persist(ref, state, owned)
        orders_sent = 0
        hedge_close_price = 0.0
        primary_close_price = 0.0
        if hedge_qty > 1e-12:
            leverage = int(_finite((hedge_row or {}).get("leverage"), settings.leverage))
            cq, cp, _ccid, _coid = _execute_with_precision_retry(
                client=client, symbol=symbol, mark=mark, notional=hedge_qty * mark, leverage=leverage,
                side=hedge_side, action="CLOSE", prefix=_prefix(old_cycle_id, int(_finite(state.get("dcaCount"))), "PORTFOLIO_HEDGE_CLOSE"),
            )
            orders_sent += 1
            hedge_close_price = cp
            owned = _reduce_owned(owned, hedge_role, cq, timestamp_ms)
        refreshed = client.position_risk(symbol)
        refreshed_primary = _row(refreshed, symbol, primary_side)
        refreshed_hedge = _row(refreshed, symbol, hedge_side)
        remaining_hedge = abs(_finite((refreshed_hedge or {}).get("positionAmt")))
        refreshed_primary_qty = abs(_finite((refreshed_primary or {}).get("positionAmt")))
        if remaining_hedge > max(1e-12, hedge_qty * 0.001):
            _persist(ref, state, owned)
            return {"status": "reconciling", "action": "PORTFOLIO_EXIT_EXECUTING", "ordersSent": orders_sent, "hedgeRemainingQty": remaining_hedge}
        if refreshed_primary_qty > 1e-12:
            leverage = int(_finite((refreshed_primary or {}).get("leverage"), settings.leverage))
            cq, cp, _ccid, _coid = _execute_with_precision_retry(
                client=client, symbol=symbol, mark=mark, notional=refreshed_primary_qty * mark, leverage=leverage,
                side=primary_side, action="CLOSE", prefix=_prefix(old_cycle_id, int(_finite(state.get("dcaCount"))), "PORTFOLIO_PRIMARY_CLOSE"),
            )
            orders_sent += 1
            primary_close_price = cp
            owned = _reduce_owned(owned, primary_role, cq, timestamp_ms)
        confirmed = client.position_risk(symbol)
        remaining_primary = abs(_finite((_row(confirmed, symbol, primary_side) or {}).get("positionAmt")))
        remaining_hedge = abs(_finite((_row(confirmed, symbol, hedge_side) or {}).get("positionAmt")))
        if remaining_primary > 1e-12 or remaining_hedge > 1e-12:
            _persist(ref, state, owned)
            return {
                "status": "reconciling", "action": "PORTFOLIO_EXIT_EXECUTING", "ordersSent": orders_sent,
                "primaryRemainingQty": remaining_primary, "hedgeRemainingQty": remaining_hedge,
            }

        realized_equity = _finite(account.get("totalMarginBalance"), current_equity)
        last_cycle = {
            "cycleId": old_cycle_id, "closedAt": timestamp_ms, "portfolioTarget": True,
            "cycleStartEquity": cycle_start_equity, "equityAtTrigger": current_equity,
            "portfolioGainAtTrigger": current_equity - cycle_start_equity,
            "primaryClosePrice": primary_close_price, "hedgeClosePrice": hedge_close_price,
            "tpMode": tp_mode, "tpValue": tp_value,
        }
        remaining_owned = [x for x in owned if not str(x.role).upper().startswith("FOCUS_V2")]
        auto_restart = bool(getattr(settings, "focus_v2_auto_restart", True))
        if auto_restart:
            restarting = {
                "cycleId": "", "symbol": symbol, "primarySide": primary_side, "restartPending": True,
                "autoRestart": True, "cycleStatus": "RESTARTING", "tpMode": tp_mode, "tpValue": tp_value,
                "portfolioExitExecuting": False, "stateMachineVersion": 7,
            }
            _persist(ref, restarting, remaining_owned, focusV2LastCycle=last_cycle)
        else:
            paused = {
                "cycleId": "", "symbol": symbol, "primarySide": primary_side, "pausedAfterTp": True,
                "autoRestart": False, "cycleStatus": "PORTFOLIO_TARGET_CLOSED", "tpMode": tp_mode, "tpValue": tp_value,
                "portfolioExitExecuting": False, "stateMachineVersion": 7,
            }
            _persist(ref, paused, remaining_owned, focusV2LastCycle=last_cycle)
        _audit(ref, "FOCUS_PORTFOLIO_TARGET_CLOSED", cycleId=old_cycle_id, symbol=symbol, cycleStartEquity=cycle_start_equity,
            equityAtTrigger=current_equity, portfolioGain=current_equity-cycle_start_equity, autoRestart=auto_restart)
        return {
            "status": "executed", "action": "FOCUS_PORTFOLIO_TARGET_CLOSED", "symbol": symbol,
            "ordersSent": orders_sent, "autoRestart": auto_restart, "cycleStartEquity": cycle_start_equity,
            "equityAtTrigger": current_equity, "portfolioGain": current_equity-cycle_start_equity,
        }

    # If a user manually flattened the Focus pair on Aster while the bot was stopped,
    # exchange truth wins over stale persisted cycle state. Only reset when both
    # sides are confirmed flat and there are no owned Focus-v2 legs. This lets the
    # same start tick create a genuinely new 1:1 cycle instead of reviving an old id.
    focus_v2_owned = [x for x in owned if str(x.role).upper().startswith("FOCUS_V2")]
    if simple_flow and state.get("cycleId") and primary_qty <= 1e-12 and hedge_qty <= 1e-12 and not focus_v2_owned:
        stale_cycle_id = str(state.get("cycleId"))
        state = _state({}, symbol=symbol, primary_side=primary_side)
        state.update({
            "startHedgePercent": configured_start_hedge_ratio,
            "hedgeTargetPercent": configured_hedge_ratio,
            "tpMode": tp_mode,
            "tpValue": tp_value,
            "autoRestart": bool(getattr(settings, "focus_v2_auto_restart", True)),
            "configSnapshotVersion": int(getattr(settings, "version", 1)),
            "dcaDistancePct": dca_ratio,
            "hedgeReleaseRecoveryPct": release_ratio,
            "hedgeRatio": configured_hedge_ratio,
            "stateMachineVersion": 7,
            "lastAction": "FOCUS_V2_STALE_FLAT_RECONCILED",
            "lastReason": "Aster bevestigt LONG en SHORT flat; oude Focus-cycle state veilig gereset voor nieuwe start",
        })
        _persist(ref, state, owned)
        _audit(ref, "FOCUS_V2_STALE_FLAT_RECONCILED", cycleId=stale_cycle_id, symbol=symbol)

    if bool(state.get("pausedAfterTp")) and not bool(getattr(settings, "focus_v2_auto_restart", True)):
        return {"status": "waiting", "action": "FOCUS_V2_TP_CLOSED_PAUSED", "symbol": symbol, "ordersSent": 0}
    if bool(state.get("pausedAfterTp")) and bool(getattr(settings, "focus_v2_auto_restart", True)):
        state["pausedAfterTp"] = False

    # Crash/restart recovery and hard start invariant: START is complete only when
    # Aster confirms SHORT quantity equals the actual LONG quantity. Partial start
    # hedges are repaired; an oversized hedge is held for manual/reconciliation
    # handling rather than automatically closing a possibly-red SHORT.
    start_sync_pending = str(state.get("cycleStatus", "")) == "START_HEDGE_SYNC_PENDING"
    if state.get("cycleId") and primary_qty > 0 and (str(state.get("hedgeState", "")) == HEDGE_STARTING or start_sync_pending):
        target_qty = primary_qty if simple_flow else primary_qty * configured_start_hedge_ratio
        qty_tolerance = max(1e-12, target_qty * 0.001)
        delta_qty = target_qty - hedge_qty
        if abs(delta_qty) <= qty_tolerance:
            state.update({
                "hedgeState": HEDGE_ACTIVE, "cycleStatus": "FOCUS_HEDGED",
                "hedgeTargetQty": target_qty, "lastAction": "START_HEDGE_SYNC_CONFIRMED",
                "lastReason": "Aster bevestigt LONG en SHORT quantities gelijk binnen tolerance",
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_START_HEDGE_SYNC_CONFIRMED", cycleId=state["cycleId"], symbol=symbol, longQty=primary_qty, shortQty=hedge_qty)
            return {"status": "executed", "action": "FOCUS_START_HEDGE_SYNC_CONFIRMED", "symbol": symbol, "ordersSent": 0}
        if delta_qty < -qty_tolerance:
            state.update({
                "hedgeState": HEDGE_STARTING, "cycleStatus": "START_HEDGE_SYNC_PENDING",
                "hedgeTargetQty": target_qty, "lastAction": "START_HEDGE_OVER_SYNC",
                "lastReason": "Aster SHORT is groter dan LONG; geen automatische verlieslatende SHORT-close",
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_START_HEDGE_OVER_SYNC", cycleId=state["cycleId"], symbol=symbol, longQty=primary_qty, shortQty=hedge_qty)
            return {"status": "reconciling", "action": "FOCUS_START_HEDGE_SYNC_PENDING", "symbol": symbol, "ordersSent": 0, "longQty": primary_qty, "shortQty": hedge_qty}
        if order_budget is not None and order_budget < 1:
            return {"status": "budget-exhausted", "action": "FOCUS_START_HEDGE_SYNC_PENDING", "ordersSent": 0, "requiredShortQty": delta_qty}
        leverage = _resolved_leverage(client, settings, symbol, primary_row)
        required_notional = delta_qty * mark
        required_margin = required_notional / max(1, leverage)
        available = _finite(account.get("availableBalance"))
        if required_margin > available:
            _audit(ref, "FOCUS_START_HEDGE_SYNC_BLOCKED", cycleId=state["cycleId"], symbol=symbol, reason="INSUFFICIENT_MARGIN", requiredMargin=required_margin, availableMargin=available, requiredShortQty=delta_qty)
            return {"status": "waiting", "action": "FOCUS_START_HEDGE_SYNC_PENDING", "ordersSent": 0, "reason": "INSUFFICIENT_MARGIN", "requiredMargin": required_margin, "availableMargin": available}
        prefix = _prefix(str(state["cycleId"]), 0, "START_HEDGE_SYNC")
        hq, hp, hcid, hoid = _execute_with_precision_retry(
            client=client, symbol=symbol, mark=mark, notional=required_notional, leverage=leverage,
            side=hedge_side, action="OPEN", prefix=prefix, new_position_leverage=leverage,
        )
        owned = _upsert_owned(owned, settings=settings, cycle_id=str(state["cycleId"]), symbol=symbol, role=hedge_role,
            side=hedge_side, quantity=hq, price=hp, client_id=hcid, order_id=hoid, dca=False, timestamp_ms=timestamp_ms)
        confirmed_positions = client.position_risk(symbol)
        confirmed_primary = _row(confirmed_positions, symbol, primary_side)
        confirmed_hedge = _row(confirmed_positions, symbol, hedge_side)
        confirmed_primary_qty = abs(_finite((confirmed_primary or {}).get("positionAmt")))
        confirmed_hedge_qty = abs(_finite((confirmed_hedge or {}).get("positionAmt")))
        confirmed_tolerance = max(1e-12, confirmed_primary_qty * 0.001)
        if confirmed_primary_qty <= 0 or abs(confirmed_primary_qty - confirmed_hedge_qty) > confirmed_tolerance:
            state.update({
                "hedgeState": HEDGE_STARTING, "cycleStatus": "START_HEDGE_SYNC_PENDING",
                "hedgeTargetQty": confirmed_primary_qty or target_qty, "lastHedgeEntryOrderId": hoid,
                "lastAction": "START_HEDGE_SYNC_PENDING",
                "lastReason": "starthedge fill bevestigd maar Aster quantities nog niet 1:1; volgende realtime tick herstellen",
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_START_HEDGE_SYNC_PENDING", cycleId=state["cycleId"], symbol=symbol, longQty=confirmed_primary_qty, shortQty=confirmed_hedge_qty)
            return {"status": "reconciling", "action": "FOCUS_START_HEDGE_SYNC_PENDING", "symbol": symbol, "ordersSent": 1, "longQty": confirmed_primary_qty, "shortQty": confirmed_hedge_qty}
        state.update({
            "hedgeState": HEDGE_ACTIVE, "cycleStatus": "FOCUS_HEDGED", "hedgeTargetQty": confirmed_primary_qty,
            "lastHedgeEntryOrderId": hoid, "lastAction": "START_HEDGE_SYNCED",
            "lastReason": "Aster bevestigt LONG en SHORT quantities exact gesynchroniseerd",
        })
        _persist(ref, state, owned)
        _audit(ref, "FOCUS_START_HEDGE_SYNCED", cycleId=state["cycleId"], symbol=symbol, longQty=confirmed_primary_qty, shortQty=confirmed_hedge_qty, orderId=hoid)
        return {"status": "executed", "action": "FOCUS_START_HEDGE_SYNCED", "symbol": symbol, "ordersSent": 1}

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
                state["hedgeReleasePrice"] = release_price_from_last_dca(last_dca, primary_side, release_ratio)
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
            "nextDcaPrice": next_dca_from_anchor(p, primary_side, dca_ratio),
            "dcaTriggerPending": False, "dcaTriggerPrice": 0.0, "dcaTriggerMarkPrice": 0.0, "dcaTriggerAtMs": 0,
            "lastDcaFillPrice": 0.0,
            "hedgeReleasePrice": 0.0, "hedgeTargetQty": q * configured_start_hedge_ratio,
            "startHedgePercent": configured_start_hedge_ratio, "hedgeTargetPercent": configured_hedge_ratio,
            "tpMode": tp_mode, "tpValue": tp_value, "autoRestart": bool(getattr(settings, "focus_v2_auto_restart", True)),
            "lastPrimaryOrderId": oid, "lastAction": "PRIMARY_OPEN_CONFIRMED", "stateMachineVersion": 7,
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
        confirmed_positions = client.position_risk(symbol)
        confirmed_primary = _row(confirmed_positions, symbol, primary_side)
        confirmed_hedge = _row(confirmed_positions, symbol, hedge_side)
        confirmed_primary_qty = abs(_finite((confirmed_primary or {}).get("positionAmt")))
        confirmed_hedge_qty = abs(_finite((confirmed_hedge or {}).get("positionAmt")))
        start_tolerance = max(1e-12, confirmed_primary_qty * 0.001)
        if confirmed_primary_qty <= 0 or abs(confirmed_primary_qty - confirmed_hedge_qty) > start_tolerance:
            state.update({
                "hedgeState": HEDGE_STARTING, "cycleStatus": "START_HEDGE_SYNC_PENDING",
                "hedgeTargetQty": confirmed_primary_qty or q, "lastHedgeEntryOrderId": hoid,
                "lastAction": "START_HEDGE_SYNC_PENDING",
                "lastReason": "startorders gevuld maar Aster quantities nog niet 1:1; volgende realtime tick synchroniseren",
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_START_HEDGE_SYNC_PENDING", cycleId=cycle_id, symbol=symbol, longQty=confirmed_primary_qty, shortQty=confirmed_hedge_qty)
            return {"status": "reconciling", "action": "FOCUS_START_HEDGE_SYNC_PENDING", "symbol": symbol, "ordersSent": 2, "cycleId": cycle_id}
        state.update({"hedgeState": HEDGE_ACTIVE, "cycleStatus": "FOCUS_HEDGED", "hedgeTargetQty": confirmed_primary_qty,
            "lastHedgeEntryOrderId": hoid, "lastAction": "START_HEDGE_ACTIVE",
            "lastReason": "nieuwe cycle: Aster bevestigt LONG en SHORT quantities 1:1; eerste DCA trailt mee"})
        _persist(ref, state, owned, focusV2History=_history(state, mark=p, dca_ratio=dca_ratio, release_ratio=release_ratio,
            primary_notional=q*p, hedge_notional=hq*hp, primary_pnl=0.0, hedge_pnl=0.0))
        _audit(ref, "FOCUS_V2_TRAILING_CYCLE_STARTED_HEDGED", cycleId=cycle_id, symbol=symbol, primarySide=primary_side,
            startNotional=q*p, startHedgeNotional=hq*hp, startHedgePercent=configured_start_hedge_ratio, nextDca=state["nextDcaPrice"], longQty=confirmed_primary_qty, shortQty=confirmed_hedge_qty)
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
            last_dca = _finite(state.get("lastDcaFillPrice"))
            restored_release = release_price_from_last_dca(last_dca, primary_side, release_ratio) if last_dca > 0 and hedge_qty > qty_tolerance else 0.0
            state.update({
                "hedgeState": HEDGE_ACTIVE if hedge_qty > qty_tolerance else HEDGE_OFF,
                "cycleStatus": "HEDGED" if hedge_qty > qty_tolerance else "LONG_ONLY",
                "hedgeReleasePrice": restored_release,
                "shortReleasePriceReady": False, "shortReleaseNetGreenReady": False, "expectedNetShortClosePnl": 0.0,
                "lastAction": "DCA_HEDGE_SYNC_CONFIRMED",
                "lastReason": "pending DCA-hedge sync door actuele Aster-quantities bevestigd; release opnieuw vanaf nieuwste DCA-fill gezet",
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

        last_dca = _finite(state.get("lastDcaFillPrice"))
        restored_release = release_price_from_last_dca(last_dca, primary_side, release_ratio) if last_dca > 0 else 0.0
        state.update({
            "hedgeState": HEDGE_ACTIVE, "cycleStatus": "HEDGED",
            "hedgeReleasePrice": restored_release,
            "shortReleasePriceReady": False, "shortReleaseNetGreenReady": False, "expectedNetShortClosePnl": 0.0,
            "lastAction": "DCA_HEDGE_SYNCED",
            "lastReason": "pending DCA-hedge sync voltooid; SHORT is weer gelijk aan totale LONG; release opnieuw vanaf nieuwste DCA-fill gezet",
            "hedgeTargetQty": target_qty, "lastHedgeEntryOrderId": hoid,
        })
        _persist(ref, state, owned)
        _audit(ref, "FOCUS_DCA_HEDGE_SYNCED", cycleId=state.get("cycleId"), symbol=symbol, longQty=primary_qty, shortQty=estimated_short_after, orderId=hoid)
        return {"status": "executed", "action": "DCA_HEDGE_SYNCED", "symbol": symbol, "ordersSent": 1}

    # Simple Mode: EVERY DCA ratchets from the freshest favorable extreme.
    # LONG: fresh highs raise the DCA; falling ticks never lower it.
    # After each fill the anchor is reset (see DCA execution below), so the next
    # DCA starts one configured step below the new fill/current price. Once a
    # crossing is proven it becomes durable and the trigger must NOT trail away
    # while execution is pending or the market rebounds.
    dca_trigger_pending = simple_flow and bool(state.get("dcaTriggerPending", False))
    initial_hedged_trailing = hedge_qty > 1e-12 and int(_finite(state.get("dcaCount"))) == 0 and _finite(state.get("lastDcaFillPrice")) <= 0
    if (simple_flow and not dca_trigger_pending) or (not simple_flow and (hedge_qty <= 1e-12 or initial_hedged_trailing)):
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
        if simple_flow:
            state["hedgeState"] = HEDGE_ACTIVE if hedge_qty > 1e-12 else HEDGE_OFF
            state["cycleStatus"] = "HEDGED" if hedge_qty > 1e-12 else "LONG_ONLY"
            state["hedgeTargetQty"] = primary_qty * configured_hedge_ratio if hedge_qty > 1e-12 else 0.0
        else:
            state["hedgeState"] = HEDGE_ACTIVE if initial_hedged_trailing else HEDGE_OFF
            state["cycleStatus"] = "TRAILING_HEDGED" if initial_hedged_trailing else "PRIMARY_ONLY"
            state["hedgeTargetQty"] = primary_qty * configured_start_hedge_ratio if initial_hedged_trailing else 0.0
        state["frozenDcaReference"] = 0.0
        if simple_flow:
            last_dca_for_release = _finite(state.get("lastDcaFillPrice"))
            state["hedgeReleasePrice"] = release_price_from_last_dca(last_dca_for_release, primary_side, release_ratio) if last_dca_for_release > 0 else 0.0
        else:
            state["hedgeReleasePrice"] = 0.0
    else:
        # v5: while hedged, BOTH directions stay fixed from the last confirmed DCA fill:
        # next DCA one step lower/higher against primary, hedge release one recovery step in favor.
        last_dca = _finite(state.get("lastDcaFillPrice"), _finite(state.get("dcaAnchorPrice"), mark))
        state["lastDcaFillPrice"] = last_dca
        state["nextDcaPrice"] = next_dca_from_anchor(last_dca, primary_side, dca_ratio)
        state["hedgeReleasePrice"] = release_price_from_last_dca(last_dca, primary_side, release_ratio)
        state["hedgeTargetQty"] = primary_qty * configured_hedge_ratio
        state["frozenDcaReference"] = 0.0
        state["dcaMode"] = DCA_FROZEN
        state["hedgeState"] = HEDGE_ACTIVE

    next_dca = _finite(state.get("nextDcaPrice"))
    dca_allowed = (not simple_flow) and settings.focus_dca_enabled and (settings.focus_dca_unlimited or int(_finite(state.get("dcaCount"))) < settings.focus_max_dca)

    # Protection reserve: continuously prove that the *next* DCA can fund both
    # the LONG add and the resulting full SHORT refill before we ever release
    # protection or submit a DCA order. This is a server-side budget reservation,
    # not an exchange wallet lock.
    reserve_leverage = max(1, int(_finite((primary_row or {}).get("leverage"), settings.leverage)))
    reserve_count = int(_finite(state.get("dcaCount")))
    reserve_budget_notional = _amount_to_notional(settings, settings.focus_max_budget_usd, reserve_leverage)
    reserve_remaining_budget = max(0.0, reserve_budget_notional - primary_notional)
    reserve_raw_dca_amount = _dca_notional(settings, reserve_count, settings.focus_max_budget_usd if getattr(settings, "focus_v2_amounts_are_margin", False) else reserve_remaining_budget)
    reserve_dca_notional = _amount_to_notional(settings, reserve_raw_dca_amount, reserve_leverage) if getattr(settings, "focus_v2_amounts_are_margin", False) else reserve_raw_dca_amount
    reserve_dca_notional = min(max(0.0, reserve_dca_notional), reserve_remaining_budget)
    reserve_expected_primary_after = primary_notional + reserve_dca_notional
    reserve_target_hedge_notional = reserve_expected_primary_after * configured_hedge_ratio
    reserve_short_gap_notional = max(0.0, reserve_target_hedge_notional - hedge_notional)
    reserve_base_margin = (reserve_dca_notional + reserve_short_gap_notional) / max(1, reserve_leverage)
    reserve_buffer_pct = max(0.0, min(.25, _finite(getattr(settings, "focus_v2_protection_reserve_buffer_pct", .05), .05)))
    reserve_required = reserve_base_margin * (1.0 + reserve_buffer_pct)
    reserve_available = max(0.0, _finite(account.get("availableBalance")))
    reserve_ready = bool(dca_allowed and reserve_dca_notional > 0 and reserve_available + 1e-9 >= reserve_required)
    state.update({
        "protectionReserveRequired": reserve_required,
        "protectionReserveAvailable": reserve_available,
        "protectionReserveSpendableMargin": max(0.0, reserve_available - reserve_required),
        "protectionReserveReady": reserve_ready,
        "protectionReserveShortfall": max(0.0, reserve_required - reserve_available),
        "protectionReserveBufferPct": reserve_buffer_pct,
        "protectionReserveDcaNotional": reserve_dca_notional,
        "protectionReserveShortRefillNotional": reserve_short_gap_notional,
    })

    crossed_now = dca_allowed and dca_crossed(mark, next_dca, primary_side)
    if simple_flow and crossed_now and not dca_trigger_pending:
        detected_ms = int(time.time() * 1000)
        state.update({
            "dcaTriggerPending": True,
            "dcaTriggerPrice": next_dca,
            "dcaTriggerMarkPrice": mark,
            "dcaTriggerAtMs": timestamp_ms,
            "marketEventReceivedAt": timestamp_ms,
            "dcaTriggerDetectedAt": detected_ms,
            "lastAction": "DCA_TRIGGER_PENDING",
            "lastReason": "realtime DCA-crossing bewezen; trigger blijft durable tot LONG DCA + SHORT sync bevestigd zijn",
        })
        _persist(ref, state, owned)
        _audit(ref, "FOCUS_DCA_TRIGGER_PENDING", cycleId=state.get("cycleId"), symbol=symbol, markPrice=mark, nextDcaPrice=next_dca)
        dca_trigger_pending = True
    dca_triggered = bool(dca_trigger_pending or crossed_now)

    # Manual Aster hedge-close reconciliation: exchange truth wins. If the hedge
    # was present in Focus ownership/state but Aster now confirms it flat, treat
    # that as an intentional manual hedge release. Keep the LONG cycle alive and
    # arm the exact same last-DCA re-hedge anchor used after a bot-managed release.
    # Start/DCA sync states are intentionally excluded so a missing required hedge
    # is never misclassified as a manual close.
    manual_hedge_closed = bool(
        simple_flow and state.get("cycleId") and primary_qty > 1e-12 and hedge_qty <= 1e-12 and
        _finite(state.get("lastDcaFillPrice")) > 0 and not bool(state.get("reHedgeArmed")) and
        str(state.get("hedgeState", "")) == HEDGE_ACTIVE and
        str(state.get("cycleStatus", "")) not in {
            "START_HEDGE_SYNC_PENDING", "DCA_HEDGE_SYNC_PENDING",
            "EMERGENCY_EQUITY_LOCK_WAIT_BUDGET", "PORTFOLIO_EXIT_EXECUTING",
        } and
        _leg(owned, hedge_role) is not None
    )
    if manual_hedge_closed:
        last_dca_manual = _finite(state.get("lastDcaFillPrice"))
        stale_owned_hedge = _leg(owned, hedge_role)
        if stale_owned_hedge is not None:
            owned = _reduce_owned(owned, hedge_role, stale_owned_hedge.quantity, timestamp_ms)
        state.update({
            "dcaMode": DCA_TRAILING, "hedgeState": HEDGE_OFF, "hedgeTargetQty": 0.0,
            "hedgeCycleId": "", "hedgeReleasePrice": 0.0,
            "shortReleasePriceReady": False, "shortReleaseNetGreenReady": False,
            "expectedNetShortClosePnl": 0.0, "shortNetGreenReleasePrice": 0.0,
            "reHedgeArmed": True, "reHedgePrice": last_dca_manual,
            "cycleStatus": "LONG_ONLY", "lastAction": "MANUAL_HEDGE_CLOSE_RECONCILED",
            "lastReason": "Aster bevestigt handmatig gesloten SHORT; LONG-cycle blijft actief en re-hedge is gewapend op laatste DCA-fill",
        })
        _persist(ref, state, owned)
        _audit(ref, "FOCUS_MANUAL_HEDGE_CLOSE_RECONCILED", cycleId=state.get("cycleId"), symbol=symbol,
            lastDcaFill=last_dca_manual, reHedgePrice=last_dca_manual)

    # v7 equity protection may repair missing protection below the cycle baseline, but
    # it must not block a valid hedge release; normal trailing
    # DCA remains active. Every confirmed LONG DCA must still be followed immediately
    # by a SHORT sync to the total LONG quantity. This block only repairs a missing
    # hedge; it must never freeze the DCA recovery mechanism.
    equity_lock_active = bool(
        simple_flow and cycle_start_equity > 0 and current_equity > 0 and
        current_equity + 1e-9 < cycle_start_equity and
        not bool(state.get("reHedgeArmed"))
    )
    if equity_lock_active and primary_qty > 1e-12:
        target_lock_qty = primary_qty * configured_hedge_ratio
        lock_tolerance = max(1e-12, target_lock_qty * 0.001)
        missing_lock_qty = max(0.0, target_lock_qty - hedge_qty)
        if missing_lock_qty > lock_tolerance:
            if order_budget is not None and order_budget < 1:
                state.update({
                    "cycleStatus": "EMERGENCY_EQUITY_LOCK_WAIT_BUDGET",
                    "lastAction": "EMERGENCY_EQUITY_LOCK_WAIT_BUDGET",
                    "lastReason": "equity onder cycleStartEquity; volledige hedge vereist maar orderbudget ontbreekt",
                })
                _persist(ref, state, owned)
                return {"status": "budget-exhausted", "action": "EMERGENCY_EQUITY_LOCK_WAIT_BUDGET", "ordersSent": 0}
            leverage = _resolved_leverage(client, settings, symbol, primary_row)
            lock_notional = missing_lock_qty * mark
            lock_required_margin = lock_notional / max(1, leverage)
            lock_available_margin = max(0.0, _finite(account.get("availableBalance")))
            if lock_required_margin > lock_available_margin + 1e-9:
                state.update({
                    "cycleStatus": "EMERGENCY_EQUITY_LOCK_WAIT_MARGIN",
                    "lastAction": "EMERGENCY_EQUITY_LOCK_WAIT_MARGIN",
                    "lastReason": "volledige protection hedge vereist maar actuele Aster available margin is onvoldoende; trigger blijft actief",
                    "equityProtectionActive": True,
                    "equityLockRequiredMargin": lock_required_margin,
                    "equityLockAvailableMargin": lock_available_margin,
                })
                _persist(ref, state, owned)
                _audit(ref, "FOCUS_EMERGENCY_EQUITY_LOCK_WAIT_MARGIN", cycleId=state.get("cycleId"), symbol=symbol,
                    requiredMargin=lock_required_margin, availableMargin=lock_available_margin)
                return {"status": "waiting", "action": "EMERGENCY_EQUITY_LOCK_WAIT_MARGIN", "ordersSent": 0}
            try:
                hq, hp, hcid, hoid = _execute_with_precision_retry(
                    client=client, symbol=symbol, mark=mark, notional=lock_notional, leverage=leverage,
                    side=hedge_side, action="OPEN",
                    prefix=_prefix(str(state.get("cycleId")), int(_finite(state.get("dcaCount"))), "EMERGENCY_EQUITY_LOCK"),
                    new_position_leverage=leverage,
                )
            except Exception as exc:
                if "-2019" not in str(exc) and "Margin is insufficient" not in str(exc):
                    raise
                state.update({
                    "cycleStatus": "EMERGENCY_EQUITY_LOCK_WAIT_MARGIN",
                    "lastAction": "EMERGENCY_EQUITY_LOCK_WAIT_MARGIN",
                    "lastReason": "Aster weigerde protection hedge wegens onvoldoende margin; trigger blijft actief en wordt later opnieuw geprobeerd",
                    "equityProtectionActive": True,
                    "equityLockRequiredMargin": lock_required_margin,
                    "equityLockAvailableMargin": lock_available_margin,
                })
                _persist(ref, state, owned)
                _audit(ref, "FOCUS_EMERGENCY_EQUITY_LOCK_WAIT_MARGIN", cycleId=state.get("cycleId"), symbol=symbol,
                    requiredMargin=lock_required_margin, availableMargin=lock_available_margin, exchangeError=str(exc))
                return {"status": "waiting", "action": "EMERGENCY_EQUITY_LOCK_WAIT_MARGIN", "ordersSent": 0}
            if hq > 0:
                owned = _upsert_owned(
                    owned, settings=settings, cycle_id=str(state.get("cycleId")), symbol=symbol,
                    role=hedge_role, side=hedge_side, quantity=hq, price=hp,
                    client_id=hcid, order_id=hoid, dca=False, timestamp_ms=timestamp_ms,
                )
            confirmed = client.position_risk(symbol)
            confirmed_primary_qty = abs(_finite((_row(confirmed, symbol, primary_side) or {}).get("positionAmt")))
            confirmed_hedge_qty = abs(_finite((_row(confirmed, symbol, hedge_side) or {}).get("positionAmt")))
            confirmed_tolerance = max(1e-12, confirmed_primary_qty * 0.001)
            state.update({
                "hedgeState": HEDGE_ACTIVE,
                "hedgeTargetQty": confirmed_primary_qty or target_lock_qty,
                "reHedgeArmed": False, "reHedgePrice": 0.0,
                "cycleStatus": "EMERGENCY_EQUITY_PROTECTED",
                "lastAction": "EMERGENCY_EQUITY_LOCK_REHEDGED",
                "lastReason": "equity onder cycleStartEquity; ontbrekende hedge direct hersteld; DCA-trigger blijft behouden en release blijft geblokkeerd",
                "equityProtectionActive": True,
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_EMERGENCY_EQUITY_LOCK", cycleId=state.get("cycleId"), symbol=symbol,
                currentEquity=current_equity, cycleStartEquity=cycle_start_equity,
                longQty=confirmed_primary_qty, shortQty=confirmed_hedge_qty)
            if confirmed_primary_qty <= 0 or abs(confirmed_primary_qty - confirmed_hedge_qty) > confirmed_tolerance:
                return {"status": "reconciling", "action": "EMERGENCY_EQUITY_LOCK_REHEDGE_PENDING", "ordersSent": 1}
            return {"status": "executed", "action": "EMERGENCY_EQUITY_LOCK_REHEDGED", "ordersSent": 1}
        legacy_lock_state = str(state.get("cycleStatus") or "") in {
            "EMERGENCY_EQUITY_LOCK", "EMERGENCY_EQUITY_LOCK_WAIT_BUDGET"
        } or str(state.get("lastAction") or "") == "EMERGENCY_EQUITY_LOCK_HOLD"
        if legacy_lock_state and not bool(state.get("equityDcaRearmedAfterLock", False)):
            # One-time migration for cycles that were frozen by the old emergency lock.
            # Do NOT backfill missed historical DCA orders at the current market price.
            # Re-arm from the current mark so only the NEXT configured 0.3% drop buys.
            fresh_next = next_dca_from_anchor(mark, primary_side, dca_ratio)
            state.update({
                "trailingHigh": mark if primary_side == "LONG" else _finite(state.get("trailingHigh")),
                "trailingLow": mark if primary_side == "SHORT" else _finite(state.get("trailingLow")),
                "dcaAnchorPrice": mark, "nextDcaPrice": fresh_next, "dcaMode": DCA_TRAILING,
                "dcaTriggerPending": False, "dcaTriggerPrice": 0.0, "dcaTriggerMarkPrice": 0.0, "dcaTriggerAtMs": 0,
                "equityDcaRearmedAfterLock": True, "equityDcaRearmedAtPrice": mark,
                "hedgeState": HEDGE_ACTIVE, "hedgeTargetQty": target_lock_qty,
                "reHedgeArmed": False, "reHedgePrice": 0.0,
                "cycleStatus": "EMERGENCY_EQUITY_PROTECTED",
                "lastAction": "EMERGENCY_EQUITY_DCA_REARMED",
                "lastReason": "oude equity-lock opgeheven voor DCA; geen gemiste orders ingehaald; volgende 0,3% daling koopt LONG en synchroniseert SHORT 1:1",
                "equityProtectionActive": True,
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_EQUITY_DCA_REARMED", cycleId=state.get("cycleId"), symbol=symbol, markPrice=mark, nextDcaPrice=fresh_next)
            return {"status": "holding", "action": "EMERGENCY_EQUITY_DCA_REARMED", "ordersSent": 0, "nextDcaPrice": fresh_next}
        state.update({
            "hedgeState": HEDGE_ACTIVE,
            "hedgeTargetQty": target_lock_qty,
            "reHedgeArmed": False, "reHedgePrice": 0.0,
            "cycleStatus": "EMERGENCY_EQUITY_PROTECTED",
            "lastAction": "EMERGENCY_EQUITY_PROTECTED",
            "lastReason": "equity onder cycleStartEquity; 1:1 hedge vasthouden; normale DCA blijft actief; verliesgevende SHORT-release blijft geblokkeerd",
            "equityProtectionActive": True,
        })
        _persist(ref, state, owned)
        # Intentionally continue into normal DCA evaluation below.

    # v8 core flow: no DCA in Simple Mode. The original primary position is the
    # earning leg; the hedge only protects while price searches for a bottom/top.
    # While hedged we trail the most adverse protected extreme. A rebound of the
    # configured recovery ratio may release the hedge only when the exact close is
    # net green and its released margin can finance a full 1:1 re-hedge.
    if simple_flow:
        state["dcaMode"] = "OFF_CORE_V8"
        state["nextDcaPrice"] = 0.0
        state["dcaTriggerPending"] = False
        state["dcaTriggerPrice"] = 0.0
        state["dcaTriggerMarkPrice"] = 0.0
        if hedge_qty > 1e-12:
            if primary_side == "LONG":
                previous_extreme = _finite(state.get("protectedFloorPrice"))
                protected_extreme = min(previous_extreme, mark) if previous_extreme > 0 else mark
                state["protectedFloorPrice"] = protected_extreme
                state["protectedCeilingPrice"] = 0.0
                state["hedgeReleasePrice"] = protected_extreme * (1.0 + release_ratio)
            else:
                previous_extreme = _finite(state.get("protectedCeilingPrice"))
                protected_extreme = max(previous_extreme, mark) if previous_extreme > 0 else mark
                state["protectedCeilingPrice"] = protected_extreme
                state["protectedFloorPrice"] = 0.0
                state["hedgeReleasePrice"] = protected_extreme * (1.0 - release_ratio)
            state["reHedgeAnchorPrice"] = protected_extreme
            state["hedgeTargetQty"] = primary_qty

    # v8 post-release re-hedge: once the hedge is confirmed flat, the trigger is
    # the exact protected bottom/top that caused the release. No additional 0.3%
    # give-back is allowed.
    rehedge_price = _finite(state.get("reHedgePrice"))
    rehedge_crossed = bool(
        simple_flow and hedge_qty <= 1e-12 and state.get("reHedgeArmed") and rehedge_price > 0 and
        ((mark <= rehedge_price) if primary_side == "LONG" else (mark >= rehedge_price))
    )
    if rehedge_crossed:
        rehedge_detected_ms = int(time.time() * 1000)
        state["reHedgeTriggerDetectedAt"] = rehedge_detected_ms
        if order_budget is not None and order_budget < 1:
            return {"status": "budget-exhausted", "action": "REHEDGE_WAIT_BUDGET", "ordersSent": 0}
        leverage = _resolved_leverage(client, settings, symbol, primary_row)
        target_qty = primary_qty
        if target_qty <= 1e-12:
            return {"status": "waiting", "action": "REHEDGE_WAIT_PRIMARY", "ordersSent": 0}
        rehedge_required_margin_live = (target_qty * mark) / max(1, leverage)
        rehedge_available_live = max(0.0, _finite(account.get("availableBalance")))
        if rehedge_required_margin_live > rehedge_available_live + 1e-9:
            state.update({
                "cycleStatus": "REHEDGE_WAIT_MARGIN",
                "lastAction": "REHEDGE_WAIT_MARGIN",
                "lastReason": "re-hedge trigger geraakt maar actuele Aster available margin is nog onvoldoende; trigger blijft armed",
                "reHedgeArmed": True,
                "reHedgePrice": rehedge_price,
                "rehedgeRequiredMargin": rehedge_required_margin_live,
                "rehedgeAvailableMargin": rehedge_available_live,
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_REHEDGE_WAIT_MARGIN", cycleId=state.get("cycleId"), symbol=symbol,
                reHedgePrice=rehedge_price, requiredMargin=rehedge_required_margin_live, availableMargin=rehedge_available_live)
            return {
                "status": "waiting", "action": "REHEDGE_WAIT_MARGIN", "ordersSent": 0,
                "reHedgePrice": rehedge_price, "requiredMargin": rehedge_required_margin_live,
                "availableMargin": rehedge_available_live,
            }
        rehedge_submit_ms = int(time.time() * 1000)
        state["reHedgeOrderSubmittedAt"] = rehedge_submit_ms
        state["reHedgeTriggerToSubmitMs"] = max(0, rehedge_submit_ms - rehedge_detected_ms)
        hq, hp, hcid, hoid = _execute_with_precision_retry(
            client=client, symbol=symbol, mark=mark, notional=target_qty * mark, leverage=leverage,
            side=hedge_side, action="OPEN", prefix=_prefix(str(state.get("cycleId")), int(_finite(state.get("dcaCount"))), "REHEDGE"),
            new_position_leverage=leverage,
        )
        owned = _upsert_owned(owned, settings=settings, cycle_id=str(state.get("cycleId")), symbol=symbol, role=hedge_role,
            side=hedge_side, quantity=hq, price=hp, client_id=hcid, order_id=hoid, dca=False, timestamp_ms=timestamp_ms)
        confirmed = client.position_risk(symbol)
        confirmed_primary_qty = abs(_finite((_row(confirmed, symbol, primary_side) or {}).get("positionAmt")))
        confirmed_hedge_qty = abs(_finite((_row(confirmed, symbol, hedge_side) or {}).get("positionAmt")))
        tolerance = max(1e-12, confirmed_primary_qty * 0.001)
        if confirmed_primary_qty <= 0 or abs(confirmed_primary_qty - confirmed_hedge_qty) > tolerance:
            state.update({
                "cycleStatus": "DCA_HEDGE_SYNC_PENDING", "hedgeState": HEDGE_ACTIVE,
                "hedgeTargetQty": confirmed_primary_qty or target_qty, "reHedgeArmed": False, "reHedgePrice": 0.0,
                "lastAction": "REHEDGE_SYNC_PENDING",
                "lastReason": "re-hedge fill ontvangen maar Aster quantities nog niet 1:1; bestaande hedge-sync recovery maakt dit af",
            })
            _persist(ref, state, owned)
            return {"status": "reconciling", "action": "REHEDGE_SYNC_PENDING", "ordersSent": 1}
        protected_extreme = min(rehedge_price, mark) if primary_side == "LONG" else max(rehedge_price, mark)
        state.update({
            "hedgeState": HEDGE_ACTIVE, "hedgeTargetQty": confirmed_primary_qty,
            "protectedFloorPrice": protected_extreme if primary_side == "LONG" else 0.0,
            "protectedCeilingPrice": protected_extreme if primary_side == "SHORT" else 0.0,
            "reHedgeAnchorPrice": protected_extreme,
            "hedgeReleasePrice": protected_extreme * (1.0 + release_ratio) if primary_side == "LONG" else protected_extreme * (1.0 - release_ratio),
            "reHedgeArmed": False, "reHedgePrice": 0.0, "cycleStatus": "HEDGED",
            "lastHedgeEntryOrderId": hoid, "lastAction": "REHEDGE_ACTIVE",
            "lastReason": "koers keerde terug naar beschermde bodem/top; hedge opnieuw exact 1:1 en bodem/top-tracking hervat",
            "reHedgeConfirmedAt": int(time.time() * 1000),
        })
        _persist(ref, state, owned)
        _audit(ref, "FOCUS_REHEDGE_ACTIVE", cycleId=state.get("cycleId"), symbol=symbol, reHedgePrice=rehedge_price,
            longQty=confirmed_primary_qty, shortQty=confirmed_hedge_qty)
        return {"status": "executed", "action": "FOCUS_REHEDGE_ACTIVE", "symbol": symbol, "ordersSent": 1}

    # DCA is the ONLY re-hedge point: LONG DCA first, then SHORT sync to total LONG.
    if dca_allowed and dca_triggered:
        if order_budget is not None and order_budget < 2:
            reason = {"reason": "ORDER_BUDGET", "markPrice": mark, "nextDcaPrice": next_dca, "orderBudget": order_budget, "dcaTriggerPending": bool(dca_trigger_pending)}
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
        required_margin_base = (dca_notional + hedge_gap) / max(1, leverage)
        required_margin = required_margin_base * (1.0 + reserve_buffer_pct)
        available = _finite(account.get("availableBalance"))
        if required_margin > available or maint >= settings.emergency_margin_ratio or liq_distance < 0.05:
            block_reason = "INSUFFICIENT_MARGIN" if required_margin > available else ("EMERGENCY_MARGIN_RATIO" if maint >= settings.emergency_margin_ratio else "LIQUIDATION_DISTANCE")
            if block_reason == "INSUFFICIENT_MARGIN" and simple_flow:
                state.update({
                    "cycleStatus": "DCA_PROTECTION_MARGIN_BLOCKED",
                    "lastAction": "DCA_PROTECTION_MARGIN_BLOCKED",
                    "lastReason": "DCA-crossing blijft pending: volledige LONG DCA + SHORT refill + buffer is nog niet financierbaar",
                    "protectionReserveRequired": required_margin,
                    "protectionReserveAvailable": available,
                    "protectionReserveReady": False,
                    "protectionReserveShortfall": max(0.0, required_margin - available),
                })
                _persist(ref, state, owned)
            reason = {
                "reason": block_reason, "markPrice": mark, "nextDcaPrice": next_dca,
                "dcaEnabled": bool(settings.focus_dca_enabled), "dcaCount": current_count,
                "maxDca": settings.focus_max_dca, "dcaUnlimited": bool(settings.focus_dca_unlimited),
                "orderBudget": order_budget, "requiredMargin": required_margin, "requiredMarginBeforeBuffer": required_margin_base, "availableMargin": available,
                "protectionReserveBufferPct": reserve_buffer_pct,
                "maintenanceRatio": maint, "liquidationDistance": liq_distance,
                "dcaNotional": dca_notional, "hedgeGapNotional": hedge_gap,
            }
            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)
            action = "DCA_PROTECTION_MARGIN_BLOCKED" if simple_flow and block_reason == "INSUFFICIENT_MARGIN" else "FOCUS_DCA_BLOCKED"
            return {"status": "waiting", "action": action, "ordersSent": 0, **reason}

        cycle_no = current_count + 1
        submit_ms = int(time.time() * 1000)
        trigger_ms = int(_finite(state.get("dcaTriggerDetectedAt"), _finite(state.get("dcaTriggerAtMs"), timestamp_ms)))
        state.update({
            "dcaLongOrderSubmittedAt": submit_ms,
            "triggerToLongSubmitMs": max(0, submit_ms - trigger_ms),
        })
        dca_prefix = _prefix(str(state["cycleId"]), cycle_no, "DCA_ENTRY")
        q, p, cid, oid = _execute_with_precision_retry(
            client=client, symbol=symbol, mark=mark, notional=dca_notional, leverage=leverage,
            side=primary_side, action="OPEN", prefix=dca_prefix, new_position_leverage=leverage,
        )
        long_fill_confirmed_ms = int(time.time() * 1000)
        state["dcaLongFillConfirmedAt"] = long_fill_confirmed_ms
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
                short_submit_ms = int(time.time() * 1000)
                state.update({
                    "shortSyncSubmittedAt": short_submit_ms,
                    "longFillToShortSubmitMs": max(0, short_submit_ms - long_fill_confirmed_ms),
                })
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
                "dcaCount": cycle_no, "dcaMode": DCA_TRAILING if simple_flow else DCA_FROZEN, "hedgeState": HEDGE_ACTIVE,
                "lastDcaFillPrice": p, "trailingHigh": p if primary_side == "LONG" else _finite(state.get("trailingHigh")), "trailingLow": p if primary_side == "SHORT" else _finite(state.get("trailingLow")), "dcaAnchorPrice": p, "nextDcaPrice": next_dca_from_anchor(p, primary_side, dca_ratio),
                "dcaTriggerPending": False, "dcaTriggerPrice": 0.0, "dcaTriggerMarkPrice": 0.0, "dcaTriggerAtMs": 0,
                "hedgeReleasePrice": 0.0, "hedgeTargetQty": target_qty_after,
                "shortNetGreenReleasePrice": 0.0,
                "reHedgeArmed": False, "reHedgePrice": 0.0,
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
        post_sync_positions = client.position_risk(symbol)
        short_confirmed_ms = int(time.time() * 1000)
        state.update({
            "shortSyncConfirmedAt": short_confirmed_ms,
            "triggerToFullHedgeMs": max(0, short_confirmed_ms - trigger_ms),
        })
        post_primary = _row(post_sync_positions, symbol, primary_side)
        post_hedge = _row(post_sync_positions, symbol, hedge_side)
        post_primary_qty = abs(_finite((post_primary or {}).get("positionAmt")))
        post_hedge_qty = abs(_finite((post_hedge or {}).get("positionAmt")))
        post_tolerance = max(1e-12, post_primary_qty * 0.001)
        if simple_flow and (post_primary_qty <= 0 or abs(post_primary_qty - post_hedge_qty) > post_tolerance):
            state.update({
                "weightedEntry": _finite((post_primary or {}).get("entryPrice"), p),
                "dcaCount": cycle_no, "dcaMode": DCA_TRAILING if simple_flow else DCA_FROZEN, "hedgeState": HEDGE_ACTIVE,
                "lastDcaFillPrice": p, "trailingHigh": p if primary_side == "LONG" else _finite(state.get("trailingHigh")), "trailingLow": p if primary_side == "SHORT" else _finite(state.get("trailingLow")), "dcaAnchorPrice": p, "nextDcaPrice": next_dca_from_anchor(p, primary_side, dca_ratio),
                "dcaTriggerPending": False, "dcaTriggerPrice": 0.0, "dcaTriggerMarkPrice": 0.0, "dcaTriggerAtMs": 0,
                "hedgeReleasePrice": 0.0, "hedgeTargetQty": post_primary_qty or target_qty_after,
                "shortNetGreenReleasePrice": 0.0,
                "reHedgeArmed": False, "reHedgePrice": 0.0,
                "cycleStatus": "DCA_HEDGE_SYNC_PENDING", "lastAction": "DCA_HEDGE_SYNC_PENDING",
                "lastReason": "DCA + SHORT fill bevestigd maar Aster quantities nog niet 1:1; volgende realtime tick herstellen",
                "lastDcaOrderId": oid, "lastHedgeEntryOrderId": hoid,
            })
            _persist(ref, state, owned)
            _audit(ref, "FOCUS_DCA_HEDGE_SYNC_PENDING", cycleId=state["cycleId"], symbol=symbol, dcaCount=cycle_no, longQty=post_primary_qty, shortQty=post_hedge_qty)
            return {"status": "reconciling", "action": "DCA_HEDGE_SYNC_PENDING", "symbol": symbol, "ordersSent": 2 if hq > 0 else 1, "longQty": post_primary_qty, "shortQty": post_hedge_qty}
        new_qty = post_primary_qty or (primary_qty + q)
        entry = _finite((primary_row or {}).get("entryPrice"), _finite(state.get("weightedEntry"), p))
        new_entry = ((primary_qty * entry) + (q * p)) / max(new_qty, 1e-12)
        next_dca_after_fill = next_dca_from_anchor(p, primary_side, dca_ratio)
        release_price = release_price_from_last_dca(p, primary_side, release_ratio)
        state.update({
            "weightedEntry": new_entry,
            "dcaCount": cycle_no,
            "dcaMode": DCA_TRAILING if simple_flow else DCA_FROZEN,
            "hedgeState": HEDGE_ACTIVE,
            "frozenDcaReference": 0.0,
            "lastDcaFillPrice": p,
            "trailingHigh": p if primary_side == "LONG" else _finite(state.get("trailingHigh")),
            "trailingLow": p if primary_side == "SHORT" else _finite(state.get("trailingLow")),
            "dcaAnchorPrice": p,
            "nextDcaPrice": next_dca_after_fill,
            "dcaTriggerPending": False, "dcaTriggerPrice": 0.0, "dcaTriggerMarkPrice": 0.0, "dcaTriggerAtMs": 0,
            "hedgeReleasePrice": release_price,
            "hedgeTargetQty": target_qty_after,
            "shortReleasePriceReady": False, "shortReleaseNetGreenReady": False, "expectedNetShortClosePnl": 0.0,
            "shortNetGreenReleasePrice": 0.0,
                "reHedgeArmed": False, "reHedgePrice": 0.0,
            "dcaAnchorPrice": p,
            "hedgeCycleId": f"{state['cycleId']}-dca-{cycle_no}",
            "lastDcaOrderId": oid,
            "lastHedgeEntryOrderId": hoid,
            "cycleStatus": "HEDGED",
            "lastAction": "DCA_HEDGE_SYNCED",
            "lastReason": "DCA geraakt: LONG bevestigd en SHORT naar totale LONG-quantity gesynchroniseerd",
            "stateMachineVersion": 7,
        })
        _persist(ref, state, owned, focusV2History=_history(
            state, mark=p, dca_ratio=dca_ratio, release_ratio=release_ratio,
            primary_notional=actual_primary_after, hedge_notional=fresh_hedge_notional + hq*hp,
            primary_pnl=primary_pnl, hedge_pnl=hedge_pnl,
        ))
        _audit(ref, "FOCUS_V2_TRAILING_DCA_HEDGE", cycleId=state["cycleId"], symbol=symbol, dcaCount=cycle_no, lastDcaFill=p, nextDca=next_dca_after_fill, hedgeReleasePrice=release_price, hedgeTarget=target_after, hedgeTargetQty=target_qty_after)
        return {"status": "executed", "action": "FOCUS_V2_DCA_HEDGE_ACTIVE", "symbol": symbol, "ordersSent": 2 if hq > 0 else 1, "dcaCount": cycle_no, "lastDcaFillPrice": p, "nextDcaPrice": next_dca_after_fill, "hedgeReleasePrice": release_price, "hedgeTargetQty": target_qty_after}

    # v7 protected SHORT release. The configured recovery is only the earliest point
    # at which a release may be considered. The exact hedge being reduced/closed must
    # also be net profitable after the existing conservative round-trip fee/slippage
    # model, and account equity may not be below the persisted cycle baseline.
    # This makes a red hedge close server-side impossible in simple portfolio-cycle mode.
    if hedge_qty > 1e-12:
        last_dca = _finite(state.get("lastDcaFillPrice"))
        if simple_flow:
            protected_extreme = _finite(state.get("protectedFloorPrice")) if primary_side == "LONG" else _finite(state.get("protectedCeilingPrice"))
            if protected_extreme <= 0:
                protected_extreme = mark
                state["protectedFloorPrice" if primary_side == "LONG" else "protectedCeilingPrice"] = protected_extreme
            release_price = protected_extreme * (1.0 + release_ratio) if primary_side == "LONG" else protected_extreme * (1.0 - release_ratio)
            state["hedgeReleasePrice"] = release_price
            state["reHedgeAnchorPrice"] = protected_extreme
            price_release_ready = hedge_release_crossed(mark, release_price, primary_side)
        else:
            protected_extreme = 0.0
            release_price = _finite(state.get("hedgeReleasePrice")) or (release_price_from_last_dca(last_dca, primary_side, release_ratio) if last_dca > 0 else 0.0)
            state["hedgeReleasePrice"] = release_price
            price_release_ready = last_dca > 0 and hedge_release_crossed(mark, release_price, primary_side)
        expected_net_close_pnl, executable_close_price, gross_close_pnl, estimated_close_fees, estimated_slippage = expected_net_hedge_close_pnl(
            client, symbol, hedge_side, hedge_row, mark
        )
        net_green_ready = expected_net_close_pnl > 0.0
        # Re-hedge funding guard: before releasing protection, conservatively prove
        # that the margin freed by closing the current hedge plus current available
        # balance can fund the full hedge again at the persisted last-DCA anchor.
        release_leverage = max(1, int(_finite((hedge_row or {}).get("leverage"), settings.leverage)))
        rehedge_anchor = protected_extreme if simple_flow and protected_extreme > 0 else (last_dca if last_dca > 0 else mark)
        rehedge_target_notional = primary_qty * rehedge_anchor
        rehedge_required_margin = rehedge_target_notional / release_leverage
        released_hedge_margin_estimate = hedge_notional / release_leverage
        rehedge_available_after_release = max(0.0, _finite(account.get("availableBalance"))) + released_hedge_margin_estimate
        rehedge_funding_ready = bool(
            rehedge_target_notional > 0 and
            rehedge_available_after_release + 1e-9 >= rehedge_required_margin
        )
        state["releaseRehedgeMarginReady"] = rehedge_funding_ready
        state["releaseRehedgeRequiredMargin"] = rehedge_required_margin
        state["releaseRehedgeAvailableAfterCloseEstimate"] = rehedge_available_after_release
        state["shortReleasePriceReady"] = bool(price_release_ready)
        state["shortReleaseNetGreenReady"] = bool(net_green_ready)
        state["expectedNetShortClosePnl"] = expected_net_close_pnl
        state["shortNetGreenReleasePrice"] = net_green_hedge_release_price(hedge_row, hedge_side)
        if price_release_ready and net_green_ready and rehedge_funding_ready:
            release_detected_ms = int(time.time() * 1000)
            state["hedgeReleaseTriggerDetectedAt"] = release_detected_ms
            if order_budget is not None and order_budget < 1:
                return {"status": "budget-exhausted", "action": "FOCUS_V2_WAIT_HEDGE_RELEASE", "ordersSent": 0}
            release_submit_ms = int(time.time() * 1000)
            state.update({"hedgeState": HEDGE_RELEASE_EXECUTING, "cycleStatus": "HEDGE_RELEASE_EXECUTING",
                "hedgeReleaseOrderSubmittedAt": release_submit_ms,
                "hedgeReleaseTriggerToSubmitMs": max(0, release_submit_ms - release_detected_ms)})
            _persist(ref, state, owned)
            leverage = int(_finite((hedge_row or {}).get("leverage"), settings.leverage))
            cq, cp, _ccid, coid = _execute_with_precision_retry(
                client=client, symbol=symbol, mark=mark, notional=hedge_qty * mark, leverage=leverage,
                side=hedge_side, action="CLOSE", prefix=_prefix(str(state["cycleId"]), int(_finite(state.get("dcaCount"))), "HEDGE_RELEASE"),
            )
            confirmed_positions = client.position_risk(symbol)
            confirmed_hedge = _row(confirmed_positions, symbol, hedge_side)
            remaining_hedge_qty = abs(_finite((confirmed_hedge or {}).get("positionAmt")))
            if remaining_hedge_qty > max(1e-12, hedge_qty * 0.001):
                state.update({
                    "hedgeState": HEDGE_RELEASE_EXECUTING, "lastHedgeReleaseOrderId": coid,
                    "lastAction": "HEDGE_RELEASE_EXECUTING",
                    "lastReason": "net-groene reduce-only release verzonden; Aster bevestigt nog resterende SHORT",
                })
                _persist(ref, state, owned)
                return {"status": "reconciling", "action": "FOCUS_V2_HEDGE_RELEASE_EXECUTING", "symbol": symbol, "ordersSent": 1, "hedgeRemainingQty": remaining_hedge_qty}
            owned = _reduce_owned(owned, hedge_role, cq, timestamp_ms)
            anchor = cp if cp > 0 else mark
            trailing_anchor = max(_finite(state.get("trailingHigh"), anchor), anchor) if primary_side == "LONG" else (min(_finite(state.get("trailingLow"), anchor), anchor) if _finite(state.get("trailingLow")) > 0 else anchor)
            state.update({
                "dcaMode": DCA_TRAILING, "hedgeState": HEDGE_OFF, "frozenDcaReference": 0.0,
                "hedgeCycleId": "", "hedgeReleasePrice": 0.0, "hedgeTargetQty": 0.0,
                "shortReleasePriceReady": False, "shortReleaseNetGreenReady": False, "expectedNetShortClosePnl": 0.0,
                "shortNetGreenReleasePrice": 0.0,
                "trailingHigh": trailing_anchor if primary_side == "LONG" else _finite(state.get("trailingHigh")),
                "trailingLow": trailing_anchor if primary_side == "SHORT" else _finite(state.get("trailingLow")),
                "dcaAnchorPrice": trailing_anchor, "nextDcaPrice": 0.0 if simple_flow else next_dca_from_anchor(trailing_anchor, primary_side, dca_ratio),
                "reHedgeArmed": (protected_extreme > 0 if simple_flow else last_dca > 0),
                "reHedgePrice": protected_extreme if simple_flow and protected_extreme > 0 else (last_dca if last_dca > 0 else 0.0),
                "lastHedgeReleaseOrderId": coid, "cycleStatus": "LONG_ONLY",
                "lastAction": "HEDGE_RELEASED_NET_GREEN",
                "lastReason": "rebound vanaf beschermde bodem/top geraakt en hedge netto groen; hedge gesloten en re-hedge exact op bodem/top gewapend" if simple_flow else "release-afstand geraakt en SHORT netto groen na kostenbuffer; volledige SHORT gesloten en re-hedge gewapend",
                "hedgeReleaseConfirmedAt": int(time.time() * 1000),
                "stateMachineVersion": 8 if simple_flow else 7,
            })
            _persist(ref, state, owned, focusV2History=_history(
                state, mark=anchor, dca_ratio=dca_ratio, release_ratio=release_ratio,
                primary_notional=primary_notional, hedge_notional=0.0, primary_pnl=primary_pnl, hedge_pnl=0.0,
            ))
            _audit(ref, "FOCUS_HEDGE_RELEASED_NET_GREEN", cycleId=state["cycleId"], symbol=symbol,
                lastDcaFill=last_dca, releasePrice=release_price, closeQty=cq, closePrice=cp,
                executableClosePrice=executable_close_price, grossClosePnl=gross_close_pnl, estimatedCloseFees=estimated_close_fees,
                estimatedSlippage=estimated_slippage, expectedNetShortClosePnl=expected_net_close_pnl, reHedgePrice=state.get("reHedgePrice"), protectedExtreme=protected_extreme)
            return {
                "status": "executed", "action": "FOCUS_HEDGE_RELEASED_NET_GREEN", "symbol": symbol,
                "ordersSent": 1, "reHedgePrice": state.get("reHedgePrice"), "shortOrLongHedgeRemaining": 0.0,
            }
        if simple_flow:
            state.update({
                "cycleStatus": "HEDGED", "lastAction": "HEDGE_HOLD_PROTECTED_RELEASE",
                "lastReason": ("releaseprijs nog niet geraakt" if not price_release_ready else
                    ("SHORT nog niet netto groen na kostenbuffer" if not net_green_ready else
                     ("re-hedge na release niet financierbaar met beschikbare + vrijvallende SHORT-margin" if not rehedge_funding_ready else
                      "release wacht op uitvoerbare voorwaarden"))),
                "hedgeReleasePrice": release_price,
            })

    # Legacy non-simple Focus TP only. Simple v7 exits exclusively on portfolio equity above.
    if (not simple_flow) and hedge_qty <= 1e-12 and take_profit_reached(settings, primary_pnl, primary_notional):
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
                "autoRestart": True, "cycleStatus": "RESTARTING", "tpMode": tp_mode, "tpValue": tp_value, "stateMachineVersion": 7}
            _persist(ref, restarting, remaining_owned, focusV2LastCycle=last_cycle)
        else:
            paused = {"cycleId": "", "symbol": symbol, "primarySide": primary_side, "pausedAfterTp": True,
                "autoRestart": False, "cycleStatus": "TP_CLOSED", "tpMode": tp_mode, "tpValue": tp_value, "stateMachineVersion": 7}
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
        "shortReleasePriceReady": bool(state.get("shortReleasePriceReady", False)), "shortReleaseNetGreenReady": bool(state.get("shortReleaseNetGreenReady", False)),
        "expectedNetShortClosePnl": _finite(state.get("expectedNetShortClosePnl")),
        "recoverySinceLastDca": recovery_from_last_dca(mark, _finite(state.get("lastDcaFillPrice")), primary_side),
    }
