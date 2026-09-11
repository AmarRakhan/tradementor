"""Execution gate for the optional Profit Lock Ladder mode.

Profit locking has priority over ordinary Multi DCA management.  The gate can
only increase a protective SHORT.  It never reduces that SHORT during a cycle,
and the final 100% ladder target closes that symbol's LONG+SHORT cycle before a
new LONG cycle may be opened.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
import hashlib
import math

from aster_execution import PairExecutionPlan, execute_leg_once, plan_pair
from aster_gateway import PositionSide
from aster_leverage_tiers import bracket_rows
from aster_profit_lock_ladder import account_summary, ladder_decision, position_notional


@dataclass(frozen=True)
class ProfitLockGateResult:
    handled: bool
    restart: bool
    report: dict[str, Any]
    raw_state: dict[str, Any]
    account: dict[str, Any]
    positions: list[dict[str, Any]]
    open_orders: list[dict[str, Any]]
    orders_sent: int = 0


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _position_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", row.get("side", ""))).upper().strip()
        qty = abs(_f(row.get("positionAmt", row.get("quantity"))))
        if symbol and side in {"LONG", "SHORT"} and qty > 0:
            result[f"{symbol}|{side}"] = row
    return result


def _available(account: dict[str, Any]) -> float:
    for key in ("availableBalance", "availableMargin", "available", "maxWithdrawAmount"):
        if key in account:
            return max(0.0, _f(account.get(key)))
    return 0.0


def _before(before_order: Any, intent: Any, metadata: dict[str, Any]) -> None:
    if before_order is None:
        return
    try:
        before_order(intent, metadata)
    except TypeError:
        before_order(intent)


def _close_plan(row: dict[str, Any]) -> PairExecutionPlan:
    qty = abs(_f(row.get("positionAmt", row.get("quantity"))))
    mark = _f(row.get("markPrice"), _f(row.get("entryPrice")))
    leverage = max(1, _i(row.get("leverage"), 1))
    return PairExecutionPlan(str(row.get("symbol", "")).upper(), Decimal(str(qty)),
                             Decimal(str(qty * mark)), leverage)


def _normal_short_conflicts(pmap: dict[str, dict[str, Any]], state: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    for key in pmap:
        if not key.endswith("|SHORT"):
            continue
        st = state.get(key) if isinstance(state.get(key), dict) else {}
        if not st.get("profitLockHedge"):
            conflicts.append(key)
    return sorted(conflicts)


def _fresh_report(*, positions: list[dict[str, Any]], state: dict[str, Any], settings: Any,
                  status: str, actions: list[dict[str, Any]], blocked: list[str] | None = None) -> dict[str, Any]:
    summary = account_summary(positions=positions, state=state, levels=settings.profit_lock_levels,
                              enabled=settings.profit_lock_ladder_enabled)
    return {**summary, "status": status, "actions": actions[-50:],
            "normalShortConflicts": blocked or []}


def run_profit_lock_ladder_gate(*, client: Any, ref: Any, raw_state: dict[str, Any], settings: Any,
                                uid: str, account: dict[str, Any], positions: list[dict[str, Any]],
                                open_orders: list[dict[str, Any]], timestamp_ms: int,
                                dry_run: bool = False, order_budget: int | None = None,
                                before_order: Any = None) -> ProfitLockGateResult:
    """Evaluate Profit Lock Ladder before normal TP/DCA/seat filling."""
    state = dict(raw_state.get("multiBbPositions") or {})
    if not bool(getattr(settings, "profit_lock_ladder_enabled", False)):
        report = _fresh_report(positions=positions, state=state, settings=settings, status="OFF", actions=[])
        return ProfitLockGateResult(False, False, report, raw_state, account, positions, open_orders, 0)

    pmap = _position_map(positions)
    conflicts = _normal_short_conflicts(pmap, state)
    if conflicts:
        report = _fresh_report(positions=positions, state=state, settings=settings,
                               status="BLOCKED_NORMAL_SHORTS", actions=[], blocked=conflicts)
        if not dry_run:
            ref.set({"profitLockLadderReport": report, "phase": "PROFIT_LOCK_BLOCKED",
                     "lastReason": "Profit Lock Ladder is LONG-only; bestaande normale SHORT-posities moeten eerst flat zijn",
                     "updatedAt": datetime.now(timezone.utc)}, merge=True)
        return ProfitLockGateResult(True, False, report, raw_state, account, positions, open_orders, 0)

    order_keys = {(str(row.get("symbol", "")).upper(), str(row.get("positionSide", "")).upper())
                  for row in open_orders or []}
    decisions: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any] | None]] = []
    state_changed = False
    for key, st_raw in list(state.items()):
        if not key.endswith("|LONG") or key not in pmap or not isinstance(st_raw, dict):
            continue
        symbol = key.split("|", 1)[0]
        short_key = f"{symbol}|SHORT"
        short_state = state.get(short_key) if isinstance(state.get(short_key), dict) else {}
        short_row = pmap.get(short_key) if short_state.get("profitLockHedge") else None
        decision = ladder_decision(long_row=pmap[key], short_row=short_row, state=st_raw,
                                   levels=settings.profit_lock_levels)
        st = dict(st_raw)
        old_high = _f(st.get("profitLockHighWaterProfit"))
        old_profit = _f(st.get("profitLockNetCycleProfit"))
        st.update({"profitLockHighWaterProfit": decision["highWaterProfit"],
                   "profitLockNetCycleProfit": decision["netCycleProfit"],
                   "profitLockCurrentHedgePercent": decision["currentHedgePercent"],
                   "profitLockStatus": decision.get("reason", "WAITING")})
        if abs(old_high - _f(st["profitLockHighWaterProfit"])) > 1e-9 or abs(old_profit - _f(st["profitLockNetCycleProfit"])) > 1e-9:
            state_changed = True
        state[key] = st
        if decision.get("action") in {"EXIT", "INCREASE", "ADVANCE", "BLOCK"}:
            decisions.append((key, decision, pmap[key], short_row))

    blocked_decisions = [item for item in decisions if item[1].get("action") == "BLOCK"]
    if blocked_decisions:
        actions = [{"kind": "PROFIT_LOCK_BLOCKED", "symbol": key.split("|", 1)[0],
                    "reason": decision.get("reason")} for key, decision, _, _ in blocked_decisions]
        report = _fresh_report(positions=positions, state=state, settings=settings,
                               status="BLOCKED_OVER_HEDGE", actions=actions)
        if not dry_run:
            ref.set({"multiBbPositions": state, "profitLockLadderReport": report,
                     "phase": "PROFIT_LOCK_BLOCKED", "lastReason": "Profit Lock Ladder blokkeert: SHORT is groter dan LONG",
                     "updatedAt": datetime.now(timezone.utc)}, merge=True)
        return ProfitLockGateResult(True, False, report, {**raw_state, "multiBbPositions": state},
                                    account, positions, open_orders, 0)

    # Final ladder target gets absolute priority. Close only this symbol's cycle,
    # never unrelated account positions. SHORT closes first so a failed second
    # close cannot leave a naked SHORT.
    exits = [item for item in decisions if item[1].get("action") == "EXIT"]
    if exits:
        key, decision, long_row, short_row = max(exits, key=lambda item: _f(item[1].get("netCycleProfit")))
        symbol = key.split("|", 1)[0]
        short_key = f"{symbol}|SHORT"
        required_orders = 1 + (1 if short_row is not None else 0)
        budget = max(0, 15 if order_budget is None else int(order_budget))
        if (symbol, "LONG") in order_keys or (symbol, "SHORT") in order_keys:
            actions = [{"kind": "PROFIT_LOCK_EXIT_WAIT", "symbol": symbol, "reason": "OPEN_ORDER_ON_CYCLE"}]
            report = _fresh_report(positions=positions, state=state, settings=settings,
                                   status="EXIT_WAIT", actions=actions)
            if not dry_run:
                ref.set({"multiBbPositions": state, "profitLockLadderReport": report}, merge=True)
            return ProfitLockGateResult(True, False, report, {**raw_state, "multiBbPositions": state},
                                        account, positions, open_orders, 0)
        if budget < required_orders:
            actions = [{"kind": "PROFIT_LOCK_EXIT_WAIT", "symbol": symbol, "reason": "ORDER_BUDGET"}]
            report = _fresh_report(positions=positions, state=state, settings=settings,
                                   status="EXIT_WAIT", actions=actions)
            return ProfitLockGateResult(True, False, report, {**raw_state, "multiBbPositions": state},
                                        account, positions, open_orders, 0)
        actions = [{"kind": "PROFIT_LOCK_100_REACHED", "symbol": symbol,
                    "netCycleProfit": decision.get("netCycleProfit"), "targetHedgePercent": 100.0}]
        if dry_run:
            actions.append({"kind": "PROFIT_LOCK_WOULD_CLOSE_CYCLE", "symbol": symbol,
                            "legs": required_orders})
            report = _fresh_report(positions=positions, state=state, settings=settings,
                                   status="SIMULATED_EXIT", actions=actions)
            return ProfitLockGateResult(True, False, report, raw_state, account, positions, open_orders, 0)

        cycle_id = str(state.get(key, {}).get("cycleId") or "cycle")
        sent = 0
        if short_row is not None:
            short_plan = _close_plan(short_row)
            execute_leg_once(client, short_plan, side=PositionSide.SHORT, action="CLOSE",
                             id_prefix=f"mbb-pll-exit-{hashlib.sha256((uid+cycle_id+symbol+'SHORT').encode()).hexdigest()[:12]}",
                             confirm=True, manual_loss_confirmation=True,
                             before_submit=lambda intent: _before(before_order, intent, {"kind": "PROFIT_LOCK_EXIT", "symbol": symbol, "side": "SHORT", "cycleId": cycle_id}))
            sent += 1
            fresh = _position_map(client.position_risk(symbol))
            if short_key in fresh:
                raise RuntimeError(f"{symbol}: Profit Lock SHORT-close niet flat bevestigd")
            state.pop(short_key, None)
            actions.append({"kind": "PROFIT_LOCK_SHORT_CLOSED", "symbol": symbol})
            ref.set({"multiBbPositions": state}, merge=True)

        long_plan = _close_plan(long_row)
        execute_leg_once(client, long_plan, side=PositionSide.LONG, action="CLOSE",
                         id_prefix=f"mbb-pll-exit-{hashlib.sha256((uid+cycle_id+symbol+'LONG').encode()).hexdigest()[:12]}",
                         confirm=True, manual_loss_confirmation=True,
                         before_submit=lambda intent: _before(before_order, intent, {"kind": "PROFIT_LOCK_EXIT", "symbol": symbol, "side": "LONG", "cycleId": cycle_id}))
        sent += 1
        fresh_positions = client.position_risk()
        fresh_map = _position_map(fresh_positions)
        if key in fresh_map or short_key in fresh_map:
            st = dict(state.get(key) or {})
            st["profitLockStatus"] = "EXIT_RECONCILING"
            state[key] = st
            report = _fresh_report(positions=fresh_positions, state=state, settings=settings,
                                   status="EXIT_RECONCILING", actions=actions)
            ref.set({"multiBbPositions": state, "profitLockLadderReport": report,
                     "phase": "PROFIT_LOCK_EXIT_RECONCILING"}, merge=True)
            return ProfitLockGateResult(True, False, report, {**raw_state, "multiBbPositions": state},
                                        client.account_information(), fresh_positions, client.open_orders(), sent)

        completed = dict(state.get(key) or {})
        state.pop(key, None)
        actions.append({"kind": "PROFIT_LOCK_CYCLE_CLOSED", "symbol": symbol,
                        "cycleId": cycle_id, "cycleProfit": decision.get("netCycleProfit")})
        report = _fresh_report(positions=fresh_positions, state=state, settings=settings,
                               status="RESTART_READY", actions=actions)
        existing_completed = raw_state.get("profitLockCompletedCycles") if isinstance(raw_state.get("profitLockCompletedCycles"), list) else []
        completed_row = {"symbol": symbol, "cycleId": cycle_id,
                         "netCycleProfitAtTrigger": decision.get("netCycleProfit"),
                         "closedAtMs": timestamp_ms, "lastState": completed}
        completed_cycles = [*existing_completed[-49:], completed_row]
        ref.set({"multiBbPositions": state, "profitLockLadderReport": report,
                 "profitLockCompletedCycles": completed_cycles, "phase": "RUNNING",
                 "lastReason": f"Profit Lock Ladder {symbol}: 100% winstlevel gesloten; nieuwe LONG-cycle mag starten",
                 "updatedAt": datetime.now(timezone.utc)}, merge=True)
        ref.collection("audit").add({"event": "PROFIT_LOCK_CYCLE_CLOSED", "symbol": symbol,
            "cycleId": cycle_id, "netCycleProfitAtTrigger": decision.get("netCycleProfit"),
            "ordersSent": sent, "timestamp": datetime.now(timezone.utc)})
        next_raw = {**raw_state, "multiBbPositions": state, "profitLockCompletedCycles": completed_cycles,
                    "profitLockLadderReport": report}
        return ProfitLockGateResult(True, True, report, next_raw, client.account_information(),
                                    fresh_positions, client.open_orders(), sent)

    due = [item for item in decisions if item[1].get("action") in {"INCREASE", "ADVANCE"}]
    due.sort(key=lambda item: (-_f(item[1].get("targetHedgePercent")), -_f(item[1].get("netCycleProfit"))))
    budget = max(0, 15 if order_budget is None else int(order_budget))
    available = _available(account)
    sent = 0
    actions: list[dict[str, Any]] = []
    info_map: dict[str, dict[str, Any]] | None = None

    for key, decision, long_row, short_row in due:
        symbol = key.split("|", 1)[0]
        if (symbol, "LONG") in order_keys or (symbol, "SHORT") in order_keys:
            actions.append({"kind": "PROFIT_LOCK_WAIT", "symbol": symbol, "reason": "OPEN_ORDER_ON_CYCLE"})
            continue
        long_state = dict(state.get(key) or {})
        level_index = int(decision.get("reachedLevelIndex", -1))
        if decision.get("action") == "ADVANCE":
            long_state.update({"profitLockLevelIndex": level_index,
                               "profitLockTargetHedgePercent": decision.get("targetHedgePercent", decision.get("currentHedgePercent", 0.0)),
                               "profitLockStatus": "LEVEL_CONFIRMED"})
            state[key] = long_state
            state_changed = True
            actions.append({"kind": "PROFIT_LOCK_LEVEL_CONFIRMED", "symbol": symbol,
                            "levelIndex": level_index, "ordersSent": 0})
            continue
        if sent >= budget:
            break
        delta = max(0.0, _f(decision.get("hedgeDeltaNotional")))
        if delta <= 0:
            continue
        if dry_run:
            actions.append({"kind": "PROFIT_LOCK_HEDGE_WOULD_INCREASE", "symbol": symbol,
                            "levelIndex": level_index, "targetHedgePercent": decision.get("targetHedgePercent"),
                            "notionalUsd": delta})
            continue
        if info_map is None:
            info = client.public_exchange_info()
            info_map = {str(row.get("symbol", "")).upper(): row for row in info.get("symbols", [])}
        symbol_row = info_map.get(symbol)
        if symbol_row is None:
            actions.append({"kind": "PROFIT_LOCK_WAIT", "symbol": symbol, "reason": "SYMBOL_INFO_UNAVAILABLE"})
            continue
        mark = _f(long_row.get("markPrice"), _f(long_row.get("entryPrice")))
        leverage = max(1, _i(long_row.get("leverage"), 1))
        current_short_notional = position_notional(short_row)
        long_notional = position_notional(long_row)
        # Hard invariant: planned SHORT after this order can never exceed LONG.
        delta = min(delta, max(0.0, long_notional - current_short_notional))
        try:
            brackets = bracket_rows(client.leverage_brackets(symbol), symbol)
            plan = plan_pair(symbol_row, brackets, mark, delta, accepted_leverage=leverage,
                             existing_contract_notional=long_notional + current_short_notional)
        except Exception as exc:
            actions.append({"kind": "PROFIT_LOCK_WAIT", "symbol": symbol,
                            "reason": f"HEDGE_PLAN_BLOCKED: {exc}"})
            continue
        required_margin = float(plan.notional_per_leg) / max(1, plan.leverage)
        if available + 1e-9 < required_margin * 1.05:
            actions.append({"kind": "PROFIT_LOCK_WAIT", "symbol": symbol,
                            "reason": "INSUFFICIENT_AVAILABLE_MARGIN", "requiredMargin": required_margin})
            continue
        result = execute_leg_once(client, plan, side=PositionSide.SHORT, action="OPEN",
                                  id_prefix=f"mbb-pll-{hashlib.sha256((uid+str(long_state.get('cycleId'))+symbol+str(level_index)).encode()).hexdigest()[:12]}",
                                  confirm=True, new_position_leverage=leverage,
                                  before_submit=lambda intent, _s=symbol, _c=str(long_state.get("cycleId")), _l=level_index:
                                      _before(before_order, intent, {"kind": "PROFIT_LOCK_HEDGE_INCREASE", "symbol": _s, "side": "SHORT", "cycleId": _c, "levelIndex": _l}))
        sent += 1
        available = max(0.0, available - required_margin)
        fresh_symbol = _position_map(client.position_risk(symbol))
        fresh_short = fresh_symbol.get(f"{symbol}|SHORT")
        fresh_long = fresh_symbol.get(f"{symbol}|LONG") or long_row
        if fresh_short is None:
            raise RuntimeError(f"{symbol}: Profit Lock SHORT-fill niet in exchange truth bevestigd")
        if position_notional(fresh_short) > position_notional(fresh_long) + max(0.01, position_notional(fresh_long) * 1e-8):
            raise RuntimeError(f"{symbol}: Profit Lock veiligheidsinvariant SHORT <= LONG geschonden")
        fill = result.get("result") or {}
        short_key = f"{symbol}|SHORT"
        state[short_key] = {
            **(state.get(short_key) if isinstance(state.get(short_key), dict) else {}),
            "cycleId": long_state.get("cycleId"), "dcaCount": 0,
            "lastBotFillPrice": _f(fill.get("avgPrice"), _f(fresh_short.get("entryPrice"))),
            "lastKnownQty": abs(_f(fresh_short.get("positionAmt"))),
            "lastKnownEntry": _f(fresh_short.get("entryPrice")),
            "leverage": max(1, _i(fresh_short.get("leverage"), leverage)),
            "cycleStartedAtMs": long_state.get("cycleStartedAtMs", timestamp_ms),
            "updatedAtMs": timestamp_ms, "botManaged": True,
            "profitLockHedge": True, "pairedLongKey": key,
        }
        actual_hedge = position_notional(fresh_short) / max(position_notional(fresh_long), 1e-12) * 100.0
        long_state.update({"profitLockLevelIndex": level_index,
                           "profitLockTargetHedgePercent": decision.get("targetHedgePercent"),
                           "profitLockCurrentHedgePercent": actual_hedge,
                           "profitLockLastHedgeAtMs": timestamp_ms,
                           "profitLockStatus": "LOCKED"})
        state[key] = long_state
        actions.append({"kind": "PROFIT_LOCK_HEDGE_INCREASED", "symbol": symbol,
                        "levelIndex": level_index, "targetHedgePercent": decision.get("targetHedgePercent"),
                        "actualHedgePercent": actual_hedge, "notionalUsd": float(plan.notional_per_leg)})
        ref.set({"multiBbPositions": state}, merge=True)
        ref.collection("audit").add({"event": "PROFIT_LOCK_HEDGE_INCREASED", "symbol": symbol,
            "cycleId": long_state.get("cycleId"), "levelIndex": level_index,
            "targetHedgePercent": decision.get("targetHedgePercent"),
            "actualHedgePercent": actual_hedge, "notionalUsd": float(plan.notional_per_leg),
            "timestamp": datetime.now(timezone.utc)})

    if dry_run and due:
        report = _fresh_report(positions=positions, state=state, settings=settings,
                               status="SIMULATED", actions=actions)
        return ProfitLockGateResult(True, False, report, raw_state, account, positions, open_orders, 0)

    if state_changed or sent or actions:
        fresh_positions = client.position_risk() if sent else positions
        report = _fresh_report(positions=fresh_positions, state=state, settings=settings,
                               status="ACTIVE", actions=actions)
        ref.set({"multiBbPositions": state, "profitLockLadderReport": report,
                 "lastReason": ("Profit Lock Ladder hedge bijgewerkt" if sent else "Profit Lock Ladder wacht op volgend netto winstlevel"),
                 "updatedAt": datetime.now(timezone.utc)}, merge=True)
        return ProfitLockGateResult(bool(sent or due), False, report,
                                    {**raw_state, "multiBbPositions": state, "profitLockLadderReport": report},
                                    client.account_information() if sent else account,
                                    fresh_positions, client.open_orders() if sent else open_orders, sent)

    report = _fresh_report(positions=positions, state=state, settings=settings,
                           status="ACTIVE", actions=[])
    if not dry_run:
        ref.set({"profitLockLadderReport": report}, merge=True)
    return ProfitLockGateResult(False, False, report, {**raw_state, "multiBbPositions": state},
                                account, positions, open_orders, 0)
