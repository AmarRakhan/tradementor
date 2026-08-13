from market_selector import select_candidates


def rows(count: int):
    return [
        {"symbol": f"C{rank}", "cmc_rank": rank, "quote": {"USD": {"percent_change_24h": rank / 10}}}
        for rank in range(1, count + 1)
    ]


def test_configurable_top_n_is_respected_without_hardcoded_fifty():
    source = rows(100)
    supported = [f"C{rank}USDT" for rank in range(1, 101)]
    result = select_candidates(source, requested_universe_size=100, exchange_symbols=supported)
    assert result.ready is True
    assert result.received_rank_count == 100
    assert len(result.candidates) == 100
    assert result.candidates[0].symbol == "C100"


def test_absolute_movement_places_large_drop_ahead_of_smaller_gain():
    source = [
        {"symbol": "GAIN", "cmc_rank": 1, "percent_change_24h": 8},
        {"symbol": "DROP", "cmc_rank": 2, "percent_change_24h": -12},
    ]
    result = select_candidates(
        source, requested_universe_size=2, exchange_symbols=["GAINUSDT", "DROPUSDT"],
    )
    assert [item.symbol for item in result.candidates] == ["DROP", "GAIN"]


def test_only_actively_supported_exchange_contracts_survive():
    source = [
        {"symbol": "AAA", "cmc_rank": 1, "percent_change_24h": 10},
        {"symbol": "BBB", "cmc_rank": 2, "percent_change_24h": 9},
    ]
    result = select_candidates(source, requested_universe_size=2, exchange_symbols=["AAA_USDT"])
    assert [item.exchange_symbol for item in result.candidates] == ["AAAUSDT"]


def test_incomplete_cmc_universe_fails_closed_instead_of_using_partial_list():
    result = select_candidates(rows(50), requested_universe_size=100, exchange_symbols=["C1USDT"])
    assert result.ready is False
    assert result.candidates == ()


def test_excluded_asset_cannot_become_candidate():
    source = [
        {"symbol": "BTC", "cmc_rank": 1, "percent_change_24h": 20},
        {"symbol": "ETH", "cmc_rank": 2, "percent_change_24h": 5},
    ]
    result = select_candidates(
        source, requested_universe_size=2, exchange_symbols=["BTCUSDT", "ETHUSDT"],
        excluded_base_assets=["BTC"],
    )
    assert [item.symbol for item in result.candidates] == ["ETH"]

