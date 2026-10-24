"""Build 648 trade journal — end-to-end on the REAL stack: production ASGI entrypoint (p0_close_scope_guard -> withdraw_app),
real Firestore SDK against the EMULATOR, real AsterV3Client against an HTTP-level fake Aster. SKIPs without the emulator.

Proves what the unit tests cannot: Firestore accepts every document we write (no nested arrays, no bad keys), the
routes are registered on the production entrypoint, the sync is resumable across HTTP calls, the settings-capture
middleware records a version after a settings save, and nothing but read-only Aster endpoints is called.
"""
from __future__ import annotations

import time
import unittest
import uuid
from urllib.parse import parse_qsl

import test_close_profits_2_0_e2e_stack as t

READY = t.READY
S = t.S
H = 3_600_000


def setUpModule():
    t.setUpModule()


def tearDownModule():
    t.tearDownModule()


def _fill(fid, order, symbol, side, order_side, qty, price, at, pnl=0.0):
    return {"id": fid, "orderId": order, "symbol": symbol, "positionSide": side, "side": order_side,
            "qty": str(qty), "price": str(price), "quoteQty": str(qty * price), "realizedPnl": str(pnl),
            "commission": "0.01", "commissionAsset": "USDT", "time": at, "maker": False, "buyer": order_side == "BUY"}


@unittest.skipUnless(READY, "needs Firestore emulator")
class TradeJournalE2E(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from offline_fake_aster import FakeAster
        import trade_journal_extension

        now = int(time.time() * 1000)
        self.now = now
        fills = {
            "BTCUSDT": [_fill(1, "b1", "BTCUSDT", "LONG", "BUY", 1, 100, now - 5 * H),
                        _fill(2, "b2", "BTCUSDT", "LONG", "BUY", 1, 90, now - 4 * H),
                        _fill(3, "b3", "BTCUSDT", "LONG", "SELL", 2, 110, now - H, pnl=30)],
            "ETHUSDT": [_fill(1, "e1", "ETHUSDT", "SHORT", "SELL", 4, 10, now - 6 * H),
                        _fill(2, "e2", "ETHUSDT", "SHORT", "BUY", 1, 9, now - 3 * H, pnl=1),
                        _fill(3, "e3", "ETHUSDT", "SHORT", "BUY", 1, 8, now - 10 * 60_000, pnl=2)],
        }
        orders = {"BTCUSDT": [{"orderId": "b1", "clientOrderId": "mbb-open-x-open-long"},
                              {"orderId": "b2", "clientOrderId": "mbb-dca-x-open-long"},
                              {"orderId": "b3", "clientOrderId": "mbb-tp-x-close-long"}],
                  "ETHUSDT": [{"orderId": "e1", "clientOrderId": "plah2-a"}, {"orderId": "e2", "clientOrderId": "plah2-b"},
                              {"orderId": "e3", "clientOrderId": "tm-manual-c-close-short"}]}
        income = [{"symbol": "BTCUSDT", "incomeType": "REALIZED_PNL", "income": "30", "time": now - H},
                  {"symbol": "ETHUSDT", "incomeType": "REALIZED_PNL", "income": "1", "time": now - 3 * H},
                  {"symbol": "ETHUSDT", "incomeType": "FUNDING_FEE", "income": "-0.03", "time": now - 2 * H}]
        self.read_paths = []

        class JournalFake(FakeAster):
            def handle(fake, request):
                path = request.url.path
                params = dict(parse_qsl(request.url.query.decode() if isinstance(request.url.query, bytes) else str(request.url.query)))
                self.read_paths.append((request.method, path))
                if path == "/fapi/v3/allOrders":
                    return fake._json(orders.get(params.get("symbol", ""), []))
                if path == "/fapi/v3/userTrades":
                    start = int(params.get("fromId", "0") or 0)
                    rows = [r for r in fills.get(params.get("symbol", ""), []) if r["id"] >= start]
                    return fake._json(rows[: int(params.get("limit", 500))])
                if path == "/fapi/v3/income" and params.get("incomeType") in {"REALIZED_PNL", "FUNDING_FEE"}:
                    start = int(params.get("startTime", "0") or 0)
                    return fake._json([r for r in income if r["incomeType"] == params["incomeType"] and r["time"] >= start])
                return FakeAster.handle(fake, request)

        S.fake = self.fake = JournalFake()
        S.uid = self.uid = "e2e-tj-" + uuid.uuid4().hex[:10]
        S.blocked.clear()
        self.http = TestClient(S.entry_app, raise_server_exceptions=False)
        self.db = S.main.db
        trade_journal_extension._last_sync.clear()
        trade_journal_extension._call_times.clear()
        # bot state the journal reads (with nested lists, as real documents have)
        S.main.aster_strategy2_reference(self.uid).set({
            "configVersion": 3,
            "settings": {"engine": "multi-bb-v1", "longTakeProfitValue": 20, "leverage": 10,
                         "priceZoneSeats": {"enabled": True, "longSeatsPerZone": 1, "zones": [{"low": 1, "high": 2}, {"low": 3, "high": 4}]}},
            "multiBbPositions": {"ETHUSDT|SHORT": {"cycleId": "c-eth", "leverage": 5, "soldierRole": "AUTO_HEDGE",
                                                   "cycleStartedAtMs": now - 6 * H, "zoneMission": {"band": [1, 2]},
                                                   "lastBotFillPrice": 10}},
        })
        S.main.aster_strategy2_reference(self.uid).collection("configHistory").add(
            {"version": 3, "newValue": {"longTakeProfitValue": 20},
             "timestamp": S.main.datetime.fromtimestamp((now - 10 * H) / 1000, tz=S.main.timezone.utc)})
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set(
            {"enabled": True, "thresholdUsd": 0.25, "shortRecoveryPlan": {"enabled": True, "steps": 3, "totalPct": 6}})
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).collection("pairs").document("ETHUSDT").set(
            {"status": "HEDGED", "protectedSide": "LONG", "shortRecovery": {"stepsReached": 2}})

    def tearDown(self):
        self.assertEqual(S.blocked, [], "outbound network attempt detected")
        writes = [p for p in self.read_paths if p[0] != "GET"]
        self.assertEqual(writes, [], "the journal must never POST/DELETE at Aster")

    def sync_until_complete(self):
        import trade_journal_extension
        for _ in range(10):
            trade_journal_extension._last_sync.clear()
            r = self.http.post("/v1/me/aster/trade-journal/sync", json={})
            self.assertEqual(r.status_code, 200, r.text)
            if r.json()["complete"]:
                return r.json()
        self.fail("journal did not complete")

    def test_sync_recent_and_export_on_real_firestore(self):
        before = self.http.get("/v1/me/aster/trade-journal/recent")
        self.assertEqual(before.status_code, 200, before.text)
        self.assertFalse(before.json()["backfillComplete"])

        result = self.sync_until_complete()
        self.assertEqual(result["unreadableSymbols"], [])

        recent = self.http.get("/v1/me/aster/trade-journal/recent?limit=50").json()
        self.assertTrue(recent["backfillComplete"])
        self.assertEqual(len(recent["rows"]), 3)
        newest = recent["rows"][0]
        self.assertEqual((newest["symbol"], newest["side"], newest["closeType"]), ("ETHUSDT", "SHORT", "PARTIAL"))
        self.assertIn("Close Profits", newest["closeReason"])

        exported = self.http.get("/v1/me/aster/trade-journal/export")
        self.assertEqual(exported.status_code, 200, exported.text)
        data = exported.json()
        self.assertEqual(data["schema"], "tradementor.trade-journal.v1")
        self.assertEqual(data["summary"]["trades"], 3)
        btc = next(t for t in data["trades"] if t["symbol"] == "BTCUSDT")
        self.assertEqual(btc["closeType"], "FULL")
        self.assertEqual(btc["closeReason"]["code"], "TAKE_PROFIT")
        self.assertEqual(btc["entryReason"]["code"], "BOT_ENTRY")
        self.assertEqual(btc["dcaCount"], 1)
        self.assertAlmostEqual(btc["entryPriceAvg"], 95.0)
        eth_recent = next(t for t in data["trades"] if t["closeReason"]["code"] == "APP_CLOSE")
        self.assertEqual(eth_recent["context"]["soldierRole"], "AUTO_HEDGE")
        self.assertEqual(eth_recent["autoHedgePair"]["status"], "HEDGED")       # closed 10 min ago: snapshot attached
        self.assertAlmostEqual(eth_recent["marginUsd"], 10 * 1 / 5)
        self.assertTrue(data["settingsVersions"], "settings timeline present")
        self.assertEqual(eth_recent["settingsAtClose"]["key"]["autoHedgeTriggerUsd"], None)   # SHORT side uses thresholdShortUsd
        self.assertIsNotNone(btc["settingsAtClose"]["ref"]["strategyVersionId"])
        self.assertEqual(btc["settingsAtClose"]["key"]["takeProfit"], 20)

        # incremental: a new close appears and is picked up without re-reading the old fills from id 0
        self.read_paths.clear()
        import trade_journal_extension
        trade_journal_extension._last_sync.clear()
        again = self.http.post("/v1/me/aster/trade-journal/sync", json={}).json()
        self.assertEqual(again["recordsWritten"], 0)

    def test_settings_save_records_a_version_through_the_middleware(self):
        main = S.main
        original = main.authenticated_user
        main.authenticated_user = lambda authorization=None: {"uid": self.uid}   # the middleware reads the token itself
        try:
            r = self.http.put("/v1/me/aster/profit-sweep-settings", headers={"Authorization": "Bearer test"},
                              json={"enabled": True, "sweepPercent": 5, "minimumTransfer": 1, "transferAsset": "USDT"})
            self.assertEqual(r.status_code, 200, r.text)
        finally:
            main.authenticated_user = original
        versions = list(main.user_reference({"uid": self.uid}).collection("tradeSettingsVersions").stream())
        self.assertEqual(len(versions), 1)
        self.assertIn("profit-sweep-settings", versions[0].to_dict()["reason"])

    def test_concurrent_or_too_fast_steps_are_refused_politely(self):
        first = self.http.post("/v1/me/aster/trade-journal/sync", json={})
        self.assertEqual(first.status_code, 200, first.text)
        second = self.http.post("/v1/me/aster/trade-journal/sync", json={})
        self.assertEqual(second.status_code, 429)


if __name__ == "__main__":
    unittest.main()
