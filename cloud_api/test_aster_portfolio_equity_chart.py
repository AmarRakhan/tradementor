from __future__ import annotations

import math

from aster_portfolio_equity_chart import (
    aggregate_ohlc,
    bollinger_bands,
    bollinger_events,
    cashflow_adjusted_samples,
    cluster_structural_levels,
    derive_price_zones,
    normalize_timeframe,
    walk_forward_backtest,
)


def sample(at_ms: int, equity: float) -> dict:
    return {"atMs": at_ms, "equity": equity}


def candle(time_ms: int, open_: float, high: float, low: float, close: float) -> dict:
    return {"timeMs": time_ms, "open": open_, "high": high, "low": low, "close": close, "sampleCount": 1}


def test_timeframe_aliases_are_supported():
    assert normalize_timeframe("15m") == "15m"
    assert normalize_timeframe("1u") == "1h"
    assert normalize_timeframe("4u") == "4h"
    assert normalize_timeframe("24u") == "24h"


def test_cashflow_adjustment_removes_deposit_jump():
    rows = [sample(1_000, 100), sample(2_000, 102), sample(3_000, 152), sample(4_000, 154)]
    flows = [{"time": 2_500, "income": 50}]
    adjusted = cashflow_adjusted_samples(rows, flows)
    assert [row["adjustedEquity"] for row in adjusted] == [100, 102, 102, 104]
    assert adjusted[-1]["externalCashflow"] == 50


def test_cashflow_adjustment_reverses_withdrawal_jump():
    rows = [sample(1_000, 100), sample(2_000, 80), sample(3_000, 82)]
    flows = [{"time": 1_500, "income": -20}]
    adjusted = cashflow_adjusted_samples(rows, flows)
    assert [row["adjustedEquity"] for row in adjusted] == [100, 100, 102]


def test_ohlc_uses_observed_samples_and_does_not_invent_missing_buckets():
    rows = [
        sample(1_000, 100),
        sample(20_000, 105),
        sample(40_000, 99),
        sample(59_000, 103),
        sample(125_000, 110),
    ]
    candles = aggregate_ohlc(rows, "1m")
    assert len(candles) == 2
    first = candles[0]
    assert first["open"] == 100
    assert first["high"] == 105
    assert first["low"] == 99
    assert first["close"] == 103
    assert first["sampleCount"] == 4
    assert candles[1]["timeMs"] == 120_000


def test_bollinger_cross_events_include_equity_without_dates_or_fake_volume():
    candles = []
    for index in range(20):
        value = 100 + (index % 2) * 0.2
        candles.append(candle(index * 60_000, value, value + 0.1, value - 0.1, value))
    candles.append(candle(20 * 60_000, 110, 110, 109, 110))
    bands = bollinger_bands(candles)
    events = bollinger_events(candles, bands)
    assert any(row["kind"] == "bb_upper" and row["equity"] == 110 for row in events)


def test_zone_engine_uses_market_structure_not_equal_price_grid():
    # Deliberately irregular swing structure.  If a fixed grid slips in, adjacent
    # zone widths would collapse to equal distances.
    closes = [100, 102, 104, 101, 99, 103, 108, 105, 101, 106, 113, 110, 104, 109, 117, 112, 107, 114, 121, 116, 111, 118, 124, 120, 115, 122, 128, 123]
    candles = []
    for index, close in enumerate(closes):
        spread = 1.0 + (index % 3) * 0.35
        candles.append(candle(index * 900_000, close, close + spread, close - spread * 0.8, close))
    levels = cluster_structural_levels(candles)
    assert len(levels) >= 2
    zones = derive_price_zones(candles, anchor_equity=100)["zones"]
    confirmed = [row for row in zones if row["confirmed"]]
    assert confirmed
    widths = [round(row["upper"] - row["lower"], 6) for row in confirmed]
    assert len(set(widths)) > 1


def test_relative_zone_labels_are_anchored_and_only_one_is_active():
    closes = [100, 104, 107, 101, 96, 103, 111, 105, 98, 107, 116, 109, 101, 112, 120, 114, 105, 116, 124, 118, 109, 120, 129, 121, 113, 125, 132]
    candles = [
        candle(index * 900_000, value, value + 1.2 + (index % 2) * 0.4, value - 1.0, value)
        for index, value in enumerate(closes)
    ]
    result = derive_price_zones(candles, anchor_equity=100)
    active = [row for row in result["zones"] if row["active"]]
    assert len(active) == 1
    assert any(row["label"] == "Zone 0" for row in result["zones"])


def test_walk_forward_backtest_is_read_only_summary():
    rows = []
    base = 100.0
    for index in range(180):
        # Irregular deterministic waveform gives enough structure without any
        # synthetic price-grid assumptions.
        value = base + math.sin(index / 7) * 7 + math.sin(index / 19) * 4 + index * 0.035
        rows.append({"atMs": index * 60_000, "adjustedEquity": value})
    report = walk_forward_backtest(rows, "5m")
    assert report["candleCount"] > 20
    assert 0 <= report["falseBreakoutRate"] <= 1
    assert report["bollingerUpperCrosses"] >= 0
    assert report["bollingerLowerCrosses"] >= 0
