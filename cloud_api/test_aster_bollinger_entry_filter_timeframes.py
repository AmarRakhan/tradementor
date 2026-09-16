from __future__ import annotations

import time
import pytest

import aster_bollinger_entry_filter as bb
from aster_bollinger_entry_filter import BollingerEntryRejected, require_bollinger_entry
from aster_multi_bb_core import MultiBbConfig


INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class TimeframeMarket:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def klines(self, *, symbol, interval, limit):
        assert interval in INTERVAL_MS
        assert limit == 25
        self.calls.append((symbol, interval))
        step = INTERVAL_MS[interval]
        now = int(time.time() * 1000)
        last_open = now // step * step
        start = last_open - 19 * step
        return [[start + i * step, "0", "0", "0", str(100 + i * 0.1), "0"] for i in range(20)]


class GuardedMarket(TimeframeMarket):
    def __init__(self):
        super().__init__()
        self.public_reads: list[str] = []

    def _public_get(self, path, *, ttl_seconds, invalid_message):
        assert ttl_seconds == 1
        self.public_reads.append(path)
        if "/klines?" in path:
            interval = path.split("interval=", 1)[1].split("&", 1)[0]
            symbol = path.split("symbol=", 1)[1].split("&", 1)[0]
            return self.klines(symbol=symbol, interval=interval, limit=25)
        if "/ticker/price?" in path:
            return {"price": "1"}
        raise AssertionError(path)


def test_config_backward_compatible_default_and_ui_aliases():
    cfg = MultiBbConfig.from_mapping({})
    assert cfg.bollinger_entry_filter_timeframe == "15m"
    assert cfg.public_dict()["bollingerEntryFilterTimeframe"] == "15m"
    assert MultiBbConfig.from_mapping({"bollingerEntryFilterTimeframe": "1u"}).bollinger_entry_filter_timeframe == "1h"
    assert MultiBbConfig.from_mapping({"bollingerEntryFilterTimeframe": "4u"}).bollinger_entry_filter_timeframe == "4h"
    with pytest.raises(ValueError):
        MultiBbConfig.from_mapping({"bollingerEntryFilterTimeframe": "30m"})


def test_filter_off_is_true_noop_even_with_invalid_timeframe():
    market = TimeframeMarket()
    assert require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=False, timeframe="invalid") is None
    assert market.calls == []


@pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "1h", "4h", "1d"])
def test_all_six_intervals_reach_datasource(timeframe):
    market = TimeframeMarket()
    symbol = f"T{timeframe.replace('m','M').replace('h','H').replace('d','D')}USDT"
    result = require_bollinger_entry(market, symbol=symbol, side="LONG", enabled=True, timeframe=timeframe,
                                     live_price=1, force_refresh=False)
    assert result is not None
    assert result.timeframe == timeframe
    assert market.calls == [(symbol, timeframe)]


def test_timeframe_change_cannot_reuse_old_band_cache():
    bb._BAND_CACHE.clear()
    market = TimeframeMarket()
    require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=True, timeframe="15m", live_price=1)
    require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=True, timeframe="1m", live_price=1)
    assert market.calls == [("BTCUSDT", "15m"), ("BTCUSDT", "1m")]
    assert ("BTCUSDT", "15m") in bb._BAND_CACHE
    assert ("BTCUSDT", "1m") in bb._BAND_CACHE


@pytest.mark.parametrize("timeframe", ["1m", "15m", "1h", "4h", "1d"])
def test_preorder_guarded_read_uses_selected_exchange_interval(timeframe):
    market = GuardedMarket()
    result = require_bollinger_entry(market, symbol="ETHUSDT", side="LONG", enabled=True, timeframe=timeframe,
                                     live_price=1, force_refresh=True, stage="pre_order")
    assert result is not None
    assert market.public_reads[0] == f"/fapi/v1/klines?interval={timeframe}&symbol=ETHUSDT&limit=25"


def test_missing_or_stale_selected_timeframe_fails_closed():
    class EmptyMarket:
        def klines(self, *, symbol, interval, limit):
            return []
    with pytest.raises(BollingerEntryRejected) as exc:
        require_bollinger_entry(EmptyMarket(), symbol="SOLUSDT", side="LONG", enabled=True, timeframe="4h", live_price=1)
    assert exc.value.reason_code == "BB_DATA_UNAVAILABLE_OR_STALE"
