"""Kostenreductie 4.1: the display read cache returns exactly what a direct Firestore read returns, with far fewer reads.

Pure tests (no network, no Firestore SDK): a fake collection implements the query shapes main.py uses
(order_by desc, where >=, limit, stream) and counts every document read the way Firestore bills them
(one read per returned document, minimum one per query). Plus static wiring checks on main.py.
"""
from __future__ import annotations

import random
import threading
import unittest
from pathlib import Path

from chart_read_cache import TailRefreshCache, TtlValueCache

MIN = 60_000


class Doc:
    def __init__(self, doc_id, data):
        self.id, self._data = doc_id, data

    def to_dict(self):
        return dict(self._data)


class FakeCollection:
    """order_by(field, desc) / where(field, '>=', v) / limit(n) / stream(), with billed-read counting."""

    def __init__(self, field="bucketMs"):
        self.field, self.docs, self.reads, self.queries = field, {}, 0, 0

    def put(self, doc_id, data):
        self.docs[doc_id] = dict(data)

    def delete(self, doc_id):
        self.docs.pop(doc_id, None)

    def query(self, since=None, limit=None):
        rows = [Doc(i, d) for i, d in self.docs.items() if self.field in d and (since is None or d[self.field] >= since)]
        rows.sort(key=lambda doc: doc._data[self.field], reverse=True)
        rows = rows if limit is None else rows[:limit]
        self.queries += 1
        self.reads += max(1, len(rows))
        return rows


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def direct(col, limit):
    return [(d.id, d._data[col.field], d._data) for d in col.query(limit=limit)]


def cached(cache, col, limit, key="k"):
    return cache.get(key, limit=limit,
                     full=lambda window: [(d.id, d._data[col.field], d._data) for d in col.query(limit=window)],
                     tail=lambda since: [(d.id, d._data[col.field], d._data) for d in col.query(since=since)])


class CandleSeriesTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cache = TailRefreshCache(overlap=10 * MIN, clock=self.clock, reuse_seconds=2.0, full_refresh_seconds=900.0,
                                      enabled=lambda: True)
        self.col = FakeCollection()
        self.now_ms = 1_800_000_000_000
        for i in range(700):                                   # 700 one-minute buckets of history
            b = self.now_ms - (700 - i) * MIN
            self.col.put(str(b), {"bucketMs": b, "close": float(i)})

    def write_sample(self, age_ms=0, value=1.0):
        """What _persist_*_chart_sample does: merge into the bucket of a sample at most ~2 minutes old."""
        b = (self.now_ms - age_ms) // MIN * MIN
        doc = self.col.docs.get(str(b), {"bucketMs": b, "close": 0.0})
        self.col.put(str(b), {**doc, "close": value, "high": max(doc.get("high", value), value)})

    def assert_same(self, limit):
        expected = direct(self.col, limit)
        reads_before = self.col.reads
        got = cached(self.cache, self.col, limit)
        cost = self.col.reads - reads_before - (len(expected) if limit is None else max(1, min(limit, len(self.col.docs))))
        self.assertEqual(got, expected)
        return cost

    def test_first_read_equals_direct_read(self):
        self.assertEqual(cached(self.cache, self.col, 320), direct(self.col, 320))

    def test_identical_after_many_writes_and_new_buckets(self):
        rng = random.Random(7)
        cached(self.cache, self.col, 320)
        for step in range(400):                                # 400 polls, 5 s apart, with live writes in between
            self.clock.t += 5
            self.now_ms += 5_000
            self.write_sample(age_ms=rng.choice([0, 0, 30_000, 119_000]), value=rng.random())
            self.assertEqual(cached(self.cache, self.col, 320), direct(self.col, 320), step)

    def test_reads_drop_by_more_than_ninety_percent(self):
        col_direct = FakeCollection()
        col_direct.docs = self.col.docs                         # same data, separate read meter
        cached(self.cache, self.col, 320)
        self.col.reads = 0
        for _ in range(720):                                    # one hour of 5-second polling
            self.clock.t += 5
            self.now_ms += 5_000
            self.write_sample(value=1.0)
            cached(self.cache, self.col, 320)
            direct(col_direct, 320)
        self.assertLess(self.col.reads, col_direct.reads * 0.10, (self.col.reads, col_direct.reads))

    def test_320_and_600_callers_share_one_window(self):
        cached(self.cache, self.col, 320)
        self.clock.t += 5
        self.assertEqual(cached(self.cache, self.col, 600), direct(self.col, 600))   # widened once
        self.clock.t += 5
        full_reads = self.cache.stats["full"]
        self.assertEqual(cached(self.cache, self.col, 320), direct(self.col, 320))
        self.assertEqual(self.cache.stats["full"], full_reads)   # served from the widened window, no new full read

    def test_unbounded_series_limit_none(self):
        self.assertEqual(cached(self.cache, self.col, None), direct(self.col, None))
        self.clock.t += 5
        self.now_ms += MIN
        self.write_sample()
        self.assertEqual(cached(self.cache, self.col, None), direct(self.col, None))

    def test_requests_within_two_seconds_share_one_read(self):
        cached(self.cache, self.col, 320)
        reads = self.col.reads
        self.clock.t += 1
        cached(self.cache, self.col, 320)
        self.assertEqual(self.col.reads, reads)

    def test_full_refresh_catches_an_out_of_window_change(self):
        cached(self.cache, self.col, 320)
        old = self.now_ms - 300 * MIN
        self.col.put(str(old), {"bucketMs": old, "close": -1.0})   # a change no current writer makes
        self.clock.t += 901
        self.assertEqual(cached(self.cache, self.col, 320), direct(self.col, 320))

    def test_tail_error_falls_back_to_the_full_read(self):
        cached(self.cache, self.col, 320)
        self.clock.t += 5
        got = self.cache.get("k", limit=320, full=lambda w: [(d.id, d._data["bucketMs"], d._data) for d in self.col.query(limit=w)],
                             tail=lambda since: (_ for _ in ()).throw(RuntimeError("deadline")))
        self.assertEqual(got, direct(self.col, 320))
        self.assertEqual(self.cache.stats["fallback"], 1)

    def test_full_read_error_propagates_like_the_direct_read(self):
        with self.assertRaises(RuntimeError):
            self.cache.get("x", limit=5, full=lambda w: (_ for _ in ()).throw(RuntimeError("down")), tail=lambda s: [])

    def test_disabled_flag_is_the_direct_read(self):
        off = TailRefreshCache(overlap=10 * MIN, clock=self.clock, enabled=lambda: False)
        cached(off, self.col, 320)
        reads = self.col.reads
        cached(off, self.col, 320)
        self.assertEqual(self.col.reads - reads, 320)

    def test_accounts_and_series_are_isolated(self):
        other = FakeCollection()
        other.put("1", {"bucketMs": 1, "close": 9.0})
        self.assertEqual(cached(self.cache, self.col, 5, key=("u1", "c")), direct(self.col, 5))
        self.assertEqual(cached(self.cache, other, 5, key=("u2", "c")), direct(other, 5))

    def test_concurrent_requests_do_not_duplicate_the_read(self):
        reads = []
        gate = threading.Event()

        def slow_full(window):
            gate.wait(1)
            reads.append(window)
            return [(d.id, d._data["bucketMs"], d._data) for d in self.col.query(limit=window)]
        threads = [threading.Thread(target=self.cache.get, args=("z",),
                                    kwargs={"limit": 320, "full": slow_full, "tail": lambda s: []}) for _ in range(6)]
        [t.start() for t in threads]
        gate.set()
        [t.join() for t in threads]
        self.assertEqual(len(reads), 1)


class AuditWindowTests(unittest.TestCase):
    """The events feed: newest 1,200 audit rows of the last 36 h, every 5 seconds."""

    def setUp(self):
        self.clock = Clock()
        self.cache = TailRefreshCache(overlap=3 * MIN, clock=self.clock, enabled=lambda: True)
        self.col = FakeCollection(field="ts")
        self.now_ms = 1_800_000_000_000
        self.n = 0
        for i in range(2000):                                   # one audit row per minute for 33 hours
            self.add(self.now_ms - (2000 - i) * MIN)

    def add(self, ts):
        self.n += 1
        self.col.put(f"a{self.n}", {"ts": ts, "n": self.n})

    def direct(self):
        cutoff = self.now_ms - 36 * 60 * MIN
        return [(d.id, d._data["ts"], d._data) for d in self.col.query(since=cutoff, limit=1200)]

    def cached(self):
        cutoff = self.now_ms - 36 * 60 * MIN
        return self.cache.get("audit", limit=1200,
                              full=lambda w: [(d.id, d._data["ts"], d._data) for d in self.col.query(since=cutoff, limit=w)],
                              tail=lambda since: [(d.id, d._data["ts"], d._data) for d in self.col.query(since=max(since, cutoff), limit=1200)],
                              keep=lambda row: row[1] >= cutoff)

    def test_same_rows_while_ticks_append_and_the_window_slides(self):
        self.assertEqual(self.cached(), self.direct())
        for step in range(300):
            self.clock.t += 5
            self.now_ms += 5_000
            if step % 12 == 0:
                self.add(self.now_ms - 2_000)                   # tick writes with its own (current) timestamp
            self.assertEqual(self.cached(), self.direct(), step)

    def test_rows_older_than_36_hours_leave_the_feed_exactly_as_with_a_direct_read(self):
        self.col.docs.clear()
        for i in range(30):                                     # 30 rows around the 36-hour edge, far below 1,200
            self.add(self.now_ms - 36 * 60 * MIN + (i - 10) * MIN)
        self.assertEqual(self.cached(), self.direct())
        for _ in range(30):
            self.clock.t += 20
            self.now_ms += 20_000
            self.assertEqual(self.cached(), self.direct())

    def test_reads_per_poll_drop_from_1200_to_a_few(self):
        self.cached()
        self.col.reads = 0
        for step in range(120):                                 # ten minutes of 5-second polling
            self.clock.t += 5
            self.now_ms += 5_000
            if step % 12 == 0:
                self.add(self.now_ms - 1_000)
            self.cached()
        self.assertLess(self.col.reads, 120 * 10, self.col.reads)   # direct: 120 x 1,200 = 144,000 reads


class TtlCacheTests(unittest.TestCase):
    def test_ttl_and_invalidation(self):
        clock, loads = Clock(), []
        cache = TtlValueCache(ttl_seconds=60, clock=clock, enabled=lambda: True)
        load = lambda: loads.append(1) or ["row"]
        cache.get("u", load)
        cache.get("u", load)
        self.assertEqual(len(loads), 1)
        cache.invalidate("u")
        cache.get("u", load)
        self.assertEqual(len(loads), 2)
        clock.t += 61
        cache.get("u", load)
        self.assertEqual(len(loads), 3)


class WiringTests(unittest.TestCase):
    SRC = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")

    def fn(self, name):
        start = self.SRC.index("\ndef " + name + "(")
        end = self.SRC.index("\ndef ", start + 5)
        return self.SRC[start:end]

    def route(self, path):
        start = self.SRC.index('@app.get("' + path + '")')
        return self.SRC[start:self.SRC.index("\n@app.", start + 5)]

    def test_trading_tick_keeps_the_direct_reader(self):
        tick = self.fn("_strategy2_zone_runtime_context")
        self.assertIn('_read_portfolio_chart_candles({"uid": uid}, "15m", 320)', tick)
        self.assertNotIn("_display(", tick)

    def test_order_engine_paths_never_use_the_display_cache(self):
        for name in ("close_one_aster_position", "_run_mexc_automation_tick", "dynamic_before_order"):
            if ("\ndef " + name + "(") in self.SRC:
                body = self.fn(name)
                for cached_name in ("_display(", "_chart_candle_cache", "_chart_audit_cache", "_stored_closes_cache"):
                    self.assertNotIn(cached_name, body, name)

    def test_presentation_routes_use_the_cached_readers(self):
        self.assertIn("_read_portfolio_chart_candles_display(user, timeframe, limit)", self.route("/v1/me/aster/portfolio-chart"))
        self.assertIn("_read_active_trades_chart_candles_display(user, timeframe, limit)", self.route("/v1/me/aster/portfolio-chart/active-trades"))
        self.assertIn("_portfolio_chart_recent_strategy_audit_rows_display(", self.route("/v1/me/aster/portfolio-chart/events"))
        self.assertIn("_stored_aster_closed_trades_display(user)", self.fn("aster_status"))

    def test_closed_trades_route_itself_stays_authoritative(self):
        self.assertIn("stored = _stored_aster_closed_trades(user)", self.fn("aster_closed_trades"))

    def test_new_durable_close_invalidates_the_display_list(self):
        self.assertIn('_stored_closes_cache.invalidate(str(user["uid"]))', self.fn("_persist_confirmed_aster_closed_trades"))

    def test_cache_module_has_no_database_or_exchange_import(self):
        src = (Path(__file__).parent / "chart_read_cache.py").read_text(encoding="utf-8")
        for forbidden in ("import main", "firestore", "aster_", "httpx", "submit"):
            self.assertNotIn(forbidden, src.split('"""', 2)[2])


if __name__ == "__main__":
    unittest.main()
