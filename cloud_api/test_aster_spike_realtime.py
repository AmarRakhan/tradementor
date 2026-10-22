"""Spike 1.1 realtime-trigger: band in geheugen, account-tick alleen bij een geraakte band."""
import unittest
from types import SimpleNamespace

from aster_extreme_spike_filter import clear_reference_cache, _store_reference
from aster_spike_realtime import (
    MAX_SYMBOLS_PER_CONNECTION, SpikeTrigger, make_spike_evaluator, shard_mapping, watch_from_control,
)

NOW = 22 * 900000 + 10            # binnen de lopende 15m-candle
LIVE_CLOSE = 23 * 900000 - 1
CLOSES = [100.0 + (i % 2) * 2 for i in range(20)]   # gemiddelde 101, sigma 1


def control(**watch):
    base = {"symbols": ["BTCUSDT", "ETHUSDT"], "level": "5", "longTimeframe": "15m", "shortTimeframe": "15m",
            "longEnabled": True, "shortEnabled": False, "updatedAtMs": NOW - 1000}
    base.update(watch)
    return {"enabled": True, "multiBbReport": {"spikeWatch": base}}


class WatchParsing(unittest.TestCase):
    def test_reads_watch_from_existing_report(self):
        w = watch_from_control("u1", control(), now_ms=NOW)
        self.assertEqual(w.symbols, ("BTCUSDT", "ETHUSDT"))
        self.assertEqual(w.sides(), (("LONG", "15m"),))

    def test_stopped_bot_or_stale_report_is_ignored(self):
        self.assertIsNone(watch_from_control("u1", {**control(), "enabled": False}, now_ms=NOW))
        self.assertIsNone(watch_from_control("u1", control(updatedAtMs=NOW - 16 * 60000), now_ms=NOW))
        self.assertIsNone(watch_from_control("u1", {"enabled": True}, now_ms=NOW))

    def test_both_sides_off_means_no_watch(self):
        self.assertIsNone(watch_from_control("u1", control(longEnabled=False), now_ms=NOW))

    def test_shards_respect_200_per_connection(self):
        symbols = [f"C{i:03d}USDT" for i in range(350)]
        w = watch_from_control("u1", control(symbols=symbols), now_ms=NOW)
        shards = shard_mapping([w])
        self.assertEqual([len(s) for s in shards], [MAX_SYMBOLS_PER_CONNECTION, 150])


class Trigger(unittest.TestCase):
    def setUp(self):
        clear_reference_cache()
        _store_reference("BTCUSDT", "15m", CLOSES, LIVE_CLOSE)
        self.trigger = SpikeTrigger()
        self.trigger.replace_watches([watch_from_control("u1", control(shortEnabled=True), now_ms=NOW)])

    def test_long_band_at_five_sigma(self):
        self.assertEqual(self.trigger.crossings("u1", "BTCUSDT", 96.1, NOW), [])
        self.assertEqual(self.trigger.crossings("u1", "BTCUSDT", 96.0, NOW), [("LONG", LIVE_CLOSE)])
        # "vanaf": ook ver voorbij de band
        self.assertEqual(self.trigger.crossings("u1", "BTCUSDT", 80.0, NOW), [("LONG", LIVE_CLOSE)])

    def test_short_band(self):
        self.assertEqual(self.trigger.crossings("u1", "BTCUSDT", 106.0, NOW), [("SHORT", LIVE_CLOSE)])

    def test_once_per_candle_after_fired(self):
        self.trigger.mark_fired("u1", "BTCUSDT", "LONG", LIVE_CLOSE)
        self.assertEqual(self.trigger.crossings("u1", "BTCUSDT", 95.0, NOW), [])

    def test_no_reference_no_trigger(self):
        self.assertEqual(self.trigger.crossings("u1", "ETHUSDT", 1.0, NOW), [])

    def test_unknown_account(self):
        self.assertEqual(self.trigger.crossings("other", "BTCUSDT", 95.0, NOW), [])

    def test_warm_fills_missing_reference(self):
        def warm(symbol, timeframe, now_ms):
            _store_reference(symbol, timeframe, CLOSES, LIVE_CLOSE)
            return True
        trigger = SpikeTrigger(warm_reference=warm, warm_per_second=1000)
        trigger.replace_watches([watch_from_control("u1", control(), now_ms=NOW)])
        self.assertEqual(trigger.crossings("u1", "ETHUSDT", 95.0, NOW), [("LONG", LIVE_CLOSE)])


class Evaluator(unittest.TestCase):
    def setUp(self):
        clear_reference_cache()
        _store_reference("BTCUSDT", "15m", CLOSES, LIVE_CLOSE)
        self.trigger = SpikeTrigger()
        self.trigger.replace_watches([watch_from_control("u1", control(), now_ms=NOW)])
        self.calls = []

    def evaluator(self, status="running"):
        def tick(uid, symbol):
            self.calls.append((uid, symbol))
            return {"status": status, "ordersSent": 1 if status == "running" else 0}
        return make_spike_evaluator(self.trigger, tick, now_ms=lambda: NOW)

    def event(self, price):
        return SimpleNamespace(symbol="BTCUSDT", mark_price=price)

    def test_no_crossing_no_tick(self):
        self.assertIsNone(self.evaluator()("u1", self.event(100.0)))
        self.assertEqual(self.calls, [])

    def test_crossing_runs_tick_once_per_candle(self):
        evaluate = self.evaluator()
        out = evaluate("u1", self.event(95.0))
        self.assertTrue(out["spikeRealtime"])
        evaluate("u1", self.event(94.0))
        self.assertEqual(self.calls, [("u1", "BTCUSDT")])

    def test_busy_account_retries_next_event(self):
        evaluate = self.evaluator(status="account-busy")
        evaluate("u1", self.event(95.0))
        evaluate("u1", self.event(95.0))
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
