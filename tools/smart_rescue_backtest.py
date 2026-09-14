from __future__ import annotations

"""Read-only historical 1m Smart Rescue DCA backtest against Aster public candles.

This is a behavioural/risk replay, not a profit promise.  It uses minute closes
only so no intrabar high/low ordering is invented for the trailing-recovery rule.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import argparse
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any

import httpx

from aster_smart_rescue import advance_state, apply_fill, build_position_state

BASE_URL = "https://fapi.asterdex.com"
INTERVAL_MS = 60_000


@dataclass(frozen=True)
class Config:
    name: str
    rescue_range: float
    dca_count: int
    growth: float
    recovery: float = 0.30
    leverage: int = 50
    start_margin: float = 0.15


CONFIGS = (
    Config("5pct-5dca-1.35x", 5, 5, 1.35),
    Config("10pct-10dca-1.35x", 10, 10, 1.35),
    Config("20pct-25dca-1.20x", 20, 25, 1.20),
    Config("custom-12pct-16dca-1.25x", 12, 16, 1.25),
)


def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    cursor = start_ms
    with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
        while cursor <= end_ms:
            response = client.get("/fapi/v1/klines", params={
                "symbol": symbol, "interval": "1m", "startTime": cursor,
                "endTime": end_ms, "limit": 1000,
            })
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                break
            batch = []
            for item in payload:
                if not isinstance(item, list) or len(item) < 5:
                    continue
                ts = int(item[0]); close = float(item[4])
                if start_ms <= ts <= end_ms and close > 0 and math.isfinite(close):
                    batch.append({"ts": ts, "close": close})
            rows.extend(batch)
            last = max((int(x[0]) for x in payload if isinstance(x, list) and x), default=cursor)
            next_cursor = last + INTERVAL_MS
            if next_cursor <= cursor or len(payload) < 1000:
                break
            cursor = next_cursor
    unique = {int(row["ts"]): row for row in rows}
    return [unique[key] for key in sorted(unique)]


def window_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    prices = [r["close"] for r in rows]
    start, end = prices[0], prices[-1]
    running_high = start
    max_dd = 0.0
    travel = 0.0
    for prev, price in zip(prices, prices[1:]):
        travel += abs(price / prev - 1)
        running_high = max(running_high, price)
        max_dd = max(max_dd, 1 - price / running_high)
    net = end / start - 1
    return {"returnPct": net * 100, "maxDrawdownPct": max_dd * 100,
            "travelPct": travel * 100, "rangePct": (max(prices) / min(prices) - 1) * 100}


def choose_regimes(rows: list[dict[str, float]], hours: int = 12) -> list[dict[str, Any]]:
    width = hours * 60
    step = 60
    candidates = []
    for start in range(0, len(rows) - width + 1, step):
        window = rows[start:start + width]
        metrics = window_metrics(window)
        candidates.append({"start": start, "end": start + width, "metrics": metrics})
    if not candidates:
        raise RuntimeError("onvoldoende 1m-data voor regime-selectie")

    def unique_pick(sorted_rows: list[dict[str, Any]], used: set[int]) -> dict[str, Any]:
        for row in sorted_rows:
            # Avoid selecting nearly the same 12h period twice.
            if all(abs(row["start"] - prev) >= width for prev in used):
                used.add(row["start"]); return row
        row = sorted_rows[0]; used.add(row["start"]); return row

    used: set[int] = set()
    rising = unique_pick(sorted(candidates, key=lambda x: (x["metrics"]["returnPct"], -x["metrics"]["maxDrawdownPct"]), reverse=True), used)
    strong = unique_pick(sorted(candidates, key=lambda x: x["metrics"]["returnPct"]), used)
    crash = unique_pick(sorted(candidates, key=lambda x: x["metrics"]["maxDrawdownPct"], reverse=True), used)
    choppy_pool = sorted(candidates, key=lambda x: (abs(x["metrics"]["returnPct"]), -x["metrics"]["travelPct"]))
    choppy = unique_pick(choppy_pool, used)
    correction_pool = [x for x in candidates if x["metrics"]["returnPct"] < 0]
    correction_pool = sorted(correction_pool or candidates, key=lambda x: abs(x["metrics"]["returnPct"] + 2.5))
    correction = unique_pick(correction_pool, used)

    labelled = [("rising", rising), ("choppy", choppy), ("normal_correction", correction),
                ("strong_decline", strong), ("crashlike_drawdown", crash)]
    result = []
    for label, item in labelled:
        block = rows[item["start"]:item["end"]]
        result.append({"name": label, "rows": block, "metrics": item["metrics"],
                       "startTs": int(block[0]["ts"]), "endTs": int(block[-1]["ts"])})
    return result


def replay(block: list[dict[str, float]], cfg: Config) -> dict[str, Any]:
    entry = block[0]["close"]
    state = build_position_state(initial_entry_price=entry, start_margin_usd=cfg.start_margin,
        rescue_range_percent=cfg.rescue_range, dca_count=cfg.dca_count,
        order_growth_multiplier=cfg.growth, trailing_recovery_percent=cfg.recovery,
        config_version=1)
    qty = cfg.start_margin * cfg.leverage / entry
    total_margin = cfg.start_margin
    avg_entry = entry
    fills: list[dict[str, Any]] = []
    recoveries: list[float] = []
    max_notional = total_margin * cfg.leverage
    max_margin = total_margin
    max_drawdown_on_margin = 0.0
    max_loss_usd = 0.0

    for candle in block[1:]:
        price = candle["close"]
        pnl = qty * (price - avg_entry)
        max_loss_usd = min(max_loss_usd, pnl)
        if total_margin > 0:
            max_drawdown_on_margin = max(max_drawdown_on_margin, max(0.0, -pnl / total_margin * 100))
        state, executable = advance_state(state, mark_price=price)
        if executable is None:
            continue
        margin = float(executable["orderMarginUsd"])
        add_qty = margin * cfg.leverage / price
        new_qty = qty + add_qty
        avg_entry = ((avg_entry * qty) + (price * add_qty)) / new_qty
        qty = new_qty
        total_margin += margin
        max_margin = max(max_margin, total_margin)
        max_notional = max(max_notional, total_margin * cfg.leverage)
        recovery = (avg_entry / price - 1) * 100
        recoveries.append(recovery)
        fills.append({"ts": int(candle["ts"]), "level": int(executable["levelIndex"]),
                      "price": price, "marginUsd": margin, "averageEntry": avg_entry,
                      "recoveryToBreakEvenPct": recovery})
        state = apply_fill(state, level_index=int(executable["levelIndex"]), fill_price=price,
            fill_qty=add_qty, actual_margin_usd=margin, order_id=f"backtest-{candle['ts']}",
            timestamp_ms=int(candle["ts"]))

    final_price = block[-1]["close"]
    final_pnl = qty * (final_price - avg_entry)
    return {
        "starts": 1, "rescueOrders": len(fills), "skippedLevels": int(state.get("skippedCount", 0)),
        "maxDcaCount": int(state.get("filledCount", 0)), "maxMarginUsd": max_margin,
        "maxNotionalUsd": max_notional, "maxPositionDrawdownPctOnMargin": max_drawdown_on_margin,
        "maxUnrealizedLossUsd": max_loss_usd,
        "averageBreakEvenRecoveryPct": mean(recoveries) if recoveries else 0.0,
        "worstBreakEvenRecoveryPct": max(recoveries) if recoveries else 0.0,
        "rejectedOrders": 0, "duplicateOrders": 0, "tpEvents": 0,
        "finalAverageEntry": avg_entry, "finalPrice": final_price, "finalPnlUsd": final_pnl,
        "fills": fills,
    }


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    recoveries = [x["averageBreakEvenRecoveryPct"] for x in results if x["rescueOrders"]]
    return {
        "starts": sum(x["starts"] for x in results),
        "rescueOrders": sum(x["rescueOrders"] for x in results),
        "skippedLevels": sum(x["skippedLevels"] for x in results),
        "averageDcaCount": mean(x["rescueOrders"] for x in results),
        "maxDcaCount": max(x["maxDcaCount"] for x in results),
        "maxMarginUsedUsd": max(x["maxMarginUsd"] for x in results),
        "maxNotionalUsd": max(x["maxNotionalUsd"] for x in results),
        "largestPositionDrawdownPctOnMargin": max(x["maxPositionDrawdownPctOnMargin"] for x in results),
        "averageBreakEvenRecoveryPct": mean(recoveries) if recoveries else 0.0,
        "worstBreakEvenRecoveryPct": max(x["worstBreakEvenRecoveryPct"] for x in results),
        "rejectedOrders": sum(x["rejectedOrders"] for x in results),
        "duplicateOrders": sum(x["duplicateOrders"] for x in results),
        "tpEvents": sum(x["tpEvents"] for x in results),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output", default="docs/smart-rescue-backtest-20260914.json")
    args = parser.parse_args()
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    rows = fetch_klines(args.symbol, int(start.timestamp()*1000), int(end.timestamp()*1000))
    if len(rows) < 24 * 60:
        raise RuntimeError(f"slechts {len(rows)} candles opgehaald")
    regimes = choose_regimes(rows)
    payload: dict[str, Any] = {
        "generatedAt": datetime.now(timezone.utc).isoformat(), "source": BASE_URL,
        "symbol": args.symbol, "interval": "1m", "candleModel": "minute-close-only",
        "candleCount": len(rows), "dataStart": iso(int(rows[0]["ts"])), "dataEnd": iso(int(rows[-1]["ts"])),
        "note": "Behavioural/risk replay; no fees/funding, no claim of future profitability. Portfolio TP is covered separately by deterministic integration tests.",
        "regimes": [], "configs": {},
    }
    for regime in regimes:
        payload["regimes"].append({"name": regime["name"], "start": iso(regime["startTs"]),
            "end": iso(regime["endTs"]), **regime["metrics"]})
    for cfg in CONFIGS:
        per = []
        for regime in regimes:
            result = replay(regime["rows"], cfg)
            per.append({"regime": regime["name"], **{k:v for k,v in result.items() if k != "fills"},
                        "fills": result["fills"]})
        payload["configs"][cfg.name] = {"settings": cfg.__dict__, "aggregate": aggregate(per), "perRegime": per}
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out), "candles": len(rows), "regimes": payload["regimes"],
                      "aggregates": {k:v["aggregate"] for k,v in payload["configs"].items()}}, indent=2))


if __name__ == "__main__":
    main()
