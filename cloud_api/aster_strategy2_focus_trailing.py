"""Strategy-2 Focus trailing DCA / temporary hedge state-machine.

This is the authoritative live engine for Focus 2.0 simple mode.

Contract:
- normal state is a naked primary leg (LONG by default) with a trailing DCA;
- a DCA cross opens the primary DCA and the temporary opposite hedge as one cycle;
- while the hedge is active, the *next* DCA reference is frozen;
- the hedge is fully released once price has moved the configured release distance
  away from that frozen DCA reference in the primary direction;
- after release, trailing resumes from the current price;
- partial profit only reduces the primary leg and never resets DCA state.

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
    target_hedge_notional,
)
from aster_strategy2_runtime import active_position_map, owned_from_mapping, owned_to_mapping
from aster_strategy2_state import OwnedLeg

ROLE_PRIMARY_LONG = "FOCUS_V2_LONG"
ROLE_PRIMARY_SHORT = "FOCUS_V2_SHORT"
ROLE_HEDGE_SHORT = "FOCUS_V2_HEDGE"
ROLE_HEDGE_LONG = "FOCUS_V2_HEDGE_LONG"
DCA_TRAILING = "TRAILING"
DCA_FROZEN = "FROZEN_FOR_HEDGE"
HEDGE_OFF = "OFF"
HEDGE_ACTIVE = "ACTIVE"


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


def hedge_release_distance(settings: Strategy2Config) -> float:
    """Current configurable hedge-release distance as a decimal ratio.

    New configs use focus_v2_hedge_release_distance_pct. Older saved settings fall
    back to the former Focus recovery rebound field so active accounts migrate
    without losing their configured value.
    """
    explicit = getattr(settings, "focus_v2_hedge_release_distance_pct", None)
    if explicit is not None:
        return _ratio(explicit, 0.0035)
    return _ratio(getattr(settings, "focus_v2_recovery_rebound_pct", 0.0035), 0.0035)


def next_dca_from_anchor(anchor: float, side: str, distance: float) -> float:
    if anchor <= 0 or distance <= 0:
        return 0.0
    return anchor * (1.0 - distance) if side.upper() == "LONG" else anchor * (1.0 + distance)


def dca_crossed(mark: float, next_dca: float, side: str) -> bool:
    if mark <= 0 or next_dca <= 0:
        return False
    return mark <= next_dca if side.upper() == "LONG" else mark >= next_dca


def release_distance_from_frozen(mark: float, frozen_dca: float, side: str) -> float:
    """Directional distance using live price as denominator, per product contract."""
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
    state.setdefault("frozenDcaReference", 0.0)
    state.setdefault("hedgeCycleId", "")
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


def _history(state: dict[str, Any], *, mark: float, dca_ratio: float, release_ratio: float,
             primary_notional: float, hedge_notional: float, primary_pnl: float, hedge_pnl: float) -> dict[str, Any]:
    frozen = _finite(state.get("frozenDcaReference"))
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
        "distanceToFrozenDca": release_distance_from_frozen(mark, frozen, side),
        "dcaDistancePct": dca_ratio,
        "hedgeReleaseDistancePct": release_ratio,
        "hedgeState": state.get("hedgeState", HEDGE_OFF),
        "dcaCount": int(_finite(state.get("dcaCount"))),
        "primaryNotional": primary_notional,
        "hedgeNotional": hedge_notional,
        "longNotional": primary_notional if side == "LONG" else hedge_notional,
        "shortNotional": primary_notional if side == "SHORT" else hedge_notional,
        "primaryPnl": primary_pnl,
        "hedgePnl": hedge_pnl,
        "profitTriggerUsdt": _finite(state.get("profitTriggerUsdt")),
        "profitHarvestUsdt": _finite(state.get("profitHarvestUsdt")),
        "totalHarvestedProfit": _finite(state.get("totalHarvestedProfit")),
        "lastHarvestProfit": _finite(state.get("lastHarvestProfit")),
        "stateMachineVersion": 4,
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

    primary_side = str(existing_state.get("primarySide", "") or _slot_side(settings, symbol)).upper()
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
    release_ratio = hedge_release_distance(settings)
    trigger_usdt = max(0.0, _finite(settings.focus_v2_profit_trigger_usdt))
    take_usdt = max(0.0, _finite(settings.focus_v2_profit_harvest_usdt))
    state["profitTriggerUsdt"] = trigger_usdt
    state["profitHarvestUsdt"] = take_usdt
    state["configSnapshotVersion"] = int(getattr(settings, "version", 1))
    state["dcaDistancePct"] = dca_ratio
    state["hedgeReleaseDistancePct"] = release_ratio

    primary_notional = _notional(primary_row)
    hedge_notional = _notional(hedge_row)
    primary_qty = abs(_finite((primary_row or {}).get("positionAmt")))
    hedge_qty = abs(_finite((hedge_row or {}).get("positionAmt")))

    # Existing live Focus V2 cycles are reconciled rather than blindly closed.
    if state.get("cycleId"):
        if primary_notional <= 0:
            # The primary leg is gone: clear only this engine's ownership/state.
            remaining = [x for x in owned if not str(x.role).upper().startswith("FOCUS_V2")]
            _persist(ref, {}, remaining, focusV2LastCycle={"cycleId": state.get("cycleId"), "closedAt": timestamp_ms})
            return {"status": "executed", "action": "FOCUS_V2_CYCLE_FLAT", "symbol": symbol, "ordersSent": 0}
        if hedge_qty > 1e-12:
            state["dcaMode"] = DCA_FROZEN
            state["hedgeState"] = HEDGE_ACTIVE
            if _finite(state.get("frozenDcaReference")) <= 0:
                old_anchor = _finite(state.get("dcaAnchorPrice"), mark)
                old_next = _finite(state.get("nextDcaPrice"))
                state["frozenDcaReference"] = old_next if old_next > 0 else next_dca_from_anchor(old_anchor, primary_side, dca_ratio)
                state["nextDcaPrice"] = state["frozenDcaReference"]
        else:
            state["dcaMode"] = DCA_TRAILING
            state["hedgeState"] = HEDGE_OFF
            state["frozenDcaReference"] = 0.0

    # New Focus 2.0 cycle: primary only. No hedge exists until the first DCA retracement.
    if not state.get("cycleId"):
        if order_budget is not None and order_budget < 1:
            return {"status": "budget-exhausted", "action": "FOCUS_V2_WAIT_PRIMARY_OPEN", "ordersSent": 0}
        # Never adopt an unrelated exchange position.
        focus_owned = [x for x in owned if str(x.role).upper().startswith("FOCUS")]
        if focus_owned or primary_row or hedge_row:
            return {"status": "waiting", "action": "FOCUS_V2_WAIT_FLAT", "reason": "bestaande positie wordt niet blind geadopteerd", "ordersSent": 0}
        start_notional = max(0.0, settings.focus_start_order_notional)
        if start_notional <= 0:
            raise RuntimeError("Focus 2.0 startnotional is nul")
        available = _finite(account.get("availableBalance"))
        leverage = _resolved_leverage(client, settings, symbol)
        if start_notional / max(1, leverage) > available:
            return {"status": "waiting", "action": "FOCUS_V2_MARGIN_BLOCK", "ordersSent": 0}
        cycle_id = f"focusv2t-{hashlib.sha256(f'{uid}|{symbol}|{primary_side}|{timestamp_ms}'.encode()).hexdigest()[:14]}"
        prefix = _prefix(cycle_id, 0, "PRIMARY_OPEN")
        q, p, cid, oid = _execute_with_precision_retry(
            client=client, symbol=symbol, mark=mark, notional=start_notional, leverage=leverage,
            side=primary_side, action="OPEN", prefix=prefix, new_position_leverage=leverage,
        )
        owned = _upsert_owned(
            owned, settings=settings, cycle_id=cycle_id, symbol=symbol, role=primary_role,
            side=primary_side, quantity=q, price=p, client_id=cid, order_id=oid,
            dca=False, timestamp_ms=timestamp_ms,
        )
        state.update({
            "cycleId": cycle_id, "symbol": symbol, "primarySide": primary_side,
            "cycleStartEquity": _finite(account.get("totalMarginBalance"), _finite(account.get("totalWalletBalance"))),
            "openedAt": timestamp_ms, "originalEntry": p, "weightedEntry": p,
            "dcaCount": 0, "dcaMode": DCA_TRAILING, "hedgeState": HEDGE_OFF,
            "trailingHigh": p if primary_side == "LONG" else 0.0,
            "trailingLow": p if primary_side == "SHORT" else 0.0,
            "nextDcaPrice": next_dca_from_anchor(p, primary_side, dca_ratio),
            "frozenDcaReference": 0.0, "hedgeCycleId": "",
            "lastPrimaryOrderId": oid, "lastAction": "PRIMARY_OPEN",
            "lastReason": "primaire positie geopend zonder hedge; trailing DCA actief",
            "stateMachineVersion": 4,
        })
        _persist(ref, state, owned, focusV2History=_history(
            state, mark=p, dca_ratio=dca_ratio, release_ratio=release_ratio,
            primary_notional=q*p, hedge_notional=0.0, primary_pnl=0.0, hedge_pnl=0.0,
        ))
        _audit(ref, "FOCUS_V2_TRAILING_CYCLE_STARTED", cycleId=cycle_id, symbol=symbol, primarySide=primary_side, nextDca=state["nextDcaPrice"])
        return {"status": "executed", "action": "FOCUS_V2_PRIMARY_OPEN", "symbol": symbol, "ordersSent": 1, "cycleId": cycle_id}

    # Re-read current state values for active cycle.
    primary_pnl = _long_or_short_pnl(primary_row, mark, primary_side)
    hedge_pnl = _long_or_short_pnl(hedge_row, mark, hedge_side)

    # In LONG_ONLY_TRAILING the high/low and next DCA move on every fresh extreme.
    if hedge_qty <= 1e-12:
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
        state["hedgeState"] = HEDGE_OFF
        state["frozenDcaReference"] = 0.0
    else:
        # While the hedge is active the next DCA is intentionally frozen.
        frozen = _finite(state.get("frozenDcaReference"))
        if frozen <= 0:
            anchor = _finite(state.get("dcaAnchorPrice"), mark)
            frozen = next_dca_from_anchor(anchor, primary_side, dca_ratio)
            state["frozenDcaReference"] = frozen
        state["nextDcaPrice"] = frozen
        state["dcaMode"] = DCA_FROZEN
        state["hedgeState"] = HEDGE_ACTIVE

    next_dca = _finite(state.get("nextDcaPrice"))
    dca_allowed = settings.focus_dca_enabled and (settings.focus_dca_unlimited or int(_finite(state.get("dcaCount"))) < settings.focus_max_dca)

    # DCA has priority on renewed downside/upside-against-primary, including while hedge is active.
    if dca_allowed and dca_crossed(mark, next_dca, primary_side):
        if order_budget is not None and order_budget < 2:
            return {"status": "budget-exhausted", "action": "FOCUS_V2_WAIT_DCA_HEDGE", "ordersSent": 0}
        current_count = int(_finite(state.get("dcaCount")))
        used = primary_notional
        remaining_budget = max(0.0, settings.focus_max_budget_usd - used)
        dca_notional = _dca_notional(settings, current_count, remaining_budget)
        if dca_notional <= 0:
            return {"status": "waiting", "action": "FOCUS_V2_DCA_BUDGET_BLOCK", "ordersSent": 0}
        equity = _finite(account.get("totalMarginBalance"), _finite(account.get("totalWalletBalance")))
        maint = _finite(account.get("totalMaintMargin")) / equity if equity > 0 else 1.0
        liq = _finite((primary_row or {}).get("liquidationPrice"))
        liq_distance = abs(mark - liq) / mark if liq > 0 else 1.0
        leverage = _resolved_leverage(client, settings, symbol, primary_row)
        expected_primary_after = primary_notional + dca_notional
        hedge_target = target_hedge_notional(
            expected_primary_after,
            min_bias_usdt=settings.focus_v2_min_net_long_usdt,
            min_bias_ratio=settings.focus_v2_min_net_long_ratio,
            max_hedge_ratio=settings.focus_v2_max_hedge_ratio,
        )
        hedge_gap = max(0.0, hedge_target - hedge_notional)
        required_margin = (dca_notional + hedge_gap) / max(1, leverage)
        available = _finite(account.get("availableBalance"))
        if required_margin > available or maint >= settings.emergency_margin_ratio or liq_distance < 0.05:
            return {"status": "waiting", "action": "FOCUS_V2_DCA_RISK_BLOCK", "ordersSent": 0}

        cycle_no = current_count + 1
        dca_prefix = _prefix(str(state["cycleId"]), cycle_no, "DCA_ENTRY")
        q, p, cid, oid = _execute_with_precision_retry(
            client=client, symbol=symbol, mark=mark, notional=dca_notional, leverage=leverage,
            side=primary_side, action="OPEN", prefix=dca_prefix, new_position_leverage=leverage,
        )
        actual_primary_after = primary_notional + q * p
        target_after = target_hedge_notional(
            actual_primary_after,
            min_bias_usdt=settings.focus_v2_min_net_long_usdt,
            min_bias_ratio=settings.focus_v2_min_net_long_ratio,
            max_hedge_ratio=settings.focus_v2_max_hedge_ratio,
        )
        fresh_positions = client.position_risk(symbol)
        fresh_hedge = _row(fresh_positions, symbol, hedge_side)
        fresh_hedge_notional = _notional(fresh_hedge)
        gap = max(0.0, target_after - fresh_hedge_notional)
        hq = hp = 0.0
        hcid = hoid = ""
        try:
            if gap > max(1.0, actual_primary_after * 0.002):
                hedge_prefix = _prefix(str(state["cycleId"]), cycle_no, "HEDGE_ENTRY")
                hq, hp, hcid, hoid = _execute_with_precision_retry(
                    client=client, symbol=symbol, mark=p, notional=gap, leverage=leverage,
                    side=hedge_side, action="OPEN", prefix=hedge_prefix, new_position_leverage=leverage,
                )
        except Exception:
            rollback_prefix = _prefix(str(state["cycleId"]), cycle_no, "DCA_ROLLBACK")
            _execute_with_precision_retry(
                client=client, symbol=symbol, mark=p, notional=q*p, leverage=leverage,
                side=primary_side, action="CLOSE", prefix=rollback_prefix,
            )
            _audit(ref, "FOCUS_V2_TRAILING_DCA_ROLLBACK", cycleId=state["cycleId"], symbol=symbol, reason="tijdelijke hedge kon niet bevestigd worden")
            raise

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
        frozen = next_dca_from_anchor(p, primary_side, dca_ratio)
        state.update({
            "weightedEntry": new_entry,
            "dcaCount": cycle_no,
            "dcaMode": DCA_FROZEN,
            "hedgeState": HEDGE_ACTIVE,
            "frozenDcaReference": frozen,
            "nextDcaPrice": frozen,
            "dcaAnchorPrice": p,
            "hedgeCycleId": f"{state['cycleId']}-dca-{cycle_no}",
            "lastDcaOrderId": oid,
            "lastHedgeEntryOrderId": hoid,
            "lastAction": "DCA_HEDGE_ACTIVE",
            "lastReason": "DCA geraakt: primary DCA + tijdelijke hedge bevestigd; volgende DCA frozen",
        })
        _persist(ref, state, owned, focusV2History=_history(
            state, mark=p, dca_ratio=dca_ratio, release_ratio=release_ratio,
            primary_notional=actual_primary_after, hedge_notional=fresh_hedge_notional + hq*hp,
            primary_pnl=primary_pnl, hedge_pnl=hedge_pnl,
        ))
        _audit(ref, "FOCUS_V2_TRAILING_DCA_HEDGE", cycleId=state["cycleId"], symbol=symbol, dcaCount=cycle_no, frozenDca=frozen, hedgeTarget=target_after)
        return {"status": "executed", "action": "FOCUS_V2_DCA_HEDGE_ACTIVE", "symbol": symbol, "ordersSent": 2 if hq > 0 else 1, "dcaCount": cycle_no, "frozenDcaReference": frozen}

    # With an active hedge, release 100% once the configurable distance from the frozen next-DCA is met.
    if hedge_qty > 1e-12:
        frozen = _finite(state.get("frozenDcaReference"))
        distance = release_distance_from_frozen(mark, frozen, primary_side)
        if distance >= release_ratio:
            if order_budget is not None and order_budget < 1:
                return {"status": "budget-exhausted", "action": "FOCUS_V2_WAIT_HEDGE_RELEASE", "ordersSent": 0}
            leverage = int(_finite((hedge_row or {}).get("leverage"), settings.leverage))
            release_prefix = _prefix(str(state["cycleId"]), int(_finite(state.get("dcaCount"))), "HEDGE_RELEASE")
            cq, cp, ccid, coid = _execute_with_precision_retry(
                client=client, symbol=symbol, mark=mark, notional=hedge_qty*mark,
                leverage=leverage, side=hedge_side, action="CLOSE", prefix=release_prefix,
            )
            owned = _reduce_owned(owned, hedge_role, cq, timestamp_ms)
            # Resume trailing from the current release price; do not resurrect an old high/low.
            anchor = cp if cp > 0 else mark
            state.update({
                "dcaMode": DCA_TRAILING,
                "hedgeState": HEDGE_OFF,
                "frozenDcaReference": 0.0,
                "hedgeCycleId": "",
                "trailingHigh": anchor if primary_side == "LONG" else 0.0,
                "trailingLow": anchor if primary_side == "SHORT" else 0.0,
                "dcaAnchorPrice": anchor,
                "nextDcaPrice": next_dca_from_anchor(anchor, primary_side, dca_ratio),
                "lastHedgeReleaseOrderId": coid,
                "lastAction": "HEDGE_RELEASED",
                "lastReason": "hedge release threshold bereikt; hedge volledig weg; trailing hervat",
            })
            _persist(ref, state, owned, focusV2History=_history(
                state, mark=anchor, dca_ratio=dca_ratio, release_ratio=release_ratio,
                primary_notional=primary_notional, hedge_notional=0.0,
                primary_pnl=primary_pnl, hedge_pnl=0.0,
            ))
            _audit(ref, "FOCUS_V2_TRAILING_HEDGE_RELEASE", cycleId=state["cycleId"], symbol=symbol, releaseDistance=distance, threshold=release_ratio, closeQty=cq, closePrice=cp)
            return {"status": "executed", "action": "FOCUS_V2_HEDGE_RELEASED", "symbol": symbol, "ordersSent": 1, "releaseDistance": distance, "shortOrLongHedgeRemaining": 0.0}

    # Partial profit is only legal in primary-only state and never changes trailing/frozen DCA state.
    if hedge_qty <= 1e-12 and trigger_usdt > 0 and take_usdt > 0 and primary_pnl >= trigger_usdt:
        entry = _finite((primary_row or {}).get("entryPrice"), _finite(state.get("weightedEntry")))
        per_unit_profit = (mark - entry) if primary_side == "LONG" else (entry - mark)
        if per_unit_profit > 0:
            raw_close_qty = take_usdt / per_unit_profit
            close_qty = min(primary_qty * 0.95, raw_close_qty)
            if close_qty > 0:
                leverage = int(_finite((primary_row or {}).get("leverage"), settings.leverage))
                harvest_no = int(round(_finite(state.get("totalHarvestedProfit")) * 100))
                profit_prefix = _prefix(str(state["cycleId"]), harvest_no, "PARTIAL_PROFIT")
                cq, cp, ccid, coid = _execute_with_precision_retry(
                    client=client, symbol=symbol, mark=mark, notional=close_qty*mark,
                    leverage=leverage, side=primary_side, action="CLOSE", prefix=profit_prefix,
                )
                if cq >= primary_qty - 1e-12:
                    raise RuntimeError("Focus 2.0 partial profit mag de volledige primaire positie niet sluiten")
                owned = _reduce_owned(owned, primary_role, cq, timestamp_ms)
                realized = max(0.0, per_unit_profit * cq)
                # Preserve trailingHigh/Low, nextDcaPrice, dcaMode, frozen ref and dcaCount exactly.
                state.update({
                    "totalHarvestedProfit": _finite(state.get("totalHarvestedProfit")) + realized,
                    "lastHarvestProfit": realized,
                    "lastPartialProfitOrderId": coid,
                    "lastAction": "PARTIAL_PROFIT",
                    "lastReason": "configureerbare winst afgeroomd; DCA-state ongewijzigd",
                })
                _persist(ref, state, owned, focusV2History=_history(
                    state, mark=mark, dca_ratio=dca_ratio, release_ratio=release_ratio,
                    primary_notional=max(0.0, primary_notional-cq*mark), hedge_notional=0.0,
                    primary_pnl=max(0.0, primary_pnl-realized), hedge_pnl=0.0,
                ))
                _audit(ref, "FOCUS_V2_TRAILING_PARTIAL_PROFIT", cycleId=state["cycleId"], symbol=symbol, requestedUsd=take_usdt, realizedGrossUsd=realized, closeQty=cq, closePrice=cp)
                return {"status": "executed", "action": "FOCUS_V2_PARTIAL_PROFIT", "symbol": symbol, "ordersSent": 1, "realizedProfitUsd": realized, "cycleContinues": True}

    # Persist high/low movement and presentation state even when no order fires.
    state["lastAction"] = "HOLD"
    state["lastReason"] = "trailing/frozen state bijgewerkt; geen ordertrigger"
    _persist(ref, state, owned, focusV2History=_history(
        state, mark=mark, dca_ratio=dca_ratio, release_ratio=release_ratio,
        primary_notional=primary_notional, hedge_notional=hedge_notional,
        primary_pnl=primary_pnl, hedge_pnl=hedge_pnl,
    ))
    return {
        "status": "holding", "action": "FOCUS_V2_TRAILING_HOLD", "symbol": symbol,
        "ordersSent": 0, "dcaMode": state["dcaMode"], "hedgeState": state["hedgeState"],
        "nextDcaPrice": state["nextDcaPrice"], "frozenDcaReference": state["frozenDcaReference"],
        "distanceToFrozenDca": release_distance_from_frozen(mark, _finite(state.get("frozenDcaReference")), primary_side),
    }
