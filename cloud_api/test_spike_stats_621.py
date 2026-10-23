"""Build 621: Spike-statistiek per niveau (20,2 … 20,7+), alle munten vs. verhandelbaar."""
import unittest

import aster_spike_stats as st
from aster_spike_realtime import SpikeTrigger, watch_from_control
from aster_extreme_spike_filter import _store_reference, clear_reference_cache

# 20 closes: gemiddelde 100, populatie-sd 1 (afwisselend 99 en 101)
CLOSES = [99.0, 101.0] * 10
LIVE_CLOSE = 1_792_740_059_999
NOW = LIVE_CLOSE - 30_000


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def flushed(stats, now_ms):
    out = []
    stats._persist = lambda uid, hour, payload: out.append((uid, hour, payload))
    stats.maybe_flush(now_ms, force=True)
    return out


class SpikeStatsTests(unittest.TestCase):
    def test_reference_stats(self):
        self.assertEqual(st.reference_stats(CLOSES), (100.0, 1.0))
        self.assertIsNone(st.reference_stats([100.0] * 20))  # geen volatiliteit
        self.assertIsNone(st.reference_stats(CLOSES[:19]))

    def test_deepest_point_of_candle_counts_cumulatively(self):
        stats = st.SpikeStats()
        for price in (99.0, 95.5, 97.0):  # diepste punt 4,5 sigma onder het gemiddelde
            stats.observe(uid="u", symbol="AUSDT", timeframe="1m", closes=CLOSES, live_close_ms=LIVE_CLOSE,
                          price=price, tradable_long=True, tradable_short=True)
        stats.observe(uid="u", symbol="BUSDT", timeframe="1m", closes=CLOSES, live_close_ms=LIVE_CLOSE,
                      price=102.5, tradable_long=False, tradable_short=False)  # 2,5 sigma boven
        self.assertEqual(flushed(stats, NOW), [])  # candle loopt nog: niets
        (uid, hour, payload), = flushed(stats, LIVE_CLOSE)
        data = payload["1m"]
        self.assertEqual(data["candles"], 2)
        self.assertEqual(data["counts"]["LONG"]["all"], {"2": 1, "3": 1, "4": 1, "5": 0, "6": 0, "7": 0})
        self.assertEqual(data["counts"]["LONG"]["tradable"], {"2": 1, "3": 1, "4": 1, "5": 0, "6": 0, "7": 0})
        self.assertEqual(data["counts"]["SHORT"]["all"]["2"], 1)
        self.assertEqual(data["counts"]["SHORT"]["tradable"]["2"], 0)
        self.assertEqual([(e["symbol"], e["side"], e["sigma"]) for e in data["examples"]], [("AUSDT", "LONG", 4.5)])
        self.assertEqual(hour, st.hour_key(LIVE_CLOSE))

    def test_seven_means_seven_and_higher(self):
        stats = st.SpikeStats()
        stats.observe(uid="u", symbol="AUSDT", timeframe="1m", closes=CLOSES, live_close_ms=LIVE_CLOSE,
                      price=88.0, tradable_long=True, tradable_short=True)  # 12 sigma
        (_, _, payload), = flushed(stats, LIVE_CLOSE)
        self.assertEqual(payload["1m"]["counts"]["LONG"]["all"]["7"], 1)

    def test_flush_at_most_once_per_minute(self):
        clock = Clock()
        calls = []
        stats = st.SpikeStats(persist=lambda *a: calls.append(a), clock=clock)
        stats.observe(uid="u", symbol="AUSDT", timeframe="1m", closes=CLOSES, live_close_ms=LIVE_CLOSE,
                      price=96.0, tradable_long=True, tradable_short=True)
        self.assertEqual(stats.maybe_flush(LIVE_CLOSE), 0)
        clock.t = 61.0
        self.assertEqual(stats.maybe_flush(LIVE_CLOSE), 1)
        self.assertEqual(len(calls), 1)

    def test_persist_failure_is_harmless(self):
        def boom(*_):
            raise RuntimeError("firestore down")
        stats = st.SpikeStats(persist=boom)
        stats.observe(uid="u", symbol="AUSDT", timeframe="1m", closes=CLOSES, live_close_ms=LIVE_CLOSE,
                      price=96.0, tradable_long=True, tradable_short=True)
        self.assertEqual(stats.maybe_flush(LIVE_CLOSE, force=True), 0)

    def test_firestore_persister_builds_increments(self):
        writes = []

        class Doc:
            def __init__(self, path):
                self.path = path

            def collection(self, name):
                return Col(self.path + "/" + name)

            def set(self, data, merge=False):
                writes.append((self.path, data, merge))

        class Col:
            def __init__(self, path):
                self.path = path

            def document(self, name):
                return Doc(self.path + "/" + name)

        class Db:
            def collection(self, name):
                return Col(name)

        persist = st.firestore_persister(Db(), lambda n: ("inc", n), lambda xs: ("union", xs))
        persist("u1", "2026102309", {"1m": {"candles": 5, "counts": {"LONG": {"all": {"2": 3, "3": 0}, "tradable": {"2": 1}}},
                                             "examples": []}})
        (path, data, merge), = writes
        self.assertTrue(path.startswith("asterStrategy2/u1/spikeStats/2026102309_"))
        self.assertTrue(merge)
        self.assertEqual(data["timeframes"]["1m"]["candles"], ("inc", 5))
        self.assertEqual(data["timeframes"]["1m"]["counts"]["LONG"]["all"], {"2": ("inc", 3)})
        self.assertNotIn("examples", data["timeframes"]["1m"])


class TriggerIntegrationTests(unittest.TestCase):
    def setUp(self):
        clear_reference_cache()
        _store_reference("BTCUSDT", "1m", CLOSES, LIVE_CLOSE)

    def tearDown(self):
        clear_reference_cache()

    def control(self, **watch):
        base = {"symbols": ["BTCUSDT"], "level": "5", "longTimeframe": "1m", "shortTimeframe": "15m",
                "longEnabled": True, "shortEnabled": False, "updatedAtMs": NOW,
                "tradableSymbols": ["BTCUSDT"], "openLong": [], "openShort": ["BTCUSDT"]}
        base.update(watch)
        return {"enabled": True, "multiBbReport": {"spikeWatch": base}}

    def test_trigger_feeds_stats_without_changing_crossings(self):
        stats = st.SpikeStats()
        trigger = SpikeTrigger(stats=stats)
        trigger.replace_watches([watch_from_control("u1", self.control(), now_ms=NOW)])
        # 3 sigma onder: onder niveau 5 → geen crossing, wel statistiek
        self.assertEqual(trigger.crossings("u1", "BTCUSDT", 97.0, NOW), [])
        (_, _, payload), = flushed(stats, LIVE_CLOSE)
        counts = payload["1m"]["counts"]
        self.assertEqual(counts["LONG"]["tradable"]["3"], 1)
        self.assertEqual(counts["LONG"]["tradable"]["4"], 0)
        self.assertEqual(counts["SHORT"]["tradable"]["2"], 0)  # open SHORT = niet verhandelbaar

    def test_unknown_tradable_list_counts_only_all(self):
        stats = st.SpikeStats()
        trigger = SpikeTrigger(stats=stats)
        trigger.replace_watches([watch_from_control("u1", self.control(tradableSymbols=[]), now_ms=NOW)])
        trigger.crossings("u1", "BTCUSDT", 94.0, NOW)
        (_, _, payload), = flushed(stats, LIVE_CLOSE)
        self.assertEqual(payload["1m"]["counts"]["LONG"]["all"]["6"], 1)
        self.assertEqual(payload["1m"]["counts"]["LONG"]["tradable"]["2"], 0)

    def test_stats_failure_never_blocks_crossing(self):
        class Broken:
            def observe(self, **_):
                raise RuntimeError("boom")

            def maybe_flush(self, *_):
                raise RuntimeError("boom")
        trigger = SpikeTrigger(stats=Broken())
        trigger.replace_watches([watch_from_control("u1", self.control(), now_ms=NOW)])
        self.assertEqual(trigger.crossings("u1", "BTCUSDT", 94.0, NOW), [("LONG", LIVE_CLOSE)])


if __name__ == "__main__":
    unittest.main()


class ExcursionTests(unittest.TestCase):
    """Build 622: doorschiet-meting na een spike."""

    def feed(self, stats, prices, start_ms=NOW, step_ms=1000, tradable=True):
        for i, price in enumerate(prices):
            stats.observe(uid="u", symbol="AUSDT", timeframe="1m", closes=CLOSES, live_close_ms=LIVE_CLOSE,
                          price=price, tradable_long=tradable, tradable_short=tradable, now_ms=start_ms + i * step_ms)

    def test_drawdown_before_tp_is_measured_from_trigger_price(self):
        stats = st.SpikeStats()
        # 4 sigma onder (96), zakt door naar 95,52 (-0,5 %), stijgt naar 97,92 (+2 %)
        self.feed(stats, [96.0, 95.52, 96.48, 96.96, 97.92])
        (_, _, payload), = flushed(stats, LIVE_CLOSE)
        level4 = payload["1m"]["excursions"]["LONG"]["4"]
        self.assertEqual(level4["count"], 1)
        self.assertEqual(level4["tp"]["0.5"]["reached"], 1)
        self.assertEqual(level4["tp"]["0.5"]["drawdownBefore"], {"0.5": 1})
        self.assertEqual(level4["tp"]["2"]["drawdownBefore"], {"0.5": 1})
        ex = [e for e in payload["1m"]["excursionExamples"] if e["level"] == 4][0]
        self.assertAlmostEqual(ex["maxDrawdownPct"], 0.5, places=3)
        self.assertAlmostEqual(ex["drawdownBeforeTpPct"]["1"], 0.5, places=3)

    def test_level_trackers_have_their_own_entry(self):
        stats = st.SpikeStats()
        # 2 sigma bij 98, verder naar 96 (4 sigma), terug naar 98,98 (+1 % vanaf 2σ-instap)
        self.feed(stats, [98.0, 96.0, 98.98])
        stats.maybe_flush(LIVE_CLOSE)  # niets: nog niet afgerond (geen +2 %)
        (_, _, payload), = flushed(stats, NOW + EXCURSION_DONE)
        long = payload["1m"]["excursions"]["LONG"]
        # 2σ-instap 98: daalde 2,04 % vóór +1 %
        self.assertEqual(long["2"]["tp"]["1"]["drawdownBefore"], {"3": 1})
        # 4σ-instap 96: +3,1 % zonder daling → alle TP's gehaald met 0 daling
        self.assertEqual(long["4"]["tp"]["2"]["drawdownBefore"], {"0.1": 1})

    def test_unreached_tp_finishes_on_horizon_with_max_drawdown(self):
        stats = st.SpikeStats()
        self.feed(stats, [96.0, 94.08])  # -2 % en nooit herstel
        self.assertEqual(flushed(stats, NOW + 10_000), [])  # nog lopend: niets weggeschreven
        (_, _, payload), = flushed(stats, NOW + st.EXCURSION_HORIZON_MS + 1)
        row = payload["1m"]["excursions"]["LONG"]["4"]
        self.assertEqual(row["count"], 1)
        self.assertEqual(row["tp"]["0.5"]["reached"], 0)
        self.assertEqual(row["maxDrawdown"], {"2": 1})

    def test_bucket_labels(self):
        self.assertEqual(st.drawdown_bucket(0.0), "0.1")
        self.assertEqual(st.drawdown_bucket(0.27), "0.3")
        self.assertEqual(st.drawdown_bucket(0.25), "0.3")
        self.assertEqual(st.drawdown_bucket(9.0), "gt5")

    def test_persister_drops_zero_counters(self):
        out = st._increments({"a": {"b": 0, "c": 2}, "d": {"e": 0}}, lambda n: ("inc", n))
        self.assertEqual(out, {"a": {"c": ("inc", 2)}})


EXCURSION_DONE = st.EXCURSION_HORIZON_MS + 1
