from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import math
import os
import statistics
import time

import httpx

BASE = "https://fapi.asterdex.com"
SYMBOLS = [s.strip().upper() for s in os.getenv("BB_BACKTEST_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
HOURS = int(os.getenv("BB_BACKTEST_HOURS", "48"))
DCA_DISTANCE_PCT = float(os.getenv("BB_BACKTEST_DCA_PCT", "0.30"))
OUTCOME_HORIZON_MINUTES = int(os.getenv("BB_BACKTEST_HORIZON_MINUTES", "60"))


def fetch_1m(client: httpx.Client, symbol: str, start_ms: int, end_ms: int) -> list[list]:
    rows: list[list] = []
    cursor = start_ms
    while cursor < end_ms:
        response = client.get(
            f"{BASE}/fapi/v1/klines",
            params={"symbol": symbol, "interval": "1m", "limit": 1000, "startTime": cursor, "endTime": end_ms},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"{symbol}: invalid kline payload")
        batch = [row for row in payload if isinstance(row, list) and len(row) >= 7]
        if not batch:
            break
        for row in batch:
            open_ms = int(row[0])
            if start_ms <= open_ms < end_ms:
                rows.append(row)
        last_open = int(batch[-1][0])
        next_cursor = last_open + 60_000
        if next_cursor <= cursor:
            raise RuntimeError(f"{symbol}: kline pagination did not advance")
        cursor = next_cursor
        if len(batch) < 1000:
            break
        time.sleep(0.12)
    unique = {int(row[0]): row for row in rows}
    return [unique[key] for key in sorted(unique)]


def mean(values):
    return sum(values) / len(values) if values else None


def summarize_outcomes(rows, decisions, side):
    adverse = []
    favorable = []
    dca_counts = []
    positive_minutes = []
    for index, entry, _lower, _upper in decisions:
        future = rows[index + 1:index + 1 + OUTCOME_HORIZON_MINUTES]
        if not future:
            continue
        highs = [float(row[2]) for row in future]
        lows = [float(row[3]) for row in future]
        closes = [float(row[4]) for row in future]
        if side == "LONG":
            adv = max(0.0, (entry - min(lows)) / entry * 100.0)
            fav = max(0.0, (max(highs) - entry) / entry * 100.0)
            hit = next((minute for minute, close in enumerate(closes, 1) if close > entry), None)
        else:
            adv = max(0.0, (max(highs) - entry) / entry * 100.0)
            fav = max(0.0, (entry - min(lows)) / entry * 100.0)
            hit = next((minute for minute, close in enumerate(closes, 1) if close < entry), None)
        adverse.append(adv)
        favorable.append(fav)
        dca_counts.append(min(20, int(math.floor((adv + 1e-12) / DCA_DISTANCE_PCT))))
        if hit is not None:
            positive_minutes.append(hit)
    return {
        "sampleCount": len(adverse),
        "averageAdverseMovePct": round(mean(adverse) or 0.0, 6),
        "averageFavorableMovePct": round(mean(favorable) or 0.0, 6),
        "averageApproxDcaCountAt0_30Pct": round(mean(dca_counts) or 0.0, 6),
        "averageMinutesToPositiveWhenReached": round(mean(positive_minutes) or 0.0, 3),
        "positiveWithinHorizonPct": round((len(positive_minutes) / len(adverse) * 100.0) if adverse else 0.0, 4),
    }


def evaluate_symbol(rows):
    buckets: deque[tuple[int, float]] = deque(maxlen=20)
    all_long = []
    all_short = []
    allowed_long = []
    allowed_short = []
    active_bucket = None

    for index, row in enumerate(rows):
        open_ms = int(row[0])
        close = float(row[4])
        bucket = open_ms // 900_000 * 900_000
        if active_bucket != bucket:
            active_bucket = bucket
            buckets.append((bucket, close))
        else:
            buckets[-1] = (bucket, close)
        if len(buckets) < 20:
            continue
        closes = [value for _, value in buckets]
        center = statistics.fmean(closes)
        sigma = statistics.pstdev(closes)
        lower = center - 2.0 * sigma
        upper = center + 2.0 * sigma
        decision = (index, close, lower, upper)
        all_long.append(decision)
        all_short.append(decision)
        if close < lower:
            allowed_long.append(decision)
        if close > upper:
            allowed_short.append(decision)

    return {
        "potentialLongEntries": len(all_long),
        "allowedLongEntries": len(allowed_long),
        "rejectedLongEntries": len(all_long) - len(allowed_long),
        "potentialShortEntries": len(all_short),
        "allowedShortEntries": len(allowed_short),
        "rejectedShortEntries": len(all_short) - len(allowed_short),
        "longSeatBlockedPct": round((1.0 - len(allowed_long) / len(all_long)) * 100.0, 4) if all_long else 0.0,
        "shortSeatBlockedPct": round((1.0 - len(allowed_short) / len(all_short)) * 100.0, 4) if all_short else 0.0,
        "offLongOutcomes": summarize_outcomes(rows, all_long, "LONG"),
        "onLongOutcomes": summarize_outcomes(rows, allowed_long, "LONG"),
        "offShortOutcomes": summarize_outcomes(rows, all_short, "SHORT"),
        "onShortOutcomes": summarize_outcomes(rows, allowed_short, "SHORT"),
    }


def aggregate(symbol_results):
    keys = [
        "potentialLongEntries", "allowedLongEntries", "rejectedLongEntries",
        "potentialShortEntries", "allowedShortEntries", "rejectedShortEntries",
    ]
    out = {key: sum(result[key] for result in symbol_results.values()) for key in keys}
    out["longSeatBlockedPct"] = round(out["rejectedLongEntries"] / out["potentialLongEntries"] * 100.0, 4) if out["potentialLongEntries"] else 0.0
    out["shortSeatBlockedPct"] = round(out["rejectedShortEntries"] / out["potentialShortEntries"] * 100.0, 4) if out["potentialShortEntries"] else 0.0
    return out


def main():
    end_ms = int(time.time() * 1000 // 60_000 * 60_000)
    start_ms = end_ms - HOURS * 60 * 60 * 1000
    report = {
        "method": "No-lookahead technical entry-filter backtest. 1m Aster futures candles are replayed chronologically; each decision uses the latest live 1m close against the current 15m Bollinger state built only from information available at that minute. Future bars are used only for outcome measurement.",
        "warning": "Historical results do not guarantee future performance. This is not a full portfolio-PnL backtest; it validates the entry gate and measures its historical selection effect.",
        "symbols": SYMBOLS,
        "startUtc": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
        "endUtc": datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat(),
        "hours": HOURS,
        "horizonMinutes": OUTCOME_HORIZON_MINUTES,
        "dcaDistancePctForApproximation": DCA_DISTANCE_PCT,
        "perSymbol": {},
    }
    with httpx.Client(timeout=25.0, headers={"User-Agent": "tradementor-bollinger-backtest/1.0"}) as client:
        for symbol in SYMBOLS:
            rows = fetch_1m(client, symbol, start_ms, end_ms)
            if len(rows) < 1000:
                raise RuntimeError(f"{symbol}: only {len(rows)} 1m candles; insufficient for representative replay")
            result = evaluate_symbol(rows)
            result["minuteCandles"] = len(rows)
            report["perSymbol"][symbol] = result
            time.sleep(0.2)
    report["aggregate"] = aggregate(report["perSymbol"])
    if report["aggregate"]["allowedLongEntries"] <= 0 or report["aggregate"]["allowedShortEntries"] <= 0:
        raise RuntimeError("Backtest window produced no allowed entries on one side")
    os.makedirs("artifacts", exist_ok=True)
    with open("artifacts/bollinger-entry-filter-backtest.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
