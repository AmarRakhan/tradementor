from datetime import datetime, timedelta, timezone

import pytest

from aster_strategy import AsterStrategySettings
from aster_strategy2 import Strategy2Config
from aster_strategy3 import Strategy3Config
from aster_universe import build_snapshot, normalize_top_n, stale_snapshot, MIN_QUOTE_VOLUME_24H_USDT


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


def ticker(symbol: str, volume: float, *, count: int = 100, bid: float = 99.9, ask: float = 100.1):
    return {"symbol": symbol, "lastPrice": "100", "quoteVolume": str(volume * 1_000_000),
            "count": count, "bidPrice": str(bid), "askPrice": str(ask),
            "priceChangePercent": "2", "highPrice": "110", "lowPrice": "90"}


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


def test_ranking_uses_quote_volume_then_symbol_deterministically():
    symbols = ["VOLUMEUSDT", "COUNTUSDT", "TIGHTBUSDT", "TIGHTAUSDT"]
    rows = [contract(symbol) for symbol in symbols]
    tickers = [
        ticker("VOLUMEUSDT", 2_000, count=1),
        ticker("COUNTUSDT", 1_000, count=500),
        ticker("TIGHTBUSDT", 1_000, count=100),
        ticker("TIGHTAUSDT", 1_000, count=100),
    ]
    snapshot = build_snapshot({"symbols": rows}, tickers, 4, fetched_at=NOW)
    assert [item.symbol for item in snapshot.eligible_markets] == [
        "VOLUMEUSDT", "COUNTUSDT", "TIGHTAUSDT", "TIGHTBUSDT",
    ]


def test_real_aster_24h_schema_without_bid_or_ask_remains_eligible():
    row = ticker("BTCUSDT", 1_000_000)
    row.pop("bidPrice")
    row.pop("askPrice")
    snapshot = build_snapshot({"symbols": [contract("BTCUSDT")]}, [row], 1, fetched_at=NOW)
    assert [item.symbol for item in snapshot.eligible_markets] == ["BTCUSDT"]
    assert snapshot.eligible_markets[0].spread_ratio is None
    assert snapshot.entry_blocked is False


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


def test_top_50_contains_exactly_fifty_when_at_least_fifty_are_eligible():
    rows = [contract(f"M{rank:03d}USDT") for rank in range(1, 76)]
    tickers = [ticker(f"M{rank:03d}USDT", 10_000 - rank) for rank in range(1, 76)]
    value = build_snapshot({"symbols": rows}, tickers, 50, fetched_at=NOW).public_dict()
    assert value["requestedTopN"] == 50
    assert value["eligibleMarketCount"] == 75
    assert value["selectedMarketCount"] == 50
    assert value["selectedSymbols"] == [f"M{rank:03d}USDT" for rank in range(1, 51)]


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


def raw_ticker(symbol: str, *, volume=2_000_000, change=2, high=110, low=90,
               bid=99.9, ask=100.1):
    return {"symbol": symbol, "lastPrice": "100", "quoteVolume": str(volume),
            "priceChangePercent": str(change), "highPrice": str(high), "lowPrice": str(low),
            "bidPrice": str(bid), "askPrice": str(ask), "count": 100}


def test_safety_filters_are_before_top_n_and_one_bad_symbol_is_isolated():
    symbols = ["GOODAUSDT", "GOODBUSDT", "LOWUSDT", "WIDEUSDT", "WILDUSDT", "RANGEUSDT", "NOVOLUMEUSDT"]
    rows = [contract(symbol) for symbol in symbols]
    tickers = [
        raw_ticker("GOODAUSDT", volume=3_000_000), raw_ticker("GOODBUSDT", volume=2_000_000),
        raw_ticker("LOWUSDT", volume=MIN_QUOTE_VOLUME_24H_USDT - 1),
        raw_ticker("WIDEUSDT", bid=99, ask=101), raw_ticker("WILDUSDT", change=51),
        raw_ticker("RANGEUSDT", high=210, low=100),
        {**raw_ticker("NOVOLUMEUSDT"), "quoteVolume": "NaN"},
    ]
    value = build_snapshot({"symbols": rows}, tickers, 200, fetched_at=NOW).public_dict()
    assert value["selectedSymbols"] == ["GOODAUSDT", "GOODBUSDT"]
    assert value["entryBlocked"] is False
    assert sum(value["rejectionCounts"].values()) == 5


def test_account_base_order_filter_rejects_unexecutable_precision_before_top_n():
    expensive = contract("EXPENSIVEUSDT")
    for item in expensive["filters"]:
        if item["filterType"] in {"LOT_SIZE", "MARKET_LOT_SIZE"}:
            item.update({"minQty": "1", "stepSize": "1"})
        if item["filterType"] == "MIN_NOTIONAL":
            item["notional"] = "100"
    value = build_snapshot({"symbols": [expensive, contract("GOODUSDT")]},
        [raw_ticker("EXPENSIVEUSDT", volume=9_000_000), raw_ticker("GOODUSDT", volume=2_000_000)],
        1, fetched_at=NOW, base_notional=25).public_dict()
    assert value["selectedSymbols"] == ["GOODUSDT"]
    assert value["rejectionSamples"]["EXPENSIVEUSDT"] == "basisorder voldoet niet aan Aster minimum/precision"


def test_531_mixed_markets_filter_then_select_top_200_deterministically():
    rows, tickers = [], []
    for rank in range(531):
        symbol = f"X{rank:03d}USDT"
        rows.append(contract(symbol, status="BREAK" if rank % 11 == 0 else "TRADING"))
        tickers.append(raw_ticker(symbol, volume=10_000_000 - rank * 10_000,
            change=60 if rank % 13 == 0 else 2))
    snapshot = build_snapshot({"symbols": rows}, reversed(tickers), 200, fetched_at=NOW)
    assert len(snapshot.selected) == 200
    assert list(snapshot.selected) == sorted(snapshot.selected,
        key=lambda item: (-item.quote_volume_24h, item.symbol))
    assert all(item.quote_volume_24h >= MIN_QUOTE_VOLUME_24H_USDT for item in snapshot.selected)


def test_unavailable_listing_short_term_and_bulk_spread_filters_are_reported_not_invented():
    row = raw_ticker("BTCUSDT")
    row.pop("bidPrice"); row.pop("askPrice")
    value = build_snapshot({"symbols": [contract("BTCUSDT")]}, [row], 1, fetched_at=NOW).public_dict()
    assert value["selectedSymbols"] == ["BTCUSDT"]
    assert value["unavailableFilters"] == ["listingdatum", "kortetermijnvolatiliteit", "bulk bid/ask-spread"]


def test_universe_change_cannot_modify_long_short_targets_or_close_logic():
    runtime = open("aster_strategy2_runtime.py", encoding="utf-8").read()
    assert "def balanced_entry_targets" in runtime
    assert "universe" not in runtime.lower()
    assert "require_profitable_automatic_close" not in open("aster_universe.py", encoding="utf-8").read()
