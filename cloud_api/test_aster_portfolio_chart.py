from pathlib import Path

from aster_portfolio_chart import (
    active_zone,
    active_trades_collection_for_timeframe,
    active_trades_continuity_value,
    active_trades_snapshot,
    aggregate_trade_activity,
    bucket_start_ms,
    derive_equity_zones,
    external_cashflow_markers,
    latest_contiguous_candles,
    latest_established_contiguous_candles,
    latest_zone_ladder_candles,
    merge_active_trades_sample,
    merge_equity_sample,
    public_active_trades_candle,
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
            {"timestampMs": 61_000, "symbol": "BTCUSDT", "side": "LONG", "executedNotionalUsd": 12.0},
            {"timestampMs": 65_000, "symbol": "BTCUSDT", "side": "LONG", "executedNotionalUsd": 8.0},
            {"timestampMs": 66_000, "symbol": "ETHUSDT", "side": "SHORT", "executedNotionalUsd": 10.0},
        ],
        "exits": [
            {"timestampMs": 70_000, "symbol": "BTCUSDT", "side": "LONG", "realizedPnlUsd": 1.25},
            {"timestampMs": 72_000, "symbol": "ETHUSDT", "side": "SHORT", "realizedPnlUsd": 0.75},
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
    assert tp["trades"] == [
        {"symbol": "BTC", "realizedPnlUsd": 1.25, "durationMinutes": 0},
        {"symbol": "ETH", "realizedPnlUsd": 0.75, "durationMinutes": 0},
    ]
    assert "TP" in tp["label"]


def test_tp_duration_uses_first_entry_of_confirmed_cycle_not_latest_dca():
    activity = {
        "entries": [
            {"timestampMs": 60_000, "symbol": "BTCUSDT", "side": "LONG", "quantity": 1.0},
            {"timestampMs": 360_000, "symbol": "BTCUSDT", "side": "LONG", "quantity": 1.0},
        ],
        "exits": [
            {"timestampMs": 1_260_000, "symbol": "BTCUSDT", "side": "LONG", "quantity": 2.0, "realizedPnlUsd": 5.0},
        ],
    }
    rows = aggregate_trade_activity(activity, "1m")
    tp = next(row for row in rows if row["kind"] == "tp")
    assert tp["trades"][0]["symbol"] == "BTC"
    assert tp["trades"][0]["durationMinutes"] == 20


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


def test_established_zone_ladder_survives_a_fresh_runtime_gap_without_bridging_it():
    rows = [
        *[candle((index + 1) * 900_000, 100 + index, 102 + index, 99 + index, 101 + index) for index in range(8)],
        candle(12_600_000, 110, 112, 109, 111),
        candle(13_500_000, 111, 113, 110, 112),
    ]
    latest = latest_contiguous_candles(rows, "15m")
    established = latest_established_contiguous_candles(rows, "15m", min_bars=7)
    assert [row["atMs"] for row in latest] == [12_600_000, 13_500_000]
    assert len(established) == 8
    assert established[-1]["atMs"] == 7_200_000
    assert 12_600_000 not in [row["atMs"] for row in established]


def test_established_zone_ladder_moves_to_newest_segment_after_warmup():
    old = [candle((index + 1) * 900_000, 100, 102, 99, 101) for index in range(8)]
    fresh = [candle(12_600_000 + index * 900_000, 110, 112, 109, 111) for index in range(7)]
    established = latest_established_contiguous_candles(old + fresh, "15m", min_bars=7)
    assert [row["atMs"] for row in established] == [row["atMs"] for row in fresh]


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
    end = source.index('@app.get("/v1/me/aster/portfolio-chart/active-trades")', start + 1)
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


def test_latest_zone_ladder_candles_skips_newer_segment_without_valid_zones():
    closes = [100, 102, 105, 103, 100, 98, 96, 99, 103, 106, 104, 101, 98, 95, 97, 101, 105, 107, 104, 100]
    old = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else close
        old.append(candle((index + 1) * 900_000, opened, max(opened, close) + 1, min(opened, close) - 1, close))
    fresh_start = old[-1]["atMs"] + 3 * 900_000
    fresh = [
        candle(fresh_start + index * 900_000, 120 + index, 121 + index, 119 + index, 120.5 + index)
        for index in range(7)
    ]
    assert derive_equity_zones(old, 100)
    assert derive_equity_zones(fresh, 100) == []
    selected = latest_zone_ladder_candles(old + fresh, "15m", cycle_start_equity=100, min_bars=7)
    assert [row["atMs"] for row in selected] == [row["atMs"] for row in old]

def test_active_trades_snapshot_uses_exchange_open_positions_and_side_correct_pnl():
    snapshot = {
        "positions": [
            {"symbol": "BTCUSDT", "side": "LONG", "quantity": 2, "entryPrice": 100, "markPrice": 103, "unrealizedPnl": 6, "notionalUsd": 206},
            {"symbol": "ETHUSDT", "side": "SHORT", "quantity": 3, "entryPrice": 50, "markPrice": 48, "notionalUsd": 144},
            {"symbol": "FLATUSDT", "side": "LONG", "quantity": 0, "entryPrice": 1, "markPrice": 2},
        ]
    }
    basket = active_trades_snapshot(snapshot)
    assert basket["activeTrades"] == 2
    assert basket["longTrades"] == 1
    assert basket["shortTrades"] == 1
    assert basket["longPnl"] == 6
    assert basket["shortPnl"] == 6
    assert basket["openPnl"] == 12
    assert basket["totalNotional"] == 350
    assert round(basket["pnlPercent"], 6) == round(12 / 350 * 100, 6)


def test_active_trades_continuity_neutralizes_entry_exit_dca_and_partial_close_jumps():
    previous = {
        "value": -10.0,
        "positions": [
            {"key": "BTCUSDT|LONG", "quantity": 2.0, "entryPrice": 100.0, "pnl": -8.0},
            {"key": "ETHUSDT|SHORT", "quantity": 4.0, "entryPrice": 50.0, "pnl": -2.0},
        ],
    }
    # BTC moves +$2 PnL. ETH is partially closed, so its resize is rebased.
    # A new SOL leg starts with -$5 but entry itself must not jump the index.
    current = {
        "positions": [
            {"key": "BTCUSDT|LONG", "quantity": 2.0, "entryPrice": 100.0, "pnl": -6.0},
            {"key": "ETHUSDT|SHORT", "quantity": 2.0, "entryPrice": 50.0, "pnl": -1.0},
            {"key": "SOLUSDT|LONG", "quantity": 1.0, "entryPrice": 20.0, "pnl": -5.0},
        ],
        "openPnl": -12.0,
    }
    assert active_trades_continuity_value(previous, current) == -8.0


def test_active_trades_signed_ohlc_accepts_negative_and_zero_values():
    first = merge_active_trades_sample(None, value=-10.0, source_at_ms=61_000, timeframe="1m")
    second = merge_active_trades_sample(first, value=0.0, source_at_ms=75_000, timeframe="1m")
    third = merge_active_trades_sample(second, value=-15.0, source_at_ms=89_000, timeframe="1m")
    row = public_active_trades_candle(third)
    assert row["open"] == -10.0
    assert row["high"] == 0.0
    assert row["low"] == -15.0
    assert row["close"] == -15.0
    assert active_trades_collection_for_timeframe("15m") == "asterActiveTradesChart15m"


def test_active_trades_endpoint_is_analytics_only_and_never_writes_canonical_account_snapshot():
    source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    start = source.index('@app.get("/v1/me/aster/portfolio-chart/active-trades")')
    end = source.index('@app.get("/v1/me/aster/portfolio-chart")', start + 1)
    block = source[start:end]
    assert "live_authorized=False" in block
    assert 'require_release_feature(user, "active_trades_chart")' in block
    assert '"readOnly": True' in block
    assert '"ordersSent": 0' in block
    assert 'automation_ref.set({"accountSnapshot"' not in block
    assert "place_order" not in block
    assert "execute_" not in block

def test_build487_active_trades_history_is_persisted_by_server_scheduler_not_browser_only():
    source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    start = source.index("def _run_aster_strategy2_tick(")
    sampler = source.index("# The Portfolio Koers is server-persistent", start)
    hedge_guard = source.index("if not hedge:", sampler)
    block = source[sampler:hedge_guard]
    assert 'if not dry_run and not str(event_symbol).strip()' in block
    assert 'active_basket=active_trades_snapshot({"positions":positions})' in block
    assert "_persist_active_trades_chart_sample(" in block
    assert "source_at_ms=source_at_ms" in block
    assert "AsterV3Client(" not in block

