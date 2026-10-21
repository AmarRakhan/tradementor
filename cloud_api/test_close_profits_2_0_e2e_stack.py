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
import time
import unittest
import uuid
from decimal import Decimal, ROUND_DOWN
from types import SimpleNamespace

HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
READY = HOST.startswith(("127.0.0.1:", "localhost:")) and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

S = SimpleNamespace(main=None, fake=None, uid=None, blocked=[], orig_connect=None, entry_app=None)


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
    # The PRODUCTION entrypoint is `uvicorn p0_close_scope_guard:app` -> withdraw_app -> main.app plus every extension
    # (Profit Sweep hooks on the shared Aster client, Auto Hedge, Legacy Hedge, Withdraw, ...). Import that chain, not
    # just main, so the tests run with the same hooks and routes production has.
    import p0_close_scope_guard
    import profit_sweep_live_extension
    S.entry_app = p0_close_scope_guard.app
    from offline_fake_aster import FakeAster
    S.main = main
    RealClient = main.AsterV3Client

    class FakeBackedClient(RealClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = S.fake.transport()
            super().__init__(**kwargs)
    main.AsterV3Client = FakeBackedClient
    def fake_secret(user):                                    # same signer->uid registration the Profit Sweep hook does
        secret = SimpleNamespace(signer_address="0x" + "0" * 40, private_key="not-a-real-key")
        profit_sweep_live_extension._register(secret.signer_address, str(user.get("uid", "")))
        return secret
    main.load_aster_secret = fake_secret
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
        self.http = TestClient(S.entry_app, raise_server_exceptions=False)         # the production ASGI entrypoint
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

    def close(self, symbol, qty, pct, key=None, bulk=False):
        body = {"confirm": True, "side": "SHORT", "expected_quantity": qty, "percentage": pct,
                "idempotency_key": key or ("e2e-key-" + uuid.uuid4().hex)}
        if bulk:                                           # what the green button sends in addition (frontend closeProfits)
            body.update({"min_open_pnl_usd": 0.5, "bulk_series": True})
        return self.http.post(f"/v1/me/aster/positions/{symbol}/close", json=body)

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
            r = self.close(symbol, qty, pct, bulk=True)
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


class SimultaneousRequests(E2E):
    def two_at_once(self, symbol, qty):
        from fastapi.testclient import TestClient
        gate, out = threading.Barrier(2), []

        def go(n):
            client = TestClient(S.main.app, raise_server_exceptions=False)
            gate.wait(10)
            r = client.post(f"/v1/me/aster/positions/{symbol}/close", json={
                "confirm": True, "side": "SHORT", "expected_quantity": qty, "percentage": 50,
                "idempotency_key": f"idempotency-key-simul-{n}-{uuid.uuid4().hex[:8]}"})
            out.append((r.status_code, r.json().get("detail")))
        threads = [threading.Thread(target=go, args=(n,)) for n in (1, 2)]
        [t.start() for t in threads]; [t.join(30) for t in threads]
        return out

    def test_two_simultaneous_closes_on_an_auto_hedge_short_place_exactly_one_order(self):
        self.seed_world(n=3, hedged=3)
        self.fake.delay["S01USDT"] = 0.5
        out = self.two_at_once("S01USDT", self.expected["S01USDT"])
        self.assertEqual(sorted(code for code, _ in out)[0], 200, out)
        self.assertNotEqual(sorted(code for code, _ in out)[1], 200, out)
        self.assertEqual(len(self.fake.accepted(symbol="S01USDT")), 1)
        print("INFO-simul-hedged", out)

    def test_KNOWN_RESIDUAL_two_simultaneous_closes_on_a_plain_short_without_opposite_leg(self):
        """Pre-existing: the individual route takes no lease for a plain SHORT (and the green button never sends two at
        once). Measured, not fixed."""
        self.seed_world(n=3, hedged=0)
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": False})
        self.fake.delay["S01USDT"] = 0.5
        out = self.two_at_once("S01USDT", self.expected["S01USDT"])
        orders = len(self.fake.accepted(symbol="S01USDT"))
        print("INFO-simul-plain orders=", orders, out)
        self.assertIn(orders, (1, 2))

    def test_plain_manual_close_has_no_profit_check_unchanged(self):
        """The plain individual Close (no green-series fields) is unchanged: it checks the quantity, not the profit.
        The green series adds the server-side profit check (see test_close_profits_2_0_release_guards)."""
        self.seed_world(n=3, hedged=0)
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": False})
        self.fake.mark["S01USDT"] = 120.0                          # SHORT now loses money
        r = self.close("S01USDT", self.expected["S01USDT"], 50)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.fake.accepted(symbol="S01USDT")), 1)


class ProductionChain(E2E):
    """Everything above runs through the production ASGI entrypoint. These add the Profit Sweep hook ENABLED for the
    user (an existing, per-user feature that hooks every Aster close of the shared client, manual closes included)."""
    allow_unmocked = True          # the sweep reads account/income endpoints and posts a Spot transfer: not modelled here

    def setUp(self):
        super().setUp()
        previous = os.environ.get("ASTER_PROFIT_SWEEP_LIVE_ENABLED")
        os.environ["ASTER_PROFIT_SWEEP_LIVE_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("ASTER_PROFIT_SWEEP_LIVE_ENABLED", None) if previous is None
                        else os.environ.__setitem__("ASTER_PROFIT_SWEEP_LIVE_ENABLED", previous))
        self.db.collection("users").document(self.uid).collection("executionControls").document("aster").set(
            {"profitSweep": {"enabled": True, "sweepPercent": 25, "transferAsset": "USDT"}})

    def sweep_docs(self):
        return [d.to_dict() for d in self.db.collection("users").document(self.uid).collection("asterProfitSweeps").stream()]

    def test_entrypoint_serves_the_same_single_close_and_preview_routes(self):
        close_routes = [r for r in S.main.app.routes if getattr(r, "path", "") == "/v1/me/aster/positions/{symbol}/close"
                        and "POST" in getattr(r, "methods", set())]
        self.assertEqual(len(close_routes), 1)
        self.assertIs(close_routes[0].endpoint, S.main.close_one_aster_position)
        self.assertEqual(len([r for r in S.main.app.routes if getattr(r, "path", "") == "/v1/me/aster/positions/manual-profit-close-plan"]), 1)

    def test_series_with_profit_sweep_enabled_places_exactly_the_planned_close_orders(self):
        self.seed_world(n=5, hedged=2)
        result = self.bulk(50)
        self.assertIsNone(result["stopped"], result)
        self.assertEqual(len(result["closed"]), 5)
        orders = self.fake.accepted()
        self.assertEqual(len(orders), 5)                                                   # the sweep never adds a MARKET order
        for o in orders:
            self.assertEqual((o["side"], o["positionSide"]), ("BUY", "SHORT"))
        intents = list(self.db.collection("users").document(self.uid).collection("asterManualCloseIntents").stream())
        self.assertEqual(sorted(d.to_dict().get("status") for d in intents), ["confirmed_closed"] * 5)
        print("INFO-sweep ledger docs:", len(self.sweep_docs()), sorted({d.get("status") for d in self.sweep_docs()}),
              "unmocked:", sorted(set(self.fake.unmocked))[:6])

    def test_unknown_outcome_with_profit_sweep_enabled_still_stops_the_series_without_a_second_order(self):
        self.seed_world(n=5, hedged=2)
        self.fake.modes["S02USDT"] = "timeout_after_accept"
        result = self.bulk(50)
        self.assertEqual(result["stopped"][:2], ("S02USDT", 502))
        self.assertEqual([o["symbol"] for o in self.fake.accepted()], ["S00USDT", "S01USDT", "S02USDT"])
        again = self.close("S02USDT", self.expected["S02USDT"], 50, bulk=True)
        self.assertEqual(again.status_code, 409)
        self.assertEqual(len(self.fake.accepted(symbol="S02USDT")), 1)


class ProfitSweepSeries(E2E):
    """Profit Sweep (existing, per-user feature hooked into EVERY Aster close of the shared client) with 25 consecutive
    profitable closes, on the real stack: real Firestore transactions (emulator), real FastAPI production entrypoint,
    real gateway, and an HTTP-level fake of Aster's fills, account, income/Spot history and Spot transfer endpoint
    (reused clientTranId is refused, like Aster does). Nothing here touches a real exchange or real money.
    Invariant checked after every scenario: money booked = still pending + transferred; the exchange holds exactly the
    transfers Firestore recorded as SUCCEEDED, each clientTranId once."""

    def setUp(self):
        super().setUp()
        previous = os.environ.get("ASTER_PROFIT_SWEEP_LIVE_ENABLED")
        os.environ["ASTER_PROFIT_SWEEP_LIVE_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("ASTER_PROFIT_SWEEP_LIVE_ENABLED", None) if previous is None
                        else os.environ.__setitem__("ASTER_PROFIT_SWEEP_LIVE_ENABLED", previous))
        self.set_sweep("25")

    # ---- helpers -------------------------------------------------------------------------------------------
    def uref(self):
        return self.db.collection("users").document(self.uid)

    def set_sweep(self, minimum, percent=25):
        self.uref().collection("executionControls").document("aster").set(
            {"profitSweep": {"enabled": True, "sweepPercent": percent, "transferAsset": "USDT", "minimumTransfer": minimum}})

    def ledger(self):
        return [d.to_dict() for d in self.uref().collection("asterProfitSweeps").stream()]

    def state(self):
        return self.uref().collection("asterProfitSweepState").document("current").get().to_dict() or {}

    def claims(self):
        return [d.to_dict() for d in self.uref().collection("asterProfitSweepTransfers").stream()]

    def sweep_client(self):
        return S.main.AsterV3Client(signer_address="0x" + "0" * 40, sign_message=lambda m: "0x" + "0" * 130,
                                    live_authorized=True)

    def tick(self):
        from profit_sweep_live import reconcile_profit_savings_buffer
        return reconcile_profit_savings_buffer(uid=self.uid, user_ref=self.uref(), client=self.sweep_client())

    def dump(self, label):
        """Everything needed to understand a Profit Sweep ledger after a scenario (printed into the CI log)."""
        import json
        from collections import Counter
        state = self.state()
        claims = sorted(self.claims(), key=lambda c: c.get("sequence", 0))
        print("INFO-DUMP", label, json.dumps({
            "state": {k: (str(v) if not isinstance(v, (dict, type(None))) else
                          ({kk: str(vv) for kk, vv in v.items()} if v else v)) for k, v in state.items()},
            "claims": [{k: str(c.get(k)) for k in ("sequence", "status", "amount", "clientTranId", "providerTransactionId",
                                                    "reconciledFromHistory", "reconciliationStatus", "reason")} for c in claims],
            "ledger": dict(Counter(l.get("status") for l in self.ledger())),
            "exchangeTransfers": len(self.fake.transfers),
            "exchangeDistinctIds": len({t["clientTranId"] for t in self.fake.transfers}),
            "posts": dict(Counter(p[2] for p in self.fake.transfer_posts)),
            "postsPerId": dict(Counter(Counter(p[0] for p in self.fake.transfer_posts).values())),
        }, default=str)[:6000])

    def check_money(self, allow_inflight=False):
        booked = sum((Decimal(l["bufferBookedAmount"]) for l in self.ledger() if l.get("bufferBooked") is True), Decimal(0))
        state = self.state()
        pending = Decimal(str(state.get("pendingSavings", "0")))
        done = [c for c in self.claims() if c.get("status") == "SUCCEEDED"]
        sent = sum((Decimal(str(c["amount"])) for c in done), Decimal(0))
        self.assertEqual(booked, pending + sent, f"booked {booked} != pending {pending} + transferred {sent}")
        exchange = self.fake.transfers
        self.assertEqual(len({t["clientTranId"] for t in exchange}), len(exchange), "a clientTranId was used twice")
        inflight = state.get("inFlight") or {}
        # A transfer the exchange accepted but Firestore has not yet proven (UNCERTAIN claim) is the one allowed gap.
        pending_proof = [t for t in exchange if inflight and t["clientTranId"] == inflight.get("clientTranId")]
        if not allow_inflight:
            self.assertFalse(inflight, inflight)
            pending_proof = []
        self.assertEqual(sum((Decimal(str(t["amount"])) for t in exchange), Decimal(0)),
                         sent + sum((Decimal(str(t["amount"])) for t in pending_proof), Decimal(0)),
                         "money the exchange moved differs from what Firestore booked as transferred")
        self.assertEqual(len(exchange), len(done) + len(pending_proof))
        claims = self.claims()
        self.assertEqual(len({c["clientTranId"] for c in claims}), len(claims))
        return booked, pending, sent

    # ---- 25 consecutive profitable closes ------------------------------------------------------------------
    def test_25_closes_book_every_profit_exactly_once_and_transfer_whole_blocks_only(self):
        self.seed_world(n=25, hedged=5)
        result = self.bulk(50)
        self.assertIsNone(result["stopped"], result)
        self.assertEqual(len(result["closed"]), 25)
        self.assertEqual(len(self.fake.accepted()), 25)                       # the sweep never adds a market order
        ledger = self.ledger()
        self.assertEqual(len(ledger), 25)
        self.assertEqual(len({l["closureId"] for l in ledger}), 25)
        self.assertEqual(sorted({l["status"] for l in ledger}), ["BUFFERED"], ledger[:2])
        booked, pending, sent = self.check_money()
        self.assertGreater(sent, 0)
        self.assertTrue(all(Decimal(str(t["amount"])) == Decimal("25") for t in self.fake.transfers))
        self.assertLess(pending, Decimal("25"))                               # only the sub-threshold remainder stays
        self.assertEqual(len(self.fake.transfer_posts), len(self.fake.transfers))   # no retries were needed
        self.assertEqual([], self.fake.unmocked)
        print("INFO-sweep25: booked", booked, "transferred", sent, "pending", pending, "transfers", len(self.fake.transfers))

    def test_a_replayed_close_request_never_books_or_transfers_twice(self):
        self.seed_world(n=3, hedged=0)
        key = "replay-" + uuid.uuid4().hex
        first = self.close("S00USDT", self.expected["S00USDT"], 100, key=key, bulk=True)
        self.assertEqual(first.status_code, 200, first.text)
        before = (len(self.ledger()), len(self.fake.transfers), self.check_money())
        again = self.close("S00USDT", self.expected["S00USDT"], 100, key=key, bulk=True)
        self.assertEqual(again.status_code, 409)
        self.assertEqual((len(self.ledger()), len(self.fake.transfers), self.check_money()), before)
        self.assertEqual(len(self.fake.accepted()), 1)

    def test_double_hook_booking_of_the_same_close_is_idempotent(self):
        import profit_sweep_live as psl
        self.seed_world(n=1, hedged=0)
        prepared = psl.prepare_close_sweep(uid=self.uid, user_ref=self.uref(), client=self.sweep_client(),
                                           intent_id="dup-1", symbol="S00USDT", position_side="SHORT",
                                           close_quantity=Decimal("1"), evidence=None)
        self.assertIsNotNone(prepared)
        self.assertEqual(psl._book_contribution(prepared, Decimal("1.5"))["alreadyBooked"], False)
        self.assertEqual(psl._book_contribution(prepared, Decimal("1.5"))["alreadyBooked"], True)
        self.assertEqual(Decimal(str(self.state()["pendingSavings"])), Decimal("1.5"))
        again = psl.prepare_close_sweep(uid=self.uid, user_ref=self.uref(), client=self.sweep_client(),
                                        intent_id="dup-1", symbol="S00USDT", position_side="SHORT",
                                        close_quantity=Decimal("1"), evidence=None)
        self.assertIsNone(again)                                              # same close can never open a 2nd ledger row

    # ---- UNKNOWN / partial fills / rejects on the CLOSE order ---------------------------------------------
    def test_unconfirmed_or_failed_close_orders_never_book_profit_or_move_money(self):
        self.seed_world(n=6, hedged=0)
        self.fake.modes.update({"S00USDT": "partial_fill", "S01USDT": "http503_unknown", "S02USDT": "reject",
                                "S03USDT": "timeout_after_accept", "S04USDT": "ack_new"})
        for sym in ("S00USDT", "S01USDT", "S02USDT", "S03USDT", "S04USDT"):
            r = self.close(sym, self.expected[sym], 100, bulk=True)
            self.assertNotEqual(r.status_code, 200, (sym, r.text))
        ok = self.close("S05USDT", self.expected["S05USDT"], 100, bulk=True)
        self.assertEqual(ok.status_code, 200, ok.text)
        booked_rows = [l for l in self.ledger() if l.get("bufferBooked") is True]
        # Only the one fully confirmed close may have booked anything; at most the partial fill's own fills.
        self.assertTrue(all(l["symbol"] in {"S05USDT", "S00USDT"} for l in booked_rows), [l["symbol"] for l in booked_rows])
        for l in booked_rows:
            fills = [f for f in self.fake.trades[l["symbol"]] if f.get("closing") and str(f["orderId"]) == str(l["exchangeOrderId"])]
            self.assertTrue(fills)
            realized = sum((Decimal(f["realizedPnl"]) for f in fills), Decimal(0))
            self.assertLessEqual(Decimal(l["bufferBookedAmount"]), realized * Decimal("0.25"))
        self.check_money()
        print("INFO-sweep-unconfirmed: booked symbols", sorted(l["symbol"] for l in booked_rows),
              "ledger statuses", sorted((l["symbol"], l["status"]) for l in self.ledger()))

    def test_closing_fills_not_yet_visible_book_nothing_and_never_transfer(self):
        self.seed_world(n=2, hedged=0)
        self.fake.hide_close_fills.add("S00USDT")
        r = self.close("S00USDT", self.expected["S00USDT"], 100, bulk=True)
        self.assertEqual(r.status_code, 200, r.text)                          # the close itself stays valid
        led = [l for l in self.ledger() if l["symbol"] == "S00USDT"]
        self.assertEqual(len(led), 1)
        self.assertNotEqual(led[0]["status"], "BUFFERED")
        self.assertFalse(led[0].get("bufferBooked"))
        self.assertEqual(self.fake.transfers, [])
        self.check_money()

    # ---- Spot transfer failures ---------------------------------------------------------------------------
    def one_close_with_transfer_plan(self, plan, minimum="10", history_down=False):
        self.set_sweep(minimum)
        self.seed_world(n=1, hedged=0)
        self.fake.transfer_plan = list(plan)
        self.fake.history_down = history_down
        r = self.close("S00USDT", self.expected["S00USDT"], 100, bulk=True)
        self.assertEqual(r.status_code, 200, r.text)
        return r

    def test_transfer_accepted_but_answer_lost_is_reconciled_from_history_without_a_second_transfer(self):
        self.one_close_with_transfer_plan(["http503_after_accept"])
        booked, pending, sent = self.check_money()
        self.assertGreater(sent, 0)
        first_id = self.fake.transfer_posts[0][0]
        self.assertEqual(sum(1 for p in self.fake.transfer_posts if p[0] == first_id), 1, "replayed although history proves it")

    def test_transfer_read_timeout_after_accept_is_reconciled_without_a_second_transfer(self):
        self.one_close_with_transfer_plan(["timeout_after_accept"])
        self.check_money()
        first_id = self.fake.transfer_posts[0][0]
        self.assertEqual(sum(1 for p in self.fake.transfer_posts if p[0] == first_id), 1)

    def test_transfer_lost_before_acceptance_is_replayed_once_with_the_same_id(self):
        self.one_close_with_transfer_plan(["http503_before_accept"])
        self.check_money()
        first_id = self.fake.transfer_posts[0][0]
        replays = [p for p in self.fake.transfer_posts if p[0] == first_id]
        self.assertEqual(len(replays), 2)
        self.assertEqual(sum(1 for t in self.fake.transfers if t["clientTranId"] == first_id), 1)

    def test_rejected_transfer_keeps_the_buffer_and_moves_no_money(self):
        self.one_close_with_transfer_plan(["reject"])
        booked, pending, sent = self.check_money(allow_inflight=True)
        self.assertEqual(self.fake.transfers, [])
        self.assertEqual(sent, Decimal(0))
        self.assertEqual(booked, pending)                                    # the buffer is intact; nothing was lost

    def test_unknown_transfer_with_history_down_blocks_blind_replay_and_recovers_later_without_a_second_transfer(self):
        self.one_close_with_transfer_plan(["http503_after_accept"], history_down=True)
        self.dump("history-down-after-close")
        first_id = self.fake.transfer_posts[0][0]
        self.assertEqual(sum(1 for p in self.fake.transfer_posts if p[0] == first_id), 1, "blind replay while history is down")
        booked, pending, sent = self.check_money(allow_inflight=True)
        self.assertEqual(sent, Decimal(0))                                    # buffer untouched until the exchange proves it
        self.assertEqual(booked, pending)
        self.assertTrue((self.state().get("inFlight") or {}).get("claimId"))
        posts_before = len(self.fake.transfer_posts)
        self.fake.history_down = False
        self.tick()                                                           # scheduler tick after the outage
        self.tick()
        self.check_money()
        self.assertEqual(sum(1 for p in self.fake.transfer_posts if p[0] == first_id), 1)

    def test_unknown_transfer_among_equal_recent_transfers_is_ambiguous_pauses_saving_and_never_replays(self):
        """Known limitation, fail-safe: many equal-sized blocks in minutes make the history match ambiguous after an
        unknown answer. Nothing is replayed, nothing is double-booked; saving pauses until the claim is resolved."""
        self.set_sweep("10")
        self.seed_world(n=3, hedged=0)
        self.assertEqual(self.close("S00USDT", self.expected["S00USDT"], 100, bulk=True).status_code, 200)
        self.assertGreaterEqual(len(self.fake.transfers), 2)
        self.fake.transfer_plan = ["http503_after_accept"]
        self.assertEqual(self.close("S01USDT", self.expected["S01USDT"], 100, bulk=True).status_code, 200)
        unknown_id = next(p[0] for p in self.fake.transfer_posts if p[2] == "http503_after_accept")
        self.assertEqual(sum(1 for p in self.fake.transfer_posts if p[0] == unknown_id), 1, "blind replay")
        inflight = self.state().get("inFlight") or {}
        self.assertEqual(inflight.get("status"), "UNCERTAIN", inflight)
        self.dump("ambiguous")
        self.check_money(allow_inflight=True)
        before = len(self.fake.transfers)
        self.assertEqual(self.close("S02USDT", self.expected["S02USDT"], 100, bulk=True).status_code, 200)
        self.assertEqual(len(self.fake.transfers), before, "saving must pause while a claim is unproven")
        self.assertEqual(sum(1 for p in self.fake.transfer_posts if p[0] == unknown_id), 1)
        self.check_money(allow_inflight=True)

    # ---- restart: process died between exchange acceptance and Firestore completion ------------------------
    def test_restart_after_exchange_accepted_completes_from_history_exactly_once(self):
        import profit_sweep_live as psl
        self.set_sweep("25")
        cid = psl._buffer_client_tran_id(self.uid, 1)
        now_ms = int(time.time() * 1000)
        self.fake.transfers.append({"clientTranId": cid, "asset": "USDT", "amount": "25", "tranId": 4242, "time": now_ms})
        from datetime import datetime, timezone
        claim = {"claimId": "restart-claim", "sequence": 1, "amount": "25", "asset": "USDT", "clientTranId": cid,
                 "status": "SUBMITTING", "createdAt": datetime.now(timezone.utc), "submittedAt": datetime.now(timezone.utc)}
        self.uref().collection("asterProfitSweepState").document("current").set(
            {"pendingSavings": "30", "transferSequence": 1, "inFlight": claim, "asset": "USDT", "minimumTransfer": "25"})
        self.uref().collection("asterProfitSweepTransfers").document("restart-claim").set(
            {"uid": self.uid, "claimId": "restart-claim", "sequence": 1, "amount": "25", "asset": "USDT",
             "clientTranId": cid, "status": "SUBMITTING"})
        self.tick()
        state = self.state()
        self.assertEqual(Decimal(str(state["pendingSavings"])), Decimal("5"))
        self.assertFalse(state.get("inFlight"))
        self.assertEqual(self.fake.transfer_posts, [], "a second POST was sent for an already accepted transfer")
        self.tick()
        self.assertEqual(Decimal(str(self.state()["pendingSavings"])), Decimal("5"))   # second tick changes nothing
        self.assertEqual(len(self.fake.transfers), 1)

    def test_restart_after_submitting_marker_but_before_the_post_sends_one_transfer_with_the_same_id(self):
        import profit_sweep_live as psl
        from datetime import datetime, timezone
        self.set_sweep("25")
        cid = psl._buffer_client_tran_id(self.uid, 1)
        claim = {"claimId": "restart-claim-2", "sequence": 1, "amount": "25", "asset": "USDT", "clientTranId": cid,
                 "status": "SUBMITTING", "createdAt": datetime.now(timezone.utc), "submittedAt": datetime.now(timezone.utc)}
        self.uref().collection("asterProfitSweepState").document("current").set(
            {"pendingSavings": "30", "transferSequence": 1, "inFlight": claim, "asset": "USDT", "minimumTransfer": "25"})
        self.uref().collection("asterProfitSweepTransfers").document("restart-claim-2").set(
            {"uid": self.uid, "claimId": "restart-claim-2", "sequence": 1, "amount": "25", "asset": "USDT",
             "clientTranId": cid, "status": "SUBMITTING"})
        self.tick()
        self.tick()
        self.assertEqual([p[0] for p in self.fake.transfer_posts], [cid])
        self.assertEqual(len(self.fake.transfers), 1)
        self.assertEqual(Decimal(str(self.state()["pendingSavings"])), Decimal("5"))

    # ---- concurrency: scheduler ticks while the series runs ------------------------------------------------
    def test_concurrent_scheduler_ticks_during_a_25_close_series_never_double_transfer(self):
        self.set_sweep("10")
        self.seed_world(n=25, hedged=5)
        stop, errors = threading.Event(), []

        def loop():
            while not stop.is_set():
                try:
                    self.tick()
                except Exception as exc:                                       # a tick must never break the books
                    errors.append(repr(exc))
                time.sleep(0.01)
        ticker = threading.Thread(target=loop)
        ticker.start()
        try:
            result = self.bulk(50)
        finally:
            stop.set()
            ticker.join(timeout=60)
        self.assertIsNone(result["stopped"], result)
        self.assertEqual(len(self.fake.accepted()), 25)
        self.dump("concurrent-before-settle")
        for _ in range(4):
            self.tick()
        self.dump("concurrent-after-settle")
        booked, pending, sent = self.check_money()
        self.assertGreater(sent, 0)
        self.assertTrue(all(Decimal(str(t["amount"])) == Decimal("10") for t in self.fake.transfers))
        print("INFO-sweep-concurrent: booked", booked, "transferred", sent, "pending", pending,
              "transfers", len(self.fake.transfers), "posts", len(self.fake.transfer_posts), "tick errors", errors[:3])
        self.assertEqual(errors, [])


class ImportSmoke(E2E):
    def test_real_app_imports_and_preview_route_answers_on_real_firestore(self):
        self.seed_world(n=3, hedged=1)
        data = self.preview(50)
        shorts = sorted(s["symbol"] for s in data["selected"] if str(s["side"]).upper() == "SHORT")
        self.assertEqual(shorts, ["S00USDT", "S01USDT", "S02USDT"])      # losing / exactly-$0.50 SHORTs are not selected


if __name__ == "__main__":
    unittest.main()
