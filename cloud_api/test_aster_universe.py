from datetime import datetime, timedelta, timezone

import pytest

from aster_strategy import AsterStrategySettings
from aster_strategy2 import Strategy2Config
from aster_strategy3 import Strategy3Config
from aster_universe import build_snapshot, normalize_top_n, stale_snapshot


NOW = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)


def contract(symbol: str, *, status: str = "TRADING", contract_type: str = "PERPETUAL",
             quote: str = "USDT", settlement: str = "USDT", valid_filters: bool = True):
    value = "0.01" if valid_filters else "0"
    return {
        "symbol": symbol,
        "status": status,
        "contractType": contract_type,
        "quoteAsset": quote,
        "marginAsset": settlement,
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": value},
            {"filterType": "LOT_SIZE", "stepSize": value},
            {"filterType": "MARKET_LOT_SIZE", "stepSize": value},
            {"filterType": "MIN_NOTIONAL", "notional": "5" if valid_filters else "0"},
        ],
    }


def ticker(symbol: str, volume: float, *, count: int = 100, bid: float = 99, ask: float = 101):
    return {"symbol": symbol, "lastPrice": "100", "quoteVolume": str(volume),
            "count": count, "bidPrice": str(bid), "askPrice": str(ask)}


def test_every_positive_integer_is_preserved_and_fractional_values_are_rejected():
    assert normalize_top_n(50) == 50
    assert normalize_top_n("150") == 150
    assert normalize_top_n(999) == 999
    for invalid in (0, -1, 150.5, "150.5", True):
        with pytest.raises(ValueError):
            normalize_top_n(invalid)


def test_all_three_strategy_configs_store_150_exactly_without_preset_rounding():
    assert AsterStrategySettings.from_mapping({"universeTopN": 150}).universe_top_n == 150
    assert Strategy2Config.from_mapping({"universeTopN": 150}).universe_top_n == 150
    assert Strategy3Config.from_mapping({"universeTopN": 150}).universe_top_n == 150
    assert Strategy2Config.from_mapping({"universeTopN": 150}).public_dict()["universeTopN"] == 150
    assert Strategy3Config.from_mapping({"universeTopN": 150}).public_dict()["universeTopN"] == 150


def test_server_serialization_reload_and_process_restart_keep_150():
    for config_type in (AsterStrategySettings, Strategy2Config, Strategy3Config):
        stored = config_type.from_mapping({"universeTopN": "150"}).public_dict()
        assert stored["universeTopN"] == 150
        reloaded = config_type.from_mapping(dict(stored))
        restarted = config_type.from_mapping(reloaded.public_dict())
        assert reloaded.universe_top_n == 150
        assert restarted.universe_top_n == 150


def test_only_active_valid_aster_usdt_perpetual_contracts_survive():
    rows = [
        contract("GOODUSDT"),
        contract("USDCUSDC", quote="USDC", settlement="USDC"),
        contract("PAUSEDUSDT", status="BREAK"),
        contract("DELIVERYUSDT", contract_type="CURRENT_QUARTER"),
        contract("BADSETTLEUSDT", settlement="USDC"),
        contract("BADFILTERUSDT", valid_filters=False),
    ]
    tickers = [ticker(str(row["symbol"]), 1_000_000) for row in rows]
    snapshot = build_snapshot({"symbols": rows}, tickers, 150, fetched_at=NOW)
    assert [item.symbol for item in snapshot.eligible_markets] == ["GOODUSDT"]


def test_ranking_uses_quote_volume_then_liquidity_then_symbol_deterministically():
    symbols = ["VOLUMEUSDT", "COUNTUSDT", "TIGHTBUSDT", "TIGHTAUSDT"]
    rows = [contract(symbol) for symbol in symbols]
    tickers = [
        ticker("VOLUMEUSDT", 2_000, count=1, bid=90, ask=110),
        ticker("COUNTUSDT", 1_000, count=500, bid=90, ask=110),
        ticker("TIGHTBUSDT", 1_000, count=100, bid=99.5, ask=100.5),
        ticker("TIGHTAUSDT", 1_000, count=100, bid=99.5, ask=100.5),
    ]
    snapshot = build_snapshot({"symbols": rows}, tickers, 4, fetched_at=NOW)
    assert [item.symbol for item in snapshot.eligible_markets] == [
        "VOLUMEUSDT", "COUNTUSDT", "TIGHTAUSDT", "TIGHTBUSDT",
    ]


def test_top_150_contains_exactly_first_150_of_two_hundred_eligible_markets():
    rows = [contract(f"C{rank:03d}USDT") for rank in range(1, 201)]
    tickers = [ticker(f"C{rank:03d}USDT", 10_000 - rank) for rank in range(1, 201)]
    contract_value = build_snapshot({"symbols": rows}, tickers, 150, fetched_at=NOW).public_dict()
    assert contract_value["requestedTopN"] == 150
    assert contract_value["eligibleMarketCount"] == 200
    assert contract_value["selectedMarketCount"] == 150
    assert contract_value["selectedSymbols"] == [f"C{rank:03d}USDT" for rank in range(1, 151)]
    assert contract_value["universeSource"] == "aster"
    assert contract_value["quoteAsset"] == "USDT"
    assert contract_value["marketType"] == "perpetual"
    assert contract_value["entryBlocked"] is False


def test_request_above_availability_is_reported_without_silent_reset():
    rows = [contract(f"C{rank:03d}USDT") for rank in range(1, 21)]
    tickers = [ticker(f"C{rank:03d}USDT", 10_000 - rank) for rank in range(1, 21)]
    value = build_snapshot({"symbols": rows}, tickers, 150, fetched_at=NOW).public_dict()
    assert (value["requestedTopN"], value["eligibleMarketCount"], value["selectedMarketCount"]) == (150, 20, 20)


def test_invalid_or_stale_data_blocks_entries_without_erasing_selected_evidence():
    fresh = build_snapshot({"symbols": [contract("BTCUSDT")]}, [ticker("BTCUSDT", 10_000)], 1,
                           fetched_at=NOW, ttl_seconds=60)
    stale = stale_snapshot(fresh, now=NOW + timedelta(seconds=61), reason="Aster data te oud")
    value = stale.public_dict()
    assert value["stale"] is True
    assert value["entryBlocked"] is True
    assert value["entryBlockReason"] == "Aster data te oud"
    assert value["selectedSymbols"] == ["BTCUSDT"]


def test_existing_position_management_does_not_depend_on_universe_membership():
    source = open("aster_strategy2_runtime.py", encoding="utf-8").read()
    strategy3 = open("aster_strategy3.py", encoding="utf-8").read()
    assert "universe" not in source.lower()
    assert "universe" not in strategy3[strategy3.index("def decide("):].lower()


def test_all_three_entry_paths_consume_only_server_selected_symbols():
    source = open("main.py", encoding="utf-8").read()
    assert source.count('universe_contract["selectedSymbols"]') >= 3
    assert "preferred=(\"BTCUSDT\"" not in source
