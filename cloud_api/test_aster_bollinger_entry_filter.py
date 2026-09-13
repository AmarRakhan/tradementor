from __future__ import annotations

import time
import pytest

from aster_bollinger_entry_filter import BollingerEntryRejected, require_bollinger_entry
from aster_multi_bb_core import MultiBbConfig


class FakeMarket:
    def __init__(self, closes, price, *, open_ms=None):
        self.closes = list(closes)
        self.price = float(price)
        self.open_ms = int(open_ms if open_ms is not None else time.time() * 1000 // 900_000 * 900_000)
        self.kline_calls = 0
        self.ticker_calls = 0

    def klines(self, *, symbol, interval, limit):
        assert interval == "15m" and limit == 25
        self.kline_calls += 1
        start = self.open_ms - (len(self.closes) - 1) * 900_000
        return [[start + i * 900_000, "0", "0", "0", str(close), "0"] for i, close in enumerate(self.closes)]

    def ticker_price(self, *, symbol):
        self.ticker_calls += 1
        return {"symbol": symbol, "price": str(self.price)}


def bands(closes):
    mean = sum(closes[-20:]) / 20
    sigma = (sum((x - mean) ** 2 for x in closes[-20:]) / 20) ** .5
    return mean - 2 * sigma, mean + 2 * sigma


def test_config_defaults_off_and_roundtrips_true():
    off = MultiBbConfig.from_mapping({})
    assert off.bollinger_entry_filter_15m_enabled is False
    assert off.public_dict()["bollingerEntryFilter15mEnabled"] is False
    on = MultiBbConfig.from_mapping({"bollingerEntryFilter15mEnabled": True})
    assert on.bollinger_entry_filter_15m_enabled is True
    assert on.public_dict()["bollingerEntryFilter15mEnabled"] is True


def test_disabled_is_true_noop_and_makes_no_market_calls():
    market = FakeMarket(range(81, 101), 80)
    assert require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=False) is None
    assert market.kline_calls == 0 and market.ticker_calls == 0


def test_long_is_strictly_below_lower_band_only():
    closes = list(range(81, 101)); lower, _ = bands(closes); market = FakeMarket(closes, lower - .001)
    assert require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=True, live_price=lower - .001, force_refresh=True)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=True, live_price=lower, force_refresh=True)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=True, live_price=lower + .001, force_refresh=True)


def test_short_is_strictly_above_upper_band_only():
    closes = list(range(81, 101)); _, upper = bands(closes); market = FakeMarket(closes, upper + .001)
    assert require_bollinger_entry(market, symbol="ETHUSDT", side="SHORT", enabled=True, live_price=upper + .001, force_refresh=True)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="ETHUSDT", side="SHORT", enabled=True, live_price=upper, force_refresh=True)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="ETHUSDT", side="SHORT", enabled=True, live_price=upper - .001, force_refresh=True)


def test_intrabar_price_can_change_from_reject_to_pass_without_candle_close():
    closes = list(range(81, 101)); lower, upper = bands(closes); market = FakeMarket(closes, (lower + upper) / 2)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="SOLUSDT", side="LONG", enabled=True, live_price=(lower + upper) / 2, force_refresh=True)
    assert require_bollinger_entry(market, symbol="SOLUSDT", side="LONG", enabled=True, live_price=lower - .01, force_refresh=True)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="SOLUSDT", side="SHORT", enabled=True, live_price=(lower + upper) / 2, force_refresh=True)
    assert require_bollinger_entry(market, symbol="SOLUSDT", side="SHORT", enabled=True, live_price=upper + .01, force_refresh=True)


def test_preorder_forces_fresh_live_price_and_rejects_stale_pass():
    closes = list(range(81, 101)); lower, upper = bands(closes); market = FakeMarket(closes, lower - 1)
    assert require_bollinger_entry(market, symbol="XRPUSDT", side="LONG", enabled=True, force_refresh=True, stage="candidate")
    market.price = (lower + upper) / 2
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="XRPUSDT", side="LONG", enabled=True, force_refresh=True, stage="pre_order")
    assert market.ticker_calls == 2


def test_stale_15m_data_fails_closed():
    old = int(time.time() * 1000) - 25 * 60 * 1000
    market = FakeMarket(range(81, 101), 70, open_ms=old)
    with pytest.raises(BollingerEntryRejected) as exc: require_bollinger_entry(market, symbol="DOGEUSDT", side="LONG", enabled=True, force_refresh=True)
    assert exc.value.reason_code == "BB_DATA_UNAVAILABLE_OR_STALE"
