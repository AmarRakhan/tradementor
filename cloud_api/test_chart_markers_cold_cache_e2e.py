"""Chart-label fix (#738) on the REAL stack: production ASGI entrypoint, real Firestore SDK on the emulator, real
gateway against the HTTP-level fake Aster (same setup as test_close_profits_2_0_e2e_stack).

Reproduces the reported bug first (cold cache, user never opened "Trades gesloten" -> chart has NO labels) and then
proves the fix (the chart route fills the cache itself -> moneybag + entry labels appear), without any extra order."""
from __future__ import annotations

import unittest
import uuid

import test_close_profits_2_0_e2e_stack as base

setUpModule = base.setUpModule
tearDownModule = base.tearDownModule


@unittest.skipUnless(base.READY, "needs Firestore emulator")
class ColdCacheChartLabels(base.E2E):
    allow_unmocked = True              # the chart route also reads account endpoints; no order endpoint is involved

    def setUp(self):
        super().setUp()
        self.main = base.S.main
        self.fake.add("AAOIUSDT", "SHORT", 8.0, mark=100.0, entry=105.0)
        self.fake.add("BTCUSDT", "SHORT", 4.0, mark=100.0, entry=104.0)

    def cold(self):
        with self.main._cache_lock:
            self.main._aster_closed_trades_cache.clear()
            self.main._chart_fill_activity_cache.clear()
        self.main._closed_trades_warmup._attempts.clear()

    def manual_close(self, symbol, qty, pct=25):
        r = self.http.post(f"/v1/me/aster/positions/{symbol}/close", json={
            "confirm": True, "side": "SHORT", "expected_quantity": qty, "percentage": pct,
            "idempotency_key": "e2e-chart-" + uuid.uuid4().hex})
        self.assertEqual(r.status_code, 200, r.text)

    def chart_markers(self):
        r = self.http.get("/v1/me/aster/portfolio-chart?timeframe=15m&limit=600")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["markers"]

    def test_bug_reproduced_cold_cache_without_warmup_shows_no_labels(self):
        self.manual_close("AAOIUSDT", 8.0)
        self.cold()
        original = self.main._closed_trades_warmup.ensure
        self.main._closed_trades_warmup.ensure = lambda uid, user: None
        try:
            markers = self.chart_markers()
        finally:
            self.main._closed_trades_warmup.ensure = original
        self.assertEqual([m for m in markers if m.get("kind") == "tp"], [])      # what Amar saw: no moneybag

    def test_fix_cold_cache_chart_route_loads_history_and_shows_the_moneybag(self):
        self.manual_close("AAOIUSDT", 8.0)
        self.manual_close("BTCUSDT", 4.0, pct=50)
        orders_before = len(self.fake.accepted())
        self.cold()
        markers = self.chart_markers()
        tp = [m for m in markers if m.get("kind") == "tp"]
        self.assertTrue(tp, markers)                                              # moneybag(s) present again
        self.assertEqual(len(self.fake.accepted()), orders_before)                # the chart placed NO order
        # the confirmed closes are now also stored durably, so a later cold instance still has them
        stored = list(self.db.collection("users").document(self.uid).collection("asterClosedTrades").stream())
        self.assertGreaterEqual(len(stored), 1)
        # Kostenreductie 4.1: the labels came from the lean chart loader, not from the heavy closed-trades loader
        self.assertNotIn(self.uid, self.main._aster_closed_trades_cache)

    def test_second_chart_load_reuses_the_warm_cache(self):
        self.manual_close("AAOIUSDT", 8.0)
        self.cold()
        self.chart_markers()
        stamp = self.main._chart_fill_activity_cache[self.uid][0]
        self.chart_markers()
        self.assertEqual(self.main._chart_fill_activity_cache[self.uid][0], stamp)   # no second history fetch

    def test_unreadable_history_never_breaks_the_chart(self):
        self.cold()
        original = self.main._closed_trades_warmup._loader
        self.main._closed_trades_warmup._loader = lambda user: (_ for _ in ()).throw(RuntimeError("Aster down"))
        try:
            markers = self.chart_markers()                                       # still HTTP 200
        finally:
            self.main._closed_trades_warmup._loader = original
        self.assertIsInstance(markers, list)


if __name__ == "__main__":
    unittest.main()
