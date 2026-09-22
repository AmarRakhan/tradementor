"""Read-only portfolio-equity chart analytics for Aster.

This module contains only deterministic arithmetic.  It never imports execution
code and it never submits orders.  The caller owns persistence and exchange
reads so the zone engine can be exhaustively tested in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Any, Iterable


TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "24h": 86400,
}
TIMEFRAME_ALIASES = {"1u": "1h", "4u": "4h", "24u": "24h"}


def normalize_timeframe(value: str) -> str:
    key = str(value or "").strip().lower()
    key = TIMEFRAME_ALIASES.get(key, key)
    if key not in TIMEFRAME_SECONDS:
        raise ValueError(f"Niet-ondersteund portfolio-timeframe: {value}")
    return key


def timeframe_ms(value: str) -> int:
    return TIMEFRAME_SECONDS[normalize_timeframe(value)] * 1000


def _number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Niet-eindige numerieke waarde")
    return number


def _sample_time(row: dict[str, Any]) -> int:
    return int(_number(row.get("atMs", row.get("at", row.get("timestampMs", 0)))))


def _sample_equity(row: dict[str, Any]) -> float:
    return _number(row.get("adjustedEquity", row.get("equity", 0)))


def cashflow_adjusted_samples(
    samples: Iterable[dict[str, Any]], cashflows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Remove exchange-external cashflow jumps from raw account equity.

    Cashflows use Aster's signed income convention.  A positive transfer is
    subtracted from every later raw equity sample; a negative transfer is added
    back.  The first reliable sample is the baseline, so cashflow before it does
    not alter the visible series.
    """
    ordered: list[tuple[int, float, dict[str, Any]]] = []
    for raw in samples:
        if not isinstance(raw, dict):
            continue
        try:
            at_ms = _sample_time(raw)
            equity = _number(raw.get("equity"))
        except (TypeError, ValueError):
            continue
        if at_ms <= 0 or equity <= 0:
            continue
        ordered.append((at_ms, equity, raw))
    ordered.sort(key=lambda item: item[0])
    if not ordered:
        return []

    baseline_ms = ordered[0][0]
    flow_rows: list[tuple[int, float]] = []
    for row in cashflows:
        if not isinstance(row, dict):
            continue
        try:
            at_ms = int(_number(row.get("time", row.get("timestampMs", row.get("timestamp", 0)))))
            amount = _number(row.get("income", row.get("amount", 0)))
        except (TypeError, ValueError):
            continue
        if at_ms >= baseline_ms and abs(amount) > 0:
            flow_rows.append((at_ms, amount))
    flow_rows.sort(key=lambda item: item[0])

    result: list[dict[str, Any]] = []
    cumulative = 0.0
    cursor = 0
    for at_ms, equity, raw in ordered:
        while cursor < len(flow_rows) and flow_rows[cursor][0] <= at_ms:
            cumulative += flow_rows[cursor][1]
            cursor += 1
        result.append({
            **raw,
            "atMs": at_ms,
            "rawEquity": equity,
            "adjustedEquity": equity - cumulative,
            "externalCashflow": cumulative,
        })
    return result


def aggregate_ohlc(samples: Iterable[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    """Aggregate observed account-equity samples into real time-bucket OHLC.

    No missing bucket is interpolated. High/low are the highest/lowest reliable
    account-equity observations captured inside that bucket.
    """
    bucket_ms = timeframe_ms(timeframe)
    rows: list[tuple[int, float]] = []
    for raw in samples:
        if not isinstance(raw, dict):
            continue
        try:
            at_ms, equity = _sample_time(raw), _sample_equity(raw)
        except (TypeError, ValueError):
            continue
        if at_ms > 0 and equity > 0:
            rows.append((at_ms, equity))
    rows.sort()
    buckets: dict[int, list[tuple[int, float]]] = {}
    for at_ms, equity in rows:
        bucket = (at_ms // bucket_ms) * bucket_ms
        buckets.setdefault(bucket, []).append((at_ms, equity))

    candles: list[dict[str, Any]] = []
    for bucket, values in sorted(buckets.items()):
        values.sort()
        equities = [value for _, value in values]
        candles.append({
            "timeMs": bucket,
            "open": values[0][1],
            "high": max(equities),
            "low": min(equities),
            "close": values[-1][1],
            "sampleCount": len(values),
        })
    return candles


def bollinger_bands(
    candles: list[dict[str, Any]], period: int = 20, deviations: float = 2.0
) -> list[dict[str, Any]]:
    closes = [_number(row["close"]) for row in candles]
    result: list[dict[str, Any]] = []
    for index, candle in enumerate(candles):
        if index + 1 < period:
            continue
        window = closes[index + 1 - period:index + 1]
        middle = statistics.fmean(window)
        deviation = statistics.pstdev(window)
        result.append({
            "timeMs": int(candle["timeMs"]),
            "middle": middle,
            "upper": middle + deviations * deviation,
            "lower": middle - deviations * deviation,
        })
    return result


def atr_values(candles: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    if not candles:
        return []
    true_ranges: list[float] = []
    result: list[float | None] = []
    previous_close: float | None = None
    for candle in candles:
        high = _number(candle["high"])
        low = _number(candle["low"])
        close = _number(candle["close"])
        tr = high - low if previous_close is None else max(
            high - low, abs(high - previous_close), abs(low - previous_close)
        )
        true_ranges.append(max(0.0, tr))
        if len(true_ranges) < period:
            result.append(None)
        else:
            result.append(statistics.fmean(true_ranges[-period:]))
        previous_close = close
    return result


@dataclass(frozen=True)
class Pivot:
    index: int
    time_ms: int
    price: float
    kind: str
    atr: float


def confirmed_pivots(candles: list[dict[str, Any]], window: int = 2) -> list[Pivot]:
    """Return pivots only after right-hand candles exist, avoiding live look-ahead."""
    if len(candles) < window * 2 + 1:
        return []
    atrs = atr_values(candles)
    fallback_ranges = [
        max(0.0, _number(row["high"]) - _number(row["low"])) for row in candles
    ]
    positive_ranges = [value for value in fallback_ranges if value > 0]
    fallback = statistics.median(positive_ranges) if positive_ranges else 0.0
    result: list[Pivot] = []
    for index in range(window, len(candles) - window):
        current = candles[index]
        high = _number(current["high"])
        low = _number(current["low"])
        neighborhood = candles[index - window:index + window + 1]
        highs = [_number(row["high"]) for row in neighborhood]
        lows = [_number(row["low"]) for row in neighborhood]
        atr = atrs[index] or fallback or max(high - low, 1e-9)
        if high == max(highs) and highs.count(high) == 1:
            result.append(Pivot(index, int(current["timeMs"]), high, "resistance", atr))
        if low == min(lows) and lows.count(low) == 1:
            result.append(Pivot(index, int(current["timeMs"]), low, "support", atr))
    return result


def cluster_structural_levels(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pivots = confirmed_pivots(candles)
    if not pivots:
        return []
    clusters: list[dict[str, Any]] = []
    for pivot in sorted(pivots, key=lambda item: item.price):
        threshold = max(pivot.atr * 0.65, 1e-9)
        candidate: dict[str, Any] | None = None
        candidate_distance = float("inf")
        for cluster in clusters:
            distance = abs(float(cluster["center"]) - pivot.price)
            local_threshold = max(float(cluster["atr"]) * 0.65, threshold)
            if distance <= local_threshold and distance < candidate_distance:
                candidate, candidate_distance = cluster, distance
        if candidate is None:
            clusters.append({
                "center": pivot.price,
                "prices": [pivot.price],
                "touches": 1,
                "supportTouches": 1 if pivot.kind == "support" else 0,
                "resistanceTouches": 1 if pivot.kind == "resistance" else 0,
                "firstTimeMs": pivot.time_ms,
                "lastTimeMs": pivot.time_ms,
                "atr": pivot.atr,
            })
            continue
        prices = list(candidate["prices"])
        prices.append(pivot.price)
        candidate["prices"] = prices
        candidate["center"] = statistics.fmean(prices)
        candidate["touches"] = int(candidate["touches"]) + 1
        candidate["supportTouches"] = int(candidate["supportTouches"]) + (1 if pivot.kind == "support" else 0)
        candidate["resistanceTouches"] = int(candidate["resistanceTouches"]) + (1 if pivot.kind == "resistance" else 0)
        candidate["firstTimeMs"] = min(int(candidate["firstTimeMs"]), pivot.time_ms)
        candidate["lastTimeMs"] = max(int(candidate["lastTimeMs"]), pivot.time_ms)
        candidate["atr"] = statistics.fmean([float(candidate["atr"]), pivot.atr])

    public: list[dict[str, Any]] = []
    for cluster in clusters:
        prices = [float(value) for value in cluster["prices"]]
        spread = max(prices) - min(prices) if len(prices) > 1 else 0.0
        half_width = max(float(cluster["atr"]) * 0.28, spread / 2)
        public.append({
            "price": float(cluster["center"]),
            "lower": float(cluster["center"]) - half_width,
            "upper": float(cluster["center"]) + half_width,
            "touches": int(cluster["touches"]),
            "supportTouches": int(cluster["supportTouches"]),
            "resistanceTouches": int(cluster["resistanceTouches"]),
            "firstTimeMs": int(cluster["firstTimeMs"]),
            "lastTimeMs": int(cluster["lastTimeMs"]),
            "strength": int(cluster["touches"]),
        })
    public.sort(key=lambda row: float(row["price"]))
    return public


def _interval_index(levels: list[dict[str, Any]], value: float) -> int | None:
    if len(levels) < 2:
        return None
    centers = [float(row["price"]) for row in levels]
    for index in range(len(centers) - 1):
        if centers[index] <= value <= centers[index + 1]:
            return index
    if value < centers[0]:
        return -1
    return len(centers) - 1


def derive_price_zones(
    candles: list[dict[str, Any]], anchor_equity: float | None = None
) -> dict[str, Any]:
    """Build zones strictly from confirmed structural levels.

    Intervals between adjacent structural support/resistance clusters are the
    visible price zones.  Outer discovery zones use the current ATR only for
    display extent; they are marked unconfirmed and are never a trading signal.
    """
    levels = cluster_structural_levels(candles)
    if not candles:
        return {"levels": levels, "zones": [], "activeZone": None}
    close = _number(candles[-1]["close"])
    anchor = float(anchor_equity) if anchor_equity and anchor_equity > 0 else _number(candles[0]["close"])
    if len(levels) < 2:
        return {"levels": levels, "zones": [], "activeZone": None}

    anchor_index = _interval_index(levels, anchor)
    active_index = _interval_index(levels, close)
    if anchor_index is None or active_index is None:
        return {"levels": levels, "zones": [], "activeZone": None}

    atrs = atr_values(candles)
    positive_ranges = [
        _number(row["high"]) - _number(row["low"]) for row in candles
        if _number(row["high"]) > _number(row["low"])
    ]
    fallback = statistics.median(positive_ranges) if positive_ranges else max(close * 0.001, 1e-9)
    current_atr = next((value for value in reversed(atrs) if value and value > 0), fallback) or fallback

    zones: list[dict[str, Any]] = []
    centers = [float(row["price"]) for row in levels]
    # One ATR-backed discovery interval on either side keeps the chart readable,
    # but its confirmed flag prevents it from being treated as market structure.
    ext_centers = [centers[0] - current_atr * 1.6, *centers, centers[-1] + current_atr * 1.6]
    adjusted_anchor_index = anchor_index + 1
    adjusted_active_index = active_index + 1
    for index in range(len(ext_centers) - 1):
        lower, upper = ext_centers[index], ext_centers[index + 1]
        label_index = index - adjusted_anchor_index
        zones.append({
            "index": label_index,
            "label": "Zone 0" if label_index == 0 else f"Zone {label_index:+d}",
            "lower": lower,
            "upper": upper,
            "confirmed": 0 < index < len(ext_centers) - 2,
            "active": index == adjusted_active_index,
        })
    active = next((row for row in zones if row["active"]), None)
    return {"levels": levels, "zones": zones, "activeZone": active}


def bollinger_events(
    candles: list[dict[str, Any]], bands: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_time = {int(row["timeMs"]): row for row in bands}
    events: list[dict[str, Any]] = []
    previous_state = "inside"
    for candle in candles:
        band = by_time.get(int(candle["timeMs"]))
        if not band:
            continue
        close = _number(candle["close"])
        state = "above" if close > float(band["upper"]) else "below" if close < float(band["lower"]) else "inside"
        if state in {"above", "below"} and state != previous_state:
            events.append({
                "kind": "bb_upper" if state == "above" else "bb_lower",
                "timeMs": int(candle["timeMs"]),
                "equity": close,
                "bandValue": float(band["upper"] if state == "above" else band["lower"]),
            })
        elif state == "inside" and previous_state in {"above", "below"}:
            events.append({
                "kind": "bb_reentry",
                "from": previous_state,
                "timeMs": int(candle["timeMs"]),
                "equity": close,
                "bandValue": float(band["middle"]),
            })
        previous_state = state
    return events


def walk_forward_backtest(samples: list[dict[str, Any]], timeframe: str) -> dict[str, Any]:
    candles = aggregate_ohlc(samples, timeframe)
    bands = bollinger_bands(candles)
    bb = bollinger_events(candles, bands)
    transitions: list[dict[str, Any]] = []
    previous_label: str | None = None
    durations: list[int] = []
    start_index = 0
    for index in range(20, len(candles)):
        prefix = candles[:index + 1]
        anchor = _number(candles[0]["close"])
        active = derive_price_zones(prefix, anchor).get("activeZone")
        label = str(active.get("label")) if isinstance(active, dict) else ""
        if not label:
            continue
        if previous_label is None:
            previous_label, start_index = label, index
            continue
        if label != previous_label:
            transitions.append({
                "timeMs": int(candles[index]["timeMs"]),
                "from": previous_label,
                "to": label,
                "candleIndex": index,
            })
            durations.append(index - start_index)
            previous_label, start_index = label, index

    false_breakouts = 0
    for offset, transition in enumerate(transitions):
        origin = transition["from"]
        index = int(transition["candleIndex"])
        later = transitions[offset + 1] if offset + 1 < len(transitions) else None
        if later and later["to"] == origin and int(later["candleIndex"]) - index <= 3:
            false_breakouts += 1

    return {
        "timeframe": normalize_timeframe(timeframe),
        "candleCount": len(candles),
        "zoneTransitionCount": len(transitions),
        "averageZoneDurationCandles": (statistics.fmean(durations) if durations else 0.0),
        "falseBreakoutCount": false_breakouts,
        "falseBreakoutRate": (false_breakouts / len(transitions) if transitions else 0.0),
        "bollingerUpperCrosses": sum(1 for row in bb if row["kind"] == "bb_upper"),
        "bollingerLowerCrosses": sum(1 for row in bb if row["kind"] == "bb_lower"),
        "bollingerReentries": sum(1 for row in bb if row["kind"] == "bb_reentry"),
        "transitions": transitions[-100:],
    }
