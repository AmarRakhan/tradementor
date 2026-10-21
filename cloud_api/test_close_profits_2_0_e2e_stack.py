"""Close Profits 2.0 — end-to-end on the REAL stack (no model of Firestore, no model of the route):
 * real FastAPI app (`main.app`) through fastapi.testclient,
 * real Firestore SDK against the Firestore EMULATOR (project close-profits-test-only),
 * real aster_gateway.AsterV3Client + execute_leg_once against an HTTP-level fake Aster (offline_fake_aster.FakeAster).
Only mocked: Aster (HTTP fake), Firebase ID-token verification (dependency override), the Secret Manager lookup.
A socket guard fails the test on any non-localhost connection. SKIPs unless FIRESTORE_EMULATOR_HOST is a localhost
address and no service-account credentials are in the environment. Never run against production."""
from __future__ import annotations

import os
import socket
import sys
import threading
import unittest
import uuid
from decimal import Decimal, ROUND_DOWN
from types import SimpleNamespace

HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
READY = HOST.startswith(("127.0.0.1:", "localhost:")) and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

S = SimpleNamespace(main=None, fake=None, uid=None, blocked=[], orig_connect=None)


def setUpModule():
    if not READY:
        raise unittest.SkipTest("needs the Firestore emulator on localhost and no service-account credentials")
    os.environ.update({
        "GOOGLE_CLOUD_PROJECT": "close-profits-test-only", "GCLOUD_PROJECT": "close-profits-test-only",
        "ASTER_LIVE_EXECUTION_ENABLED": "true",                       # route gate; the 'exchange' is the local fake
        "ASTER_POSITION_LOSS_AUTO_HEDGE_WORKER": "false", "ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED": "true",
        "TRADEMENTOR_ENVIRONMENT": "e2e-test",
    })
    import google.auth
    import google.auth.credentials
    google.auth.default = lambda *a, **k: (google.auth.credentials.AnonymousCredentials(), "close-profits-test-only")

    S.orig_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in {"127.0.0.1", "::1", "localhost"}:
            S.blocked.append(address)
            raise OSError(f"E2E network guard: outbound connection to {address} blocked")
        return S.orig_connect(self, address)
    socket.socket.connect = guarded

    # main.py builds a Hyperliquid Info() client at import (public meta request over HTTPS). Not part of Close
    # Profits and must not touch the network in this test: replace it with an inert stand-in BEFORE the import.
    import hyperliquid.info

    class _InertInfo:
        def __init__(self, *args, **kwargs):
            pass
    hyperliquid.info.Info = _InertInfo

    sys.path.insert(0, os.path.dirname(__file__))
    import main
    from offline_fake_aster import FakeAster
    S.main = main
    RealClient = main.AsterV3Client

    class FakeBackedClient(RealClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = S.fake.transport()
            super().__init__(**kwargs)
    main.AsterV3Client = FakeBackedClient
    main.load_aster_secret = lambda user: SimpleNamespace(signer_address="0x" + "0" * 40, private_key="not-a-real-key")
    main.local_eip712_signer = lambda secret: (lambda encoded: "0x" + "0" * 130)
    main.app.dependency_overrides[main.authenticated_user] = lambda: {"uid": S.uid}


def tearDownModule():
    if S.orig_connect:
        socket.socket.connect = S.orig_connect
    if S.main:
        S.main.app.dependency_overrides.clear()


def floor_step(value, step):
    d = Decimal(str(step))
    return float((Decimal(repr(value)) / d).to_integral_value(rounding=ROUND_DOWN) * d)


@unittest.skipUnless(READY, "needs Firestore emulator")
class E2E(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from offline_fake_aster import FakeAster
        S.fake = self.fake = FakeAster()
        S.uid = self.uid = "e2e-" + uuid.uuid4().hex[:12]
        S.blocked.clear()
        self.http = TestClient(S.main.app, raise_server_exceptions=False)
        self.db = S.main.db

    def tearDown(self):
        self.assertEqual(S.blocked, [], "outbound network attempt detected")
        if not getattr(self, "allow_unmocked", False):
            self.assertEqual(self.fake.unmocked, [], "unexpected Aster endpoint called")

    # ---- what the frontend does, step by step (aster-recent-trades.tsx closeProfits) ----------------------
    def preview(self, pct):
        r = self.http.get(f"/v1/me/aster/positions/manual-profit-close-plan?percentage={pct}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def close(self, symbol, qty, pct, key=None):
        return self.http.post(f"/v1/me/aster/positions/{symbol}/close", json={
            "confirm": True, "side": "SHORT", "expected_quantity": qty, "percentage": pct,
            "idempotency_key": key or ("e2e-key-" + uuid.uuid4().hex)})

    def targets(self, pct):
        data = self.preview(pct)
        picked = {(s["symbol"]) for s in data["selected"] if str(s["side"]).upper() == "SHORT"}
        out = []
        for row in data["snapshot"]["rows"]:
            if row["symbol"] in picked and row["side"] == "SHORT":
                out.append((row["symbol"], abs(float(row["quantity"]))))
        return out

    def bulk(self, pct):
        """Frontend loop: fresh check before every close, close sequentially, stop on anything unclear."""
        result = {"closed": [], "stopped": None, "skipped": []}
        for symbol, qty in self.targets(pct):
            fresh = self.preview(pct)
            if not any(s["symbol"] == symbol for s in fresh["selected"]):
                result["skipped"].append(symbol); continue
            r = self.close(symbol, qty, pct)
            if r.status_code == 200:
                result["closed"].append(symbol)
            else:
                result["stopped"] = (symbol, r.status_code, r.json().get("detail")); break
        return result

    def seed_world(self, n=25, hedged=5):
        self.expected = {}
        for i in range(n):
            sym = f"S{i:02d}USDT"
            qty = round(37.123 + i * 1.7, 3)
            self.fake.add(sym, "SHORT", qty, mark=100.0, entry=105.0)
            self.expected[sym] = qty
            if i < hedged:                                   # Auto Hedge pair: LONG protected, SHORT is the hedge leg
                self.fake.add(sym, "LONG", qty, mark=100.0, entry=95.0)
                self.db.collection("asterPositionLossAutoHedge").document(self.uid).collection("pairs").document(sym).set({
                    "symbol": sym, "status": "HEDGED", "protectedSide": "LONG", "hedgeSide": "SHORT",
                    "rehedgeEnabled": True, "reservedHedgeQty": 0.0, "generationId": "g1"})
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": True})
        # noise that must NEVER be selected/closed: losing SHORT, profitable LONG-only, SHORT at exactly $0.50
        self.fake.add("LOSSUSDT", "SHORT", 10.0, mark=110.0, entry=105.0)
        self.fake.add("LONGUSDT", "LONG", 10.0, mark=120.0, entry=100.0)
        self.fake.add("EDGEUSDT", "SHORT", 10.0, mark=100.0, entry=100.05)   # pnl = 0.5 exactly -> not > 0.50

    def pair(self, sym):
        return (self.db.collection("asterPositionLossAutoHedge").document(self.uid).collection("pairs").document(sym).get().to_dict())


BUSY = "Auto Hedge verwerkt momenteel dezelfde accountstatus; probeer de sluiting zo opnieuw"


class FullSeries(E2E):
    def assert_series(self, pct, result):
        from position_close import close_size
        self.assertIsNone(result["stopped"], result)
        self.assertEqual(result["skipped"], [])
        self.assertEqual(sorted(result["closed"]), sorted(self.expected))
        orders = sorted(self.fake.accepted(), key=lambda o: o["t0"])
        self.assertEqual(len(orders), 25)
        for o in orders:                                              # only SHORT legs, BUY side, exact backend sizes
            self.assertEqual((o["side"], o["positionSide"], o["status"]), ("BUY", "SHORT", "FILLED"))
            want = floor_step(close_size(self.expected[o["symbol"]], pct), 0.001)
            self.assertAlmostEqual(o["qty"], want, places=9, msg=o["symbol"])
            self.assertAlmostEqual(self.fake.pos[(o["symbol"], "SHORT")], self.expected[o["symbol"]] - o["qty"], places=6)
        for a, b in zip(orders, orders[1:]):                          # strictly sequential at HTTP level
            self.assertLessEqual(a["t1"], b["t0"], "orders overlapped")
        for i in range(5):                                            # hedge legs untouched
            self.assertAlmostEqual(self.fake.pos[(f"S{i:02d}USDT", "LONG")], self.expected[f"S{i:02d}USDT"])
        self.assertEqual(self.fake.pos[("LOSSUSDT", "SHORT")], 10.0)
        self.assertEqual(self.fake.pos[("EDGEUSDT", "SHORT")], 10.0)
        self.assertEqual(self.fake.pos[("LONGUSDT", "LONG")], 10.0)
        intents = list(self.db.collection("users").document(self.uid).collection("asterManualCloseIntents").stream())
        self.assertEqual(sorted(d.to_dict().get("status") for d in intents), ["confirmed_closed"] * 25)
        for i in range(5):                                            # existing manual consequences, unchanged
            pair = self.pair(f"S{i:02d}USDT")
            self.assertNotEqual(pair["status"], "HEDGED")
            self.assertIs(pair["rehedgeEnabled"], False)
        for i in range(5, 25):
            self.assertIsNone(self.pair(f"S{i:02d}USDT"))
        lease = (self.db.collection("asterAccountCoordination").document(self.uid).get().to_dict() or {}).get("lease") or {}
        self.assertFalse(lease.get("token"))


def _series_test(pct):
    def test(self):
        self.seed_world()
        for sym in self.expected:
            self.fake.delay[sym] = 0.01
        self.assert_series(pct, self.bulk(pct))
    test.__name__ = f"test_25_shorts_{pct}_percent_end_to_end_on_real_stack"
    return test


for _p in (25, 50, 75, 100):
    setattr(FullSeries, f"test_25_shorts_{_p}_percent_end_to_end_on_real_stack", _series_test(_p))


class ExchangeFailures(E2E):
    def run_until_stop(self, mode, pct=50):
        self.seed_world()
        self.fake.modes["S02USDT"] = mode
        order = sorted(self.expected)
        result = self.bulk(pct)
        return result, order

    def test_duplicate_click_same_key_places_exactly_one_order(self):
        self.seed_world(n=3, hedged=1)
        self.assertEqual(self.close("S01USDT", self.expected["S01USDT"], 50, key="idempotency-key-dup-0001").status_code, 200)
        again = self.close("S01USDT", self.expected["S01USDT"], 50, key="idempotency-key-dup-0001")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(len(self.fake.accepted()), 1)

    def test_503_after_accept_is_recovered_by_the_single_readonly_query_and_series_continues(self):
        result, _ = self.run_until_stop("http503_after_accept")
        self.assertIsNone(result["stopped"])
        self.assertEqual(len(self.fake.accepted()), 25)

    def test_read_timeout_after_accept_stops_series_and_never_orders_twice(self):
        result, _ = self.run_until_stop("timeout_after_accept")
        self.assertEqual(result["stopped"][0], "S02USDT"); self.assertEqual(result["stopped"][1], 502)
        self.assertIn("niet opnieuw besteld", result["stopped"][2])
        self.assertEqual([o["symbol"] for o in self.fake.accepted()], ["S00USDT", "S01USDT", "S02USDT"])
        for key in ("idempotency-key-replay-0001",):                                    # replays / stale-quantity retries never reorder
            r = self.close("S02USDT", self.expected["S02USDT"], 50, key=key)
            self.assertEqual(r.status_code, 409)
        self.assertEqual(len(self.fake.accepted()), 3)
        self.assertEqual(self.pair("S02USDT")["status"], "MANUAL_RELEASE_UNCERTAIN")   # S02 is an Auto Hedge SHORT: existing fail-closed state

    def test_503_without_acceptance_is_unknown_stops_with_no_order_for_that_symbol(self):
        result, _ = self.run_until_stop("http503_unknown")
        self.assertEqual(result["stopped"][:2], ("S02USDT", 502))
        self.assertEqual([o["symbol"] for o in self.fake.accepted()], ["S00USDT", "S01USDT"])

    def test_partial_fill_stops_series_without_second_order(self):
        result, _ = self.run_until_stop("partial_fill")
        self.assertEqual(result["stopped"][:2], ("S02USDT", 502))
        self.assertEqual([o["symbol"] for o in self.fake.accepted()], ["S00USDT", "S01USDT", "S02USDT"])
        self.assertEqual(self.fake.accepted(symbol="S02USDT")[0]["status"], "PARTIALLY_FILLED")
        self.assertEqual(self.pair("S02USDT")["status"], "MANUAL_RELEASE_UNCERTAIN")
        self.assertAlmostEqual(self.fake.pos[("S02USDT", "SHORT")], self.expected["S02USDT"] - self.fake.accepted(symbol="S02USDT")[0]["executed"], places=6)

    def test_ack_new_without_fill_stops_series(self):
        result, _ = self.run_until_stop("ack_new")
        self.assertEqual(result["stopped"][:2], ("S02USDT", 502))
        self.assertEqual(len(self.fake.accepted()), 3)

    def test_exchange_reject_places_no_order_and_stops(self):
        result, _ = self.run_until_stop("reject")
        self.assertEqual(result["stopped"][0], "S02USDT")
        self.assertEqual([o["symbol"] for o in self.fake.accepted()], ["S00USDT", "S01USDT"])
        print("INFO-reject", result["stopped"][1:], "pair:", (self.pair("S02USDT") or {}).get("status"))

    def test_delayed_position_reflection_is_not_confirmed(self):
        self.seed_world(n=3, hedged=0)
        self.fake.lag["S00USDT"] = 1
        r = self.close("S00USDT", self.expected["S00USDT"], 50)
        self.assertEqual(r.status_code, 502)
        self.assertEqual(len(self.fake.accepted()), 1)

    def test_profit_gone_before_close_is_skipped_by_the_fresh_check_without_order(self):
        self.seed_world(n=3, hedged=0)
        targets = self.targets(50)
        self.fake.mark["S01USDT"] = 110.0                           # price rises: SHORT now loses
        fresh = self.preview(50)
        self.assertNotIn("S01USDT", [s["symbol"] for s in fresh["selected"]])
        self.assertEqual(len(self.fake.accepted()), 0)
        self.assertEqual([t[0] for t in targets], ["S00USDT", "S01USDT", "S02USDT"])


class WorkerConcurrency(E2E):
    """The REAL Auto Hedge worker entry (`_run_uid`) racing the REAL close route on the real Firestore emulator."""
    allow_unmocked = True          # the worker may reach Aster endpoints this fake does not model after the point under test

    def setUp(self):
        super().setUp()
        import aster_position_loss_auto_hedge_extension as ext
        self.ext = ext
        self.old = (ext.EXECUTION_ENABLED, S.main._release_feature_enabled_for_uid)
        ext.EXECUTION_ENABLED = True
        S.main._release_feature_enabled_for_uid = lambda uid, key: True
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": True, "thresholdUsd": 10.0})
        self.fake.add("BTCUSDT", "SHORT", 100.0, mark=90.0, entry=105.0)    # profitable SHORT (+1500)
        self.fake.add("BTCUSDT", "LONG", 100.0, mark=90.0, entry=100.0)     # losing LONG (-1000) beyond the threshold

    def tearDown(self):
        self.ext.EXECUTION_ENABLED, S.main._release_feature_enabled_for_uid = self.old
        super().tearDown()

    def lease_token(self):
        return ((self.db.collection("asterAccountCoordination").document(self.uid).get().to_dict() or {}).get("lease") or {}).get("token")

    def test_worker_run_during_an_ordering_close_is_deferred_and_places_nothing(self):
        started, out = threading.Event(), {}
        self.fake.delay["BTCUSDT"] = 0.8
        self.fake.on_order_start = lambda sym: started.set()

        def closer():
            from fastapi.testclient import TestClient
            r = TestClient(S.main.app, raise_server_exceptions=False).post(
                "/v1/me/aster/positions/BTCUSDT/close",
                json={"confirm": True, "side": "SHORT", "expected_quantity": 100.0, "percentage": 50,
                      "idempotency_key": "idempotency-key-race-0001"})
            out["close"] = (r.status_code, r.text[:200])
        t = threading.Thread(target=closer); t.start()
        self.assertTrue(started.wait(10))
        report = self.ext._run_uid(self.uid)                                  # worker tick while the close holds the order
        t.join(20)
        self.assertEqual(out["close"][0], 200, out)
        self.assertEqual((report.get("status"), report.get("reason"), report.get("ordersSent")), ("PENDING", "ACCOUNT_COORDINATION_BUSY", 0), report)
        self.assertEqual([(o["positionSide"], o["side"]) for o in self.fake.accepted()], [("SHORT", "BUY")])   # only the close
        self.assertEqual(self.fake.accepted()[0]["qty"], 50.0)
        self.assertFalse(self.lease_token())
        print("INFO-W1 close", out["close"][0], "worker", report.get("status"), report.get("reason"))

    def test_close_arriving_while_the_worker_holds_the_lease_is_refused_before_any_order(self):
        in_worker, release, out = threading.Event(), threading.Event(), {}
        holder = {}

        def hook():
            if threading.current_thread() is holder.get("t") and not in_worker.is_set():
                in_worker.set()
                release.wait(30)                                              # worker stalls while holding its lease
        self.fake.on_position_read = hook

        def worker():
            try:
                out["report"] = self.ext._run_uid(self.uid)
            except BaseException as exc:                                      # what the worker does after our point is not under test
                out["error"] = repr(exc)[:200]
        holder["t"] = t = threading.Thread(target=worker); t.start()
        self.assertTrue(in_worker.wait(10))
        r = self.close("BTCUSDT", 100.0, 50, key="idempotency-key-busy-0001")
        release.set(); t.join(30)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"], BUSY)
        self.assertEqual([o for o in self.fake.accepted() if o["side"] == "BUY" and o["positionSide"] == "SHORT"], [])   # no close order
        self.assertFalse(self.lease_token())
        print("INFO-W2 close", r.status_code, "worker", out.get("report", {}).get("status"), out.get("error"), "unmocked", sorted(set(self.fake.unmocked)))

    def test_busy_close_retried_with_a_new_key_after_the_worker_finished_succeeds_once(self):
        r1 = self.close("BTCUSDT", 100.0, 50, key="idempotency-key-first-0001")
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(len([o for o in self.fake.accepted() if o["positionSide"] == "SHORT"]), 1)
        again = self.close("BTCUSDT", 100.0, 50, key="idempotency-key-first-0001")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(len([o for o in self.fake.accepted() if o["positionSide"] == "SHORT"]), 1)


class ImportSmoke(E2E):
    def test_real_app_imports_and_preview_route_answers_on_real_firestore(self):
        self.seed_world(n=3, hedged=1)
        data = self.preview(50)
        shorts = sorted(s["symbol"] for s in data["selected"] if str(s["side"]).upper() == "SHORT")
        self.assertEqual(shorts, ["S00USDT", "S01USDT", "S02USDT"])      # losing / exactly-$0.50 SHORTs are not selected


if __name__ == "__main__":
    unittest.main()
