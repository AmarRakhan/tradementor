"""Kostenreductie 4.1 on the REAL stack: production ASGI entrypoint + real Firestore SDK on the emulator + HTTP fake Aster.

Proves that with the display read cache ON the chart/status routes return the same candles, zones and markers as with
the cache OFF (the original direct reads), including after new samples and new Strategy-2 audit rows are written, and
that no order is placed."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

import test_close_profits_2_0_e2e_stack as base

setUpModule = base.setUpModule
tearDownModule = base.tearDownModule


@unittest.skipUnless(base.READY, "needs Firestore emulator")
class ChartReadCacheParity(base.E2E):
    allow_unmocked = True              # chart routes read account endpoints; no order endpoint is involved

    def setUp(self):
        super().setUp()
        self.main = base.S.main
        self.fake.add("AAOIUSDT", "SHORT", 8.0, mark=100.0, entry=105.0)
        self.fake.add("BTCUSDT", "LONG", 4.0, mark=100.0, entry=98.0)
        self.main._chart_candle_cache.clear()
        self.main._chart_audit_cache.clear()
        self._flag = os.environ.get("CHART_READ_CACHE_ENABLED")
        self.root = self.db.collection("users").document(self.uid)
        now = datetime.now(timezone.utc)
        bucket = int(now.timestamp() * 1000) // 900_000 * 900_000
        for i in range(40):                                   # 10 hours of 15m history + 5m history
            b = bucket - (40 - i) * 900_000
            self.root.collection("asterPortfolioChart15m").document(str(b)).set(
                {"timeframe": "15m", "bucketMs": b, "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i,
                 "firstSampleAtMs": b, "lastSampleAtMs": b + 1, "sampleCount": 3, "source": "aster-account-equity"})
        for i in range(60):
            b = bucket - (60 - i) * 300_000
            self.root.collection("asterPortfolioChart5m").document(str(b)).set(
                {"timeframe": "5m", "bucketMs": b, "open": 100, "high": 102, "low": 98, "close": 101,
                 "firstSampleAtMs": b, "lastSampleAtMs": b + 1, "sampleCount": 2, "source": "aster-account-equity"})
        self.audit = self.db.collection("asterStrategy2").document(self.uid).collection("audit")
        for i in range(25):
            ts = now - timedelta(minutes=30 * i + 1)
            self.audit.document(f"a{i}").set({"event": "OPEN_LEG", "timestamp": ts, "timestampMs": int(ts.timestamp() * 1000),
                                              "symbol": "BTCUSDT", "side": "LONG", "filledNotional": 10.0})

    def tearDown(self):
        if self._flag is None:
            os.environ.pop("CHART_READ_CACHE_ENABLED", None)
        else:
            os.environ["CHART_READ_CACHE_ENABLED"] = self._flag
        super().tearDown()

    def get(self, path):
        r = self.http.get(path)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def views(self):
        chart = self.get("/v1/me/aster/portfolio-chart?timeframe=15m&limit=600")
        chart5 = self.get("/v1/me/aster/portfolio-chart?timeframe=5m&limit=320")
        events = self.get("/v1/me/aster/portfolio-chart/events?timeframe=15m")
        # samples/sourceAtMs/firstSampleAtMs change with every persisted sample (each call writes one), cache or not.
        volatile = ("updatedAt", "samples", "sourceAtMs", "firstSampleAtMs")
        strip = lambda rows: [{k: v for k, v in row.items() if k not in volatile} for row in rows]
        return {"candles15": strip(chart["candles"]), "zones15": chart.get("zones"), "markers15": chart.get("markers"),
                "candles5": strip(chart5["candles"]), "events": events["markers"]}

    def both(self):
        os.environ["CHART_READ_CACHE_ENABLED"] = "false"
        direct = self.views()
        os.environ["CHART_READ_CACHE_ENABLED"] = "true"
        cached = self.views()
        return direct, cached

    def test_cached_routes_equal_direct_reads_and_place_no_order(self):
        orders = len(self.fake.accepted())
        direct, cached = self.both()
        self.assertEqual(cached, direct)
        self.assertTrue(direct["candles15"] and direct["events"])
        self.assertEqual(len(self.fake.accepted()), orders)
        # freshness: the cached current candle carries the sample that was just written
        chart = self.get("/v1/me/aster/portfolio-chart?timeframe=15m&limit=600")
        last = chart["candles"][-1]
        doc = self.root.collection("asterPortfolioChart15m").document(str(last["atMs"])).get().to_dict()
        self.assertEqual(last["samples"], max(1, int(doc["sampleCount"])))
        self.assertEqual(last["sourceAtMs"], int(doc["lastSampleAtMs"]))

    def test_new_audit_rows_and_samples_appear_exactly_as_with_direct_reads(self):
        os.environ["CHART_READ_CACHE_ENABLED"] = "true"
        self.views()                                          # warm the cache
        ts = datetime.now(timezone.utc)
        self.audit.document("new-tp").set({"event": "FULL_TP", "timestamp": ts, "timestampMs": int(ts.timestamp() * 1000),
                                           "symbol": "AAOIUSDT", "side": "SHORT", "realizedPnlUsd": 1.23})
        self.main._chart_audit_cache.clear()                  # bypass the 2-second reuse window of the warm-up call
        self.main._chart_candle_cache.clear()
        os.environ["CHART_READ_CACHE_ENABLED"] = "true"
        self.views()
        ts2 = datetime.now(timezone.utc)
        self.audit.document("new-open").set({"event": "OPEN_LEG", "timestamp": ts2, "timestampMs": int(ts2.timestamp() * 1000),
                                             "symbol": "ETHUSDT", "side": "LONG", "filledNotional": 5.0})
        import time as _t
        _t.sleep(2.1)                                         # past the reuse window: the tail read must pick it up
        direct, cached = self.both()
        self.assertEqual(cached, direct)
        self.assertTrue(any(m.get("symbol") == "ETHUSDT" or "ETHUSDT" in str(m) for m in cached["events"]), cached["events"])


if __name__ == "__main__":
    unittest.main()
