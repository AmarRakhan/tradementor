"""Pure Profit Lock Ladder helpers for Aster Multi DCA.

The module contains no network or order submission.  It deliberately treats a
Profit Lock SHORT as protection owned by its LONG cycle, never as a primary
SHORT strategy seat.
"""
from __future__ import annotations

from typing import Any, Iterable
import math


REFERENCE_ID = "file_00000000e8dc82108202dd2e1397c131"
DEFAULT_LEVELS: tuple[tuple[float, float], ...] = (
    (5.0, 20.0),
    (10.0, 40.0),
    (15.0, 60.0),
    (20.0, 80.0),
    (25.0, 100.0),
)
MAX_LEVELS = 20


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def position_pnl(row: dict[str, Any] | None) -> float:
    source = row or {}
    for key in ("unRealizedProfit", "unrealizedPnl", "unrealizedProfit"):
        if key in source:
            return _f(source.get(key))
    return 0.0


def position_notional(row: dict[str, Any] | None) -> float:
    source = row or {}
    qty = abs(_f(source.get("positionAmt", source.get("quantity"))))
    mark = _f(source.get("markPrice"), _f(source.get("entryPrice")))
    if qty > 0 and mark > 0:
        return qty * mark
    return abs(_f(source.get("notional")))


def normalize_levels(raw: Any) -> tuple[tuple[float, float], ...]:
    """Validate a strictly increasing profit -> hedge ladder ending at 100%."""
    if raw in (None, "", []):
        return DEFAULT_LEVELS
    if not isinstance(raw, (list, tuple)):
        raise ValueError("Profit Lock Ladder-levels moeten een lijst zijn")
    if not 1 <= len(raw) <= MAX_LEVELS:
        raise ValueError(f"Profit Lock Ladder moet 1 t/m {MAX_LEVELS} levels bevatten")
    levels: list[tuple[float, float]] = []
    for item in raw:
        if isinstance(item, dict):
            profit = _f(item.get("profitUsd", item.get("profit", item.get("netProfitUsd"))), -1.0)
            hedge = _f(item.get("hedgePercent", item.get("hedge", item.get("coveragePercent"))), -1.0)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            profit, hedge = _f(item[0], -1.0), _f(item[1], -1.0)
        else:
            raise ValueError("Ieder Profit Lock Ladder-level vereist profitUsd en hedgePercent")
        if profit <= 0:
            raise ValueError("Profit Lock Ladder winstlevels moeten groter dan 0 USDT zijn")
        if not 0 < hedge <= 100:
            raise ValueError("Profit Lock Ladder hedge moet tussen 0% en 100% liggen")
        if levels and profit <= levels[-1][0]:
            raise ValueError("Profit Lock Ladder winstlevels moeten strikt oplopen")
        if levels and hedge <= levels[-1][1]:
            raise ValueError("Profit Lock Ladder hedgepercentages moeten strikt oplopen")
        levels.append((round(profit, 8), round(hedge, 8)))
    if abs(levels[-1][1] - 100.0) > 1e-9:
        raise ValueError("Het laatste Profit Lock Ladder-level moet exact 100% hedge zijn")
    return tuple(levels)


def public_levels(levels: Iterable[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"profitUsd": float(profit), "hedgePercent": float(hedge)} for profit, hedge in levels]


def cycle_profit(long_row: dict[str, Any] | None, short_row: dict[str, Any] | None,
                 state: dict[str, Any] | None) -> float:
    """Net cycle profit: live LONG + hedge SHORT + realized cycle PnL - cycle fees."""
    st = state or {}
    realized = _f(st.get("realizedCyclePnl", st.get("profitLockRealizedPnl")))
    fees = max(0.0, _f(st.get("cycleFees", st.get("profitLockCycleFees"))))
    return position_pnl(long_row) + position_pnl(short_row) + realized - fees


def reached_level_index(net_profit: float, levels: tuple[tuple[float, float], ...]) -> int:
    index = -1
    for candidate, (profit, _) in enumerate(levels):
        if net_profit + 1e-9 >= profit:
            index = candidate
        else:
            break
    return index


def ladder_decision(*, long_row: dict[str, Any], short_row: dict[str, Any] | None,
                    state: dict[str, Any] | None,
                    levels: tuple[tuple[float, float], ...]) -> dict[str, Any]:
    """Return one ratchet decision without ever asking to reduce the SHORT."""
    st = state or {}
    long_notional = position_notional(long_row)
    short_notional = position_notional(short_row)
    net_profit = cycle_profit(long_row, short_row, st)
    previous_index = max(-1, int(_f(st.get("profitLockLevelIndex"), -1)))
    high_water = max(_f(st.get("profitLockHighWaterProfit")), net_profit)
    current_hedge = (short_notional / long_notional * 100.0) if long_notional > 0 else 0.0
    base = {
        "netCycleProfit": net_profit,
        "highWaterProfit": high_water,
        "longNotional": long_notional,
        "shortNotional": short_notional,
        "currentHedgePercent": current_hedge,
        "previousLevelIndex": previous_index,
    }
    if long_notional <= 0:
        return {**base, "action": "HOLD", "reason": "NO_LONG"}
    if short_notional > long_notional + max(0.01, long_notional * 1e-8):
        return {**base, "action": "BLOCK", "reason": "OVER_HEDGED"}
    reached = reached_level_index(net_profit, levels)
    if reached <= previous_index:
        next_index = previous_index + 1
        return {**base, "action": "HOLD", "reason": "WAITING_NEXT_NET_PROFIT_LEVEL",
                "reachedLevelIndex": reached,
                "nextLevel": (public_levels((levels[next_index],))[0] if next_index < len(levels) else None)}
    profit_usd, target_percent = levels[reached]
    if target_percent >= 100.0 - 1e-9:
        return {**base, "action": "EXIT", "reason": "FINAL_100_PERCENT_LEVEL_REACHED",
                "reachedLevelIndex": reached, "profitLevelUsd": profit_usd,
                "targetHedgePercent": 100.0, "targetShortNotional": long_notional,
                "hedgeDeltaNotional": max(0.0, long_notional - short_notional)}
    target_short = min(long_notional, long_notional * target_percent / 100.0)
    delta = max(0.0, min(target_short - short_notional, long_notional - short_notional))
    return {**base, "action": "INCREASE" if delta > 1e-9 else "ADVANCE",
            "reason": "NEW_NET_PROFIT_LEVEL_REACHED", "reachedLevelIndex": reached,
            "profitLevelUsd": profit_usd, "targetHedgePercent": target_percent,
            "targetShortNotional": target_short, "hedgeDeltaNotional": delta}


def account_summary(*, positions: list[dict[str, Any]], state: dict[str, Any],
                    levels: tuple[tuple[float, float], ...], enabled: bool) -> dict[str, Any]:
    """Weighted Profit Lock coverage plus per-LONG cycle diagnostics."""
    pmap: dict[str, dict[str, Any]] = {}
    for row in positions or []:
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", row.get("side", ""))).upper().strip()
        if symbol and side in {"LONG", "SHORT"} and position_notional(row) > 0:
            pmap[f"{symbol}|{side}"] = row
    rows: list[dict[str, Any]] = []
    total_long = 0.0
    total_short = 0.0
    hedged = 0
    for key, long_state_raw in sorted(state.items()):
        if not str(key).endswith("|LONG") or key not in pmap or not isinstance(long_state_raw, dict):
            continue
        symbol = str(key).split("|", 1)[0]
        long_row = pmap[key]
        short_key = f"{symbol}|SHORT"
        short_state = state.get(short_key) if isinstance(state.get(short_key), dict) else {}
        short_row = pmap.get(short_key) if short_state.get("profitLockHedge") else None
        long_notional = position_notional(long_row)
        short_notional = position_notional(short_row)
        total_long += long_notional
        total_short += min(short_notional, long_notional)
        if short_notional > 0:
            hedged += 1
        current_index = max(-1, int(_f(long_state_raw.get("profitLockLevelIndex"), -1)))
        next_index = current_index + 1
        net_profit = cycle_profit(long_row, short_row, long_state_raw)
        rows.append({
            "symbol": symbol,
            "longNotional": round(long_notional, 8),
            "shortNotional": round(short_notional, 8),
            "hedgePercent": round(short_notional / long_notional * 100.0, 6) if long_notional > 0 else 0.0,
            "cycleProfit": round(net_profit, 8),
            "highestCycleProfit": round(max(_f(long_state_raw.get("profitLockHighWaterProfit")), net_profit), 8),
            "currentLevelIndex": current_index,
            "currentTargetHedgePercent": (levels[current_index][1] if 0 <= current_index < len(levels) else 0.0),
            "nextLevel": (public_levels((levels[next_index],))[0] if next_index < len(levels) else None),
            "dcaCount": max(0, int(_f(long_state_raw.get("dcaCount")))),
            "status": str(long_state_raw.get("profitLockStatus", "WAITING")),
        })
    coverage = (total_short / total_long * 100.0) if total_long > 0 else 0.0
    return {
        "enabled": bool(enabled),
        "primarySide": "LONG" if enabled else None,
        "referenceId": REFERENCE_ID,
        "longExposureUsd": round(total_long, 8),
        "profitLockShortExposureUsd": round(total_short, 8),
        "hedgeCoveragePercent": round(min(100.0, coverage), 6),
        "positionCount": len(rows),
        "hedgedPositionCount": hedged,
        "levels": public_levels(levels),
        "positions": rows,
    }
