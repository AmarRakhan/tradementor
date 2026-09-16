from __future__ import annotations

import json
import math
import time

from aster_bollinger_entry_filter import BollingerEntryRejected, require_bollinger_entry

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


class SyntheticMarket:
    def __init__(self, timeframe: str, closes: list[float]):
        self.timeframe = timeframe
        self.closes = closes

    def klines(self, *, symbol, interval, limit):
        assert interval == self.timeframe
        step = INTERVAL_MS[interval]
        now = int(time.time() * 1000)
        last_open = now // step * step
        start = last_open - (len(self.closes) - 1) * step
        return [[start + i * step, "0", "0", "0", str(close), "0"] for i, close in enumerate(self.closes)]


def bands(closes: list[float]):
    window = closes[-20:]
    mean = sum(window) / len(window)
    sigma = math.sqrt(sum((x - mean) ** 2 for x in window) / len(window))
    return mean - 2 * sigma, mean + 2 * sigma


def decision(market, timeframe, side, price, lower, upper, expected):
    allowed = True
    reason = "PASS"
    try:
        require_bollinger_entry(market, symbol="TESTUSDT", side=side, enabled=True, timeframe=timeframe,
                                live_price=price, force_refresh=True, stage="simulation")
    except BollingerEntryRejected as exc:
        allowed = False
        reason = exc.reason_code
    row = {"symbol":"TESTUSDT","side":side,"selectedTimeframe":timeframe,"currentPrice":price,
           "lowerBand":lower,"upperBand":upper,"filterEnabled":True,"entryAllowed":allowed,"reason":reason}
    print("SIM_RESULT " + json.dumps(row, sort_keys=True))
    assert allowed is expected, row


def run(timeframe):
    closes = [100 + i * .25 for i in range(20)]
    lower, upper = bands(closes)
    market = SyntheticMarket(timeframe, closes)
    middle = (lower + upper) / 2
    decision(market, timeframe, "LONG", middle, lower, upper, False)
    decision(market, timeframe, "LONG", lower - .01, lower, upper, True)
    decision(market, timeframe, "LONG", middle, lower, upper, False)
    decision(market, timeframe, "SHORT", upper + .01, lower, upper, True)


for tf in ("1m", "15m", "1h"):
    run(tf)

# Datasource interval contract for all six choices is separately asserted by
# test_aster_bollinger_entry_filter_timeframes.py.
print("SIMULATION_OK timeframes=1m,15m,1h datasourceValidated=1m,5m,15m,1h,4h,1d")
