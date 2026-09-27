from __future__ import annotations

from aster_multi_bb import MultiBbConfig
from aster_portfolio_chart import zone_shadow_backtest


def base_settings(**overrides):
    raw = {
        "engine": "multi_bb_v1",
        "strategyKind": "multi_bb_v1",
        "universeTopN": 350,
        "maximumPositions": 100,
        "longSlots": 50,
        "shortSlots": 50,
        "minimumLeverage": 20,
        "maximumLeverage": 50,
        "entrySizingMode": "margin",
        "entryMarginLongUsd": 0.40,
        "entryMarginShortUsd": 0.30,
        "longDcaMarginUsd": 0.17,
        "shortDcaMarginUsd": 0.25,
        "longDcaDistance": 0.10,
        "shortDcaDistance": 0.25,
        "maxDcaLong": 10,
        "maxDcaShort": 15,
        "takeProfitMode": "PER_TRADE",
        "longTakeProfitValue": 0.015,
        "shortTakeProfitValue": 0.015,
        "bollingerEntryFilter15mEnabled": False,
        "directionalBollingerEnabled": False,
    }
    raw.update(overrides)
    return raw


def test_classic_dca_dry_run_keeps_independent_long_short_values_without_bollinger():
    cfg = MultiBbConfig.from_mapping(base_settings())
    assert cfg.zone_soldiers_enabled is False
    assert cfg.maximum_positions == 100
    assert (cfg.long_slots, cfg.short_slots) == (50, 50)
    assert cfg.bollinger_entry_filter_15m_enabled is False
    assert (cfg.entry_margin_long_usd, cfg.entry_margin_short_usd) == (0.40, 0.30)
    assert (cfg.long_dca_margin_usd, cfg.short_dca_margin_usd) == (0.17, 0.25)
    assert (cfg.long_dca_distance, cfg.short_dca_distance) == (0.10, 0.25)
    assert (cfg.max_dca_long, cfg.max_dca_short) == (10, 15)


def test_classic_dca_bollinger_is_optional_and_directional_when_enabled():
    cfg = MultiBbConfig.from_mapping(base_settings(
        bollingerEntryFilter15mEnabled=True,
        directionalBollingerEnabled=True,
        bollingerLongTimeframe="1m",
        bollingerShortTimeframe="15m",
    ))
    assert cfg.bollinger_entry_filter_15m_enabled is True
    assert cfg.directional_bollinger_enabled is True
    assert cfg.bollinger_long_timeframe == "1m"
    assert cfg.bollinger_short_timeframe == "15m"


def test_zone_warriors_keeps_global_capacity_and_per_zone_formation():
    cfg = MultiBbConfig.from_mapping(base_settings(
        maximumPositions=130,
        zoneSoldiersEnabled=True,
        zoneSoldiersOptInVersion=1,
        zoneBaseLongSoldiers=3,
        zoneBaseShortSoldiers=3,
    ))
    assert cfg.zone_soldiers_enabled is True
    assert cfg.zone_soldiers_opt_in_version == 1
    assert cfg.zone_base_long_soldiers == 3
    assert cfg.zone_base_short_soldiers == 3
    assert cfg.maximum_positions == 130
    saved = cfg.public_dict()
    assert saved["maximumPositions"] == 130
    assert saved["zoneBaseLongSoldiers"] == 3
    assert saved["zoneBaseShortSoldiers"] == 3


def test_tp_modes_round_trip_without_losing_directional_values():
    portfolio = MultiBbConfig.from_mapping(base_settings(
        takeProfitMode="PORTFOLIO",
        portfolioTpInputMode="USD",
        portfolioTpValue=15,
        portfolioTpBaseMode="CUSTOM",
        portfolioTpCustomBaseEquity=340.32,
    ))
    saved = portfolio.public_dict()
    assert saved["takeProfitMode"] == "PORTFOLIO"
    assert saved["portfolioTpInputMode"] == "USD"
    assert saved["portfolioTpValue"] == 15
    assert saved["portfolioTpBaseMode"] == "CUSTOM"
    assert saved["portfolioTpCustomBaseEquity"] == 340.32
    assert saved["longTakeProfitValue"] == 0.015
    assert saved["shortTakeProfitValue"] == 0.015

    off = MultiBbConfig.from_mapping(base_settings(takeProfitMode="OFF"))
    assert off.take_profit_mode == "OFF"
    assert off.long_take_profit_value == 0.015
    assert off.short_take_profit_value == 0.015


def test_zone_shadow_backtest_is_read_only_and_never_emits_orders():
    closes = [100, 104, 99, 105, 98, 106, 99, 107, 100, 108, 101, 107, 100, 106, 99, 105, 98, 104, 99, 105,
              100, 106, 101, 107, 102, 108, 103, 109, 104, 110, 103, 109, 102, 108, 101, 107, 100, 106, 99, 105]
    candles = []
    for index, close in enumerate(closes):
        candles.append({
            "timestamp": 1_700_000_000_000 + index * 60_000,
            "open": close - 0.4,
            "high": close + 1.2,
            "low": close - 1.2,
            "close": close,
        })
    report = zone_shadow_backtest(candles, cycle_start_equity=100.0)
    assert report["mode"] == "shadow"
    assert report["readOnly"] is True
    assert report["ordersSent"] == 0
    assert report["usesFutureCandles"] is False
    assert report["evaluatedCandles"] >= 0
    assert report["zoneTransitions"] >= 0
