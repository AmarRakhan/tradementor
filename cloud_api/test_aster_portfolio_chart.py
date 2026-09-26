from pathlib import Path

from aster_portfolio_chart import (
    active_zone,
    aggregate_trade_activity,
    bucket_start_ms,
    derive_equity_zones,
    external_cashflow_markers,
    latest_contiguous_candles,
    merge_equity_sample,
    public_candle,
    strategy_audit_trade_markers,
    zone_shadow_backtest,
)


def candle(at_ms, open_, high, low, close):
    return {"atMs": at_ms, "time": at_ms // 1000, "open": open_, "high": high, "low": low, "close": close}


def test_equity_sample_builds_real_ohlc_without_inventing_values():
    first = merge_equity_sample(None, equity=100.0, source_at_ms=61_000, timeframe="1m")
    second = merge_equity_sample(first, equity=103.0, source_at_ms=75_000, timeframe="1m")
    third = merge_equity_sample(second, equity=98.0, source_at_ms=89_000, timeframe="1m")
    row = public_candle(third)
    assert row == {
        "time": 60,
        "atMs": 60_000,
        "open": 100.0,
        "high": 103.0,
        "low": 98.0,
        "close": 98.0,
        "samples": 3,
        "firstSampleAtMs": 61_000,
        "sourceAtMs": 89_000,
    }


def test_timeframe_buckets_match_requested_contract():
    stamp = 17_111_111
    assert bucket_start_ms(stamp, "1m") % 60_000 == 0
    assert bucket_start_ms(stamp, "5m") % 300_000 == 0
    assert bucket_start_ms(stamp, "15m") % 900_000 == 0
    assert bucket_start_ms(stamp, "1u") % 3_600_000 == 0
    assert bucket_start_ms(stamp, "4u") % 14_400_000 == 0
    assert bucket_start_ms(stamp, "24u") % 86_400_000 == 0


def test_trade_markers_are_bucketed_and_tp_is_aggregated():
    activity = {
        "entries": [
            {"timestampMs": 61_000, "side": "LONG", "executedNotionalUsd": 12.0},
            {"timestampMs": 65_000, "side": "LONG", "executedNotionalUsd": 8.0},
            {"timestampMs": 66_000, "side": "SHORT", "executedNotionalUsd": 10.0},
        ],
        "exits": [
            {"timestampMs": 70_000, "side": "LONG", "realizedPnlUsd": 1.25},
            {"timestampMs": 72_000, "side": "SHORT", "realizedPnlUsd": 0.75},
        ],
    }
    rows = aggregate_trade_activity(activity, "1m")
    assert len(rows) == 3
    long_entry = next(row for row in rows if row["kind"] == "entry" and row["side"] == "LONG")
    assert long_entry["count"] == 2
    assert long_entry["notionalUsd"] == 20.0
    tp = next(row for row in rows if row["kind"] == "tp")
    assert tp["count"] == 2
    assert tp["realizedPnlUsd"] == 2.0
    assert "TP" in tp["label"]


def test_external_cashflows_remain_separate_from_trading_markers():
    rows = external_cashflow_markers([
        {"incomeType": "TRANSFER", "income": "50", "time": 61_000},
        {"incomeType": "REALIZED_PNL", "income": "5", "time": 62_000},
        {"incomeType": "TRANSFER", "income": "-10", "time": 63_000},
    ], "1m")
    assert len(rows) == 2
    deposit = next(row for row in rows if row["cashflowType"] == "DEPOSIT")
    withdrawal = next(row for row in rows if row["cashflowType"] == "WITHDRAWAL")
    assert deposit["kind"] == withdrawal["kind"] == "cashflow"
    assert deposit["amountUsd"] == 50.0
    assert withdrawal["amountUsd"] == -10.0
    assert "STORTING" in deposit["label"]
    assert "OPNAME" in withdrawal["label"]


def test_zones_require_confirmed_swings_and_use_cycle_reference_for_zone_zero():
    closes = [100, 102, 105, 103, 100, 98, 96, 99, 103, 106, 104, 101, 98, 95, 97, 101, 105, 107, 104, 100, 97, 96, 99, 103, 106, 104, 100, 98, 101, 105]
    candles = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else close
        candles.append(candle((index + 1) * 900_000, opened, max(opened, close) + 1, min(opened, close) - 1, close))
    zones = derive_equity_zones(candles, 100.0)
    assert zones
    assert any(zone["index"] == 0 for zone in zones)
    assert all(zone["source"] == "confirmed-swings+sr-cluster+atr" for zone in zones)
    current = active_zone(zones, candles[-1]["close"])
    assert isinstance(current, int)
    shadow = zone_shadow_backtest(candles, 100.0)
    assert shadow["readOnly"] is True
    assert shadow["ordersSent"] == 0
    assert shadow["usesFutureCandles"] is False


def test_no_fixed_zone_grid_when_market_has_no_confirmed_structure():
    flat = [candle((index + 1) * 900_000, 100, 100, 100, 100) for index in range(30)]
    assert derive_equity_zones(flat, 100.0) == []


def test_duplicate_confirmed_sample_does_not_inflate_ohlc_sample_count():
    first = merge_equity_sample(None, equity=100.0, source_at_ms=61_000, timeframe="1m")
    duplicate = merge_equity_sample(first, equity=100.0, source_at_ms=61_000, timeframe="1m")
    assert duplicate["sampleCount"] == 1
    assert duplicate["open"] == duplicate["high"] == duplicate["low"] == duplicate["close"] == 100.0


def test_latest_contiguous_candles_never_bridges_an_unobserved_gap():
    rows = [
        candle(900_000, 100, 101, 99, 100),
        candle(1_800_000, 100, 102, 99, 101),
        candle(4_500_000, 103, 104, 102, 103),
        candle(5_400_000, 103, 105, 102, 104),
    ]
    recent = latest_contiguous_candles(rows, "15m")
    assert [row["atMs"] for row in recent] == [4_500_000, 5_400_000]


def test_recent_strategy_audit_events_become_immediate_chart_markers():
    rows = [
        {"event": "MULTI_BB_ENTRY", "timestampMs": 61_000, "side": "SHORT", "originZone": -2, "soldierRole": "ZONE_BASE"},
        {"event": "MULTI_BB_DCA", "timestampMs": 65_000, "side": "SHORT"},
        {"event": "MULTI_BB_TP", "timestampMs": 70_000, "side": "LONG"},
        {"event": "MULTI_BB_DCA_BLOCKED", "timestampMs": 71_000, "side": "LONG"},
    ]
    markers = strategy_audit_trade_markers(rows, "1m")
    assert len(markers) == 2
    short = next(row for row in markers if row["kind"] == "entry")
    assert short["side"] == "SHORT"
    assert short["count"] == 2
    assert short["activityTypes"] == ["DCA", "ENTRY"]
    assert short["originZones"] == [-2]
    assert short["soldierRoles"] == ["ZONE_BASE"]
    tp = next(row for row in markers if row["kind"] == "tp")
    assert tp["side"] == "ALL"
    assert tp["count"] == 1


def test_live_portfolio_event_endpoint_is_read_only_and_does_not_poll_aster():
    source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    start = source.index('@app.get("/v1/me/aster/portfolio-chart/events")')
    end = source.index('@app.get("/v1/me/aster/portfolio-chart")', start + 1)
    block = source[start:end]
    assert "AsterV3Client(" not in block
    assert "portfolio_chart_strategy_audit_markers" in block
    assert '"ordersSent": 0' in block
    assert "confirmed Strategy-2 audit events; no exchange polling" in block


def test_build432_cashflow_markers_aggregate_same_direction_but_never_net_opposite_flows():
    rows=external_cashflow_markers([
        {"incomeType":"DEPOSIT","income":"100","time":61_000},
        {"incomeType":"TRANSFER","income":"50","time":62_000},
        {"incomeType":"WITHDRAWAL","income":"-25","time":63_000},
        {"incomeType":"FUNDING_FEE","income":"-2","time":64_000},
    ],"1m")
    assert len(rows)==2
    deposit=next(row for row in rows if row["cashflowType"]=="DEPOSIT")
    withdrawal=next(row for row in rows if row["cashflowType"]=="WITHDRAWAL")
    assert deposit["amountUsd"]==150
    assert deposit["count"]==2
    assert withdrawal["amountUsd"]==-25
    assert withdrawal["count"]==1
