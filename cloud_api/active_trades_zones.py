"""Actieve Trades prijszones (read-only analytics, never feeds orders).

Two pure building blocks, both deterministic and fully unit-tested:

1. ``long_basket`` + ``basket_index_candles``: the open LONG positions (hedge
   SHORTs excluded), weighted by their current notional, recomputed with those
   constant weights over every coin's own Aster klines. This gives a calm index
   line with real history instead of the chain-linked minute samples, so
   support/resistance on it actually means something.

2. ``derive_sr_zones``: support/resistance levels from confirmed swing highs and
   lows, clustered on ATR, with strength = number of touches. A zone is the
   range between two neighbouring levels. A break (close beyond a level by
   0.25 ATR) followed by a retest that holds flips the level's role
   (resistance becomes support and vice versa).
"""
from __future__ import annotations

import math
from typing import Any

TIMEFRAME_TO_ASTER = {"1m": "1m", "5m": "5m", "15m": "15m", "1u": "1h", "4u": "4h", "24u": "1d"}
TIMEFRAME_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1u": 3_600_000, "4u": 14_400_000, "24u": 86_400_000}

SWING_WING = 3
CLUSTER_ATR = 0.6
BREAK_ATR = 0.25
RETEST_ATR = 0.5
MAX_LEVELS = 24
MIN_COVERAGE = 0.9


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def long_basket(positions: list[dict[str, Any]] | None, *, max_symbols: int = 40) -> dict[str, Any]:
    """Open LONG legs weighted by current notional. SHORT legs (hedges) are excluded."""
    weights: dict[str, float] = {}
    for row in positions or []:
        if not isinstance(row, dict):
            continue
        side = str(row.get("side", row.get("positionSide", ""))).upper().strip()
        if side != "LONG":
            continue
        symbol = str(row.get("symbol", "")).upper().strip()
        quantity = abs(_number(row.get("quantity", row.get("positionAmt"))))
        mark = _number(row.get("markPrice"))
        notional = abs(_number(row.get("notionalUsd", row.get("notional"))))
        if notional <= 0 and quantity > 0 and mark > 0:
            notional = quantity * mark
        if not symbol or notional <= 0:
            continue
        weights[symbol] = weights.get(symbol, 0.0) + notional
    ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
    total = sum(weight for _, weight in ranked)
    kept = ranked[:max(1, int(max_symbols))]
    kept_total = sum(weight for _, weight in kept)
    return {
        "symbols": [{"symbol": symbol, "notionalUsd": weight, "weight": weight / kept_total if kept_total > 0 else 0.0}
                    for symbol, weight in kept],
        "totalLongNotional": total,
        "coveredNotional": kept_total,
        "coveragePercent": (kept_total / total * 100.0) if total > 0 else 0.0,
        "weighting": "CURRENT_NOTIONAL_LONG_ONLY",
    }


def kline_candles(rows: list[Any] | None) -> list[dict[str, Any]]:
    """Aster kline rows [openTime, open, high, low, close, ...] -> clean OHLC dicts."""
    result: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, (list, tuple)) and len(row) >= 5:
            at, opened, high, low, close = (_number(row[index]) for index in range(5))
        elif isinstance(row, dict):
            at = _number(row.get("openTime", row.get("t")))
            opened, high, low, close = (_number(row.get(key)) for key in ("open", "high", "low", "close"))
        else:
            continue
        if at <= 0 or min(opened, high, low, close) <= 0 or high < low:
            continue
        result.append({"atMs": int(at), "open": opened, "high": high, "low": low, "close": close})
    result.sort(key=lambda candle: candle["atMs"])
    deduped: list[dict[str, Any]] = []
    for candle in result:
        if deduped and deduped[-1]["atMs"] == candle["atMs"]:
            deduped[-1] = candle
        else:
            deduped.append(candle)
    return deduped


def basket_index_candles(basket: dict[str, Any], candles_by_symbol: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Constant-weight basket index (base 100 at the first common bar).

    Symbols covering < 90 % of the longest history are dropped (weights are
    renormalised) so a recent listing never shortens the whole chart. Bars are
    inner-joined on time. Open/close are exact; high/low are the weighted sum of
    each coin's high/low (the usual basket approximation; it can slightly
    overstate the true intrabar range).
    """
    entries = [row for row in basket.get("symbols", []) if isinstance(row, dict) and _number(row.get("weight")) > 0]
    series = {str(row["symbol"]): candles_by_symbol.get(str(row["symbol"])) or [] for row in entries}
    longest = max((len(rows) for rows in series.values()), default=0)
    if longest <= 0:
        return {"candles": [], "usedSymbols": [], "droppedSymbols": [row["symbol"] for row in entries], "usedWeightPercent": 0.0}
    used = [row for row in entries if len(series[str(row["symbol"])]) >= longest * MIN_COVERAGE]
    dropped = [str(row["symbol"]) for row in entries if row not in used]
    if not used:
        return {"candles": [], "usedSymbols": [], "droppedSymbols": dropped, "usedWeightPercent": 0.0}
    weight_total = sum(_number(row["weight"]) for row in used)
    maps = {str(row["symbol"]): {candle["atMs"]: candle for candle in series[str(row["symbol"])]} for row in used}
    common = sorted(set.intersection(*(set(mapping) for mapping in maps.values())))
    if not common:
        return {"candles": [], "usedSymbols": [], "droppedSymbols": dropped + [str(row["symbol"]) for row in used], "usedWeightPercent": 0.0}
    base = {symbol: maps[symbol][common[0]]["open"] for symbol in maps}
    candles: list[dict[str, Any]] = []
    for at in common:
        values = {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0}
        for row in used:
            symbol = str(row["symbol"])
            weight = _number(row["weight"]) / weight_total
            bar = maps[symbol][at]
            for key in values:
                values[key] += weight * bar[key] / base[symbol] * 100.0
        high = max(values["high"], values["open"], values["close"])
        low = min(values["low"], values["open"], values["close"])
        candles.append({"time": at // 1000, "atMs": at, "open": values["open"], "high": high, "low": low, "close": values["close"]})
    return {
        "candles": candles,
        "usedSymbols": [str(row["symbol"]) for row in used],
        "droppedSymbols": dropped,
        "usedWeightPercent": weight_total * 100.0,
    }


def _atr(candles: list[dict[str, Any]], period: int = 14) -> float:
    ranges: list[float] = []
    previous_close = 0.0
    for candle in candles:
        high, low, close = candle["high"], candle["low"], candle["close"]
        ranges.append(high - low if previous_close <= 0 else max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = close
    window = ranges[-period:]
    return sum(window) / len(window) if window else 0.0


def _swings(candles: list[dict[str, Any]], wing: int = SWING_WING) -> list[dict[str, Any]]:
    """Swing highs/lows confirmed by `wing` closed bars on both sides (no look-ahead)."""
    swings: list[dict[str, Any]] = []
    for index in range(wing, len(candles) - wing):
        window = candles[index - wing:index + wing + 1]
        high, low = candles[index]["high"], candles[index]["low"]
        if high >= max(row["high"] for row in window) and high > max(row["high"] for row in candles[index - wing:index]):
            swings.append({"price": high, "kind": "high", "index": index})
        if low <= min(row["low"] for row in window) and low < min(row["low"] for row in candles[index - wing:index]):
            swings.append({"price": low, "kind": "low", "index": index})
    return swings


def _role_history(level: float, candles: list[dict[str, Any]], atr: float, start: int) -> dict[str, Any]:
    """Walk forward from the level's first swing: breaks, retests and role flips.

    A flip needs three steps: a close beyond the level by BREAK_ATR, a move away
    of at least 1 ATR, then a pullback that touches the level within RETEST_ATR
    and closes on the new side. A straight run-away is a break without retest.
    """
    flips = 0
    last_flip_index: int | None = None
    pending_break: str | None = None
    extended = False
    side = "above" if candles[start]["close"] >= level else "below"
    for index in range(start + 1, len(candles)):
        candle = candles[index]
        close = candle["close"]
        if side == "below" and close > level + BREAK_ATR * atr:
            side, pending_break, extended = "above", "up", close >= level + atr
            continue
        if side == "above" and close < level - BREAK_ATR * atr:
            side, pending_break, extended = "below", "down", close <= level - atr
            continue
        if pending_break == "up":
            if not extended:
                extended = candle["high"] >= level + atr
            elif candle["low"] <= level + RETEST_ATR * atr and close > level:
                flips += 1
                last_flip_index = index
                pending_break, extended = None, False
        elif pending_break == "down":
            if not extended:
                extended = candle["low"] <= level - atr
            elif candle["high"] >= level - RETEST_ATR * atr and close < level:
                flips += 1
                last_flip_index = index
                pending_break, extended = None, False
    return {"flips": flips, "lastFlipIndex": last_flip_index, "pendingBreak": pending_break}


def derive_sr_zones(candles: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [row for row in candles or [] if isinstance(row, dict) and _number(row.get("close")) > 0]
    if len(rows) < SWING_WING * 2 + 8:
        return {"levels": [], "zones": [], "activeZone": None, "atr": 0.0, "reason": "TOO_FEW_CANDLES"}
    atr = _atr(rows)
    if atr <= 0:
        return {"levels": [], "zones": [], "activeZone": None, "atr": 0.0, "reason": "NO_VOLATILITY"}
    clusters: list[dict[str, Any]] = []
    for swing in sorted(_swings(rows), key=lambda row: row["price"]):
        target = next((cluster for cluster in clusters if abs(swing["price"] - cluster["price"]) <= CLUSTER_ATR * atr), None)
        if target is None:
            clusters.append({"price": swing["price"], "prices": [swing["price"]], "touches": 1,
                             "firstIndex": swing["index"], "lastIndex": swing["index"], "kinds": {swing["kind"]}})
        else:
            target["prices"].append(swing["price"])
            target["price"] = sum(target["prices"]) / len(target["prices"])
            target["touches"] += 1
            target["firstIndex"] = min(target["firstIndex"], swing["index"])
            target["lastIndex"] = max(target["lastIndex"], swing["index"])
            target["kinds"].add(swing["kind"])
    last_close = rows[-1]["close"]
    recent_cutoff = len(rows) - 40
    kept = [cluster for cluster in clusters if cluster["touches"] >= 2 or cluster["lastIndex"] >= recent_cutoff]
    kept.sort(key=lambda cluster: abs(cluster["price"] - last_close))
    kept = sorted(kept[:MAX_LEVELS], key=lambda cluster: cluster["price"])
    levels: list[dict[str, Any]] = []
    for cluster in kept:
        history = _role_history(cluster["price"], rows, atr, cluster["firstIndex"])
        flipped = history["lastFlipIndex"] is not None
        kind = "support" if cluster["price"] < last_close else "resistance"
        levels.append({
            "price": cluster["price"],
            "kind": kind,
            "touches": cluster["touches"],
            "strength": 3 if cluster["touches"] >= 4 else 2 if cluster["touches"] >= 2 else 1,
            "flipped": flipped,
            "flips": history["flips"],
            "flipAtMs": rows[history["lastFlipIndex"]]["atMs"] if flipped else None,
            "brokenAwaitingRetest": history["pendingBreak"] is not None,
            "lastTouchAtMs": rows[cluster["lastIndex"]]["atMs"],
        })
    zones: list[dict[str, Any]] = []
    active_position = None
    for index in range(len(levels) - 1):
        lower, upper = levels[index], levels[index + 1]
        zones.append({"lower": lower["price"], "upper": upper["price"]})
        if lower["price"] <= last_close < upper["price"]:
            active_position = index
    if active_position is None and levels:
        active_position = -1 if last_close < levels[0]["price"] else len(zones)
    for index, zone in enumerate(zones):
        zone["index"] = index - active_position if active_position is not None else None
    active = next((zone for zone in zones if zone["index"] == 0), None)
    return {
        "levels": levels,
        "zones": zones,
        "activeZone": active,
        "lastClose": last_close,
        "atr": atr,
        "aboveAllLevels": bool(levels and last_close >= levels[-1]["price"]),
        "belowAllLevels": bool(levels and last_close < levels[0]["price"]),
        "method": "swings(wing=3)+atr-cluster(0.6)+break(0.25atr)+retest(0.5atr)",
        "reason": "OK" if levels else "NO_LEVELS",
    }
