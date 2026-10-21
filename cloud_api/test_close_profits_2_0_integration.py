"""Close Profits 2.0 — offline model-based integration tests of the REAL individual close route.

Mocked: Firestore (in-memory model), Aster (ledger). Real: route + manual-release helpers + lease functions + lock /
dynamic-hedge guards + ContractRules + close_size (source extracted from main.py). Needs the `httpx` import of
aster_gateway (a stub is enough offline). These are NOT real-infrastructure proofs."""
from __future__ import annotations

import threading
import unittest
from pathlib import Path

try:
    import offline_close_harness as H
    HAVE = True
except Exception:  # pragma: no cover  (aster_gateway needs httpx)
    HAVE = False

KEY = lambda n: f"idempotency-key-{n:08d}"
MAIN_SRC = (Path(__file__).parent / "main.py").read_text()


def pair(status="HEDGED", protected="LONG", hedge="SHORT", **extra):
    return {"status": status, "protectedSide": protected, "hedgeSide": hedge, "rehedgeEnabled": True,
            "reservedHedgeQty": 0.0, "generationId": "g1", **extra}


@unittest.skipUnless(HAVE, "needs aster_gateway (httpx)")
class Base(unittest.TestCase):
    def setUp(self, src=None):
        self.fs = H.FakeFirestore()
        self.L = H.Ledger(self.fs)
        self.route, self.ns, self.HTTP = H.build_backend(self.L, self.fs, src=src)
        self.n = 0

    def close(self, symbol, qty, pct, key=None):
        self.n += 1
        return self.route(symbol.lower(), H.request(qty, percentage=pct, key=key or KEY(self.n)), {"uid": "u1"})

    def pair_doc(self, symbol):
        return self.fs.docs.get(("asterPositionLossAutoHedge", "u1", "pairs", symbol))

    def lease_free(self):
        lease = (self.fs.docs.get(("asterAccountCoordination", "u1")) or {}).get("lease") or {}
        return not lease.get("token")

    def seed_pair(self, symbol, doc):
        self.fs.docs[("asterPositionLossAutoHedge", "u1", "pairs", symbol)] = doc


class SequentialBulkTests(Base):
    def test_25_profitable_shorts_all_percentages_only_shorts_exact_sizes(self):
        expected_fraction = {25: .25, 50: .5, 75: .75, 100: 1.0}
        for pct, fraction in expected_fraction.items():
            self.setUp()
            symbols = [f"C{i:02d}USDT" for i in range(25)]
            for i, s in enumerate(symbols):
                self.L.add(s, "SHORT", 8.0 + i, mark=100.0)
                self.L.add(s, "LONG", 5.0, mark=100.0)           # hedged symbols: LONGs must never be touched
            before_long = {s: self.L.pos[(s, "LONG")] for s in symbols}
            for i, s in enumerate(symbols):
                self.close(s, 8.0 + i, pct)
            self.assertEqual(len(self.L.orders), 25)             # exactly one order per SHORT
            for (sym, side, qty, _), i in zip(self.L.orders, range(25)):
                self.assertEqual(side, "SHORT")
                self.assertAlmostEqual(qty, (8.0 + i) * fraction, places=6)
            self.assertEqual({s: self.L.pos[(s, "LONG")] for s in symbols}, before_long)
            self.assertTrue(self.lease_free())

    def test_auto_hedge_shorts_are_closed_with_the_existing_recovery_transition_unchanged(self):
        for pct in (25, 50, 75, 100):
            self.setUp()
            self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
            self.seed_pair("BTCUSDT", pair())
            result = self.close("BTCUSDT", 8.0, pct)
            doc = self.pair_doc("BTCUSDT")
            self.assertEqual(doc["status"], "RECOVERY")                      # existing manual behaviour
            self.assertFalse(doc["rehedgeEnabled"])
            self.assertEqual(doc["hedgeSide"], "LONG")
            self.assertEqual(self.L.pos[("BTCUSDT", "LONG")], 8.0)           # LONG untouched
            self.assertEqual(result["autoHedgeStatus"], "RECOVERY")
            self.assertTrue(self.lease_free())

    def test_auto_hedge_hedge_leg_with_reserved_quantity_is_still_closable_like_the_manual_button(self):
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        self.seed_pair("BTCUSDT", pair(reservedHedgeQty=8.0, currentHedgeQty=8.0, normalFreeQty=0.0))
        self.close("BTCUSDT", 8.0, 25)                                       # same as a manual click: freeze -> order
        self.assertEqual(len(self.L.orders), 1)
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "RECOVERY")

    def test_bulk_equals_individual_clicks_same_end_state(self):
        def run(sym_list):
            self.setUp()
            for s in sym_list:
                self.L.add(s, "SHORT", 10.0); self.L.add(s, "LONG", 10.0); self.seed_pair(s, pair())
            for s in sym_list:
                self.close(s, 10.0, 50)
            strip = lambda d: {k: v for k, v in d.items() if k not in ("updatedAt", "recoveryAt", "manualRelease", "protectedLeg", "hedgeLeg")}
            return ({s: strip(self.pair_doc(s)) for s in sym_list}, dict(self.L.pos))
        a = run(["AAAUSDT", "BBBUSDT"])
        b = run(["BBBUSDT", "AAAUSDT"])          # order of clicks does not matter: same per-position semantics
        self.assertEqual(a, b)

    def test_minimum_order_error_skips_without_order_or_freeze_and_series_continues(self):
        self.L.add("TINYUSDT", "SHORT", 0.002, minimum=0.001, step=0.001)
        self.L.add("BTCUSDT", "SHORT", 8.0)
        self.seed_pair("TINYUSDT", pair())
        with self.assertRaises(self.HTTP) as ctx:
            self.close("TINYUSDT", 0.002, 25)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertRegex(ctx.exception.detail, r"contractregels: (Order ligt onder de minimale Aster-(hoeveelheid|orderwaarde)|Hoeveelheid en marktprijs moeten positief zijn)$")
        self.assertEqual(self.L.orders, [])
        self.assertEqual(self.pair_doc("TINYUSDT")["status"], "HEDGED")    # NOT frozen/changed by a skipped position
        self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(len(self.L.orders), 1)

    def test_changed_quantity_between_snapshot_and_close_is_refused_without_order(self):
        self.L.add("BTCUSDT", "SHORT", 8.0)
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 7.0, 25)                                  # snapshot said 7, exchange has 8
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.L.orders, [])

    def test_missing_position_is_refused_and_long_is_never_substituted(self):
        self.L.add("BTCUSDT", "LONG", 8.0)
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.L.orders, [])
        self.assertEqual(self.L.pos[("BTCUSDT", "LONG")], 8.0)


class UnknownOutcomeTests(Base):
    def test_unknown_after_accept_one_order_fail_closed_no_retry_and_no_blind_release(self):
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        self.seed_pair("BTCUSDT", pair())
        self.L.modes["BTCUSDT"] = "drop_after_accept"
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25, key=KEY(1))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("er wordt niet opnieuw besteld", ctx.exception.detail)
        self.assertEqual(len(self.L.orders), 1)
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "MANUAL_RELEASE_UNCERTAIN")   # existing fail-closed state
        self.assertTrue(self.lease_free())
        # same click replayed (e.g. refresh/retry): idempotency refuses, no second MARKET order
        with self.assertRaises(self.HTTP) as again:
            self.close("BTCUSDT", 8.0, 25, key=KEY(1))
        self.assertEqual(again.exception.status_code, 409)
        self.assertEqual(len(self.L.orders), 1)
        # a fresh key with the old snapshot quantity: the exchange already moved -> stale quantity refusal
        with self.assertRaises(self.HTTP) as stale:
            self.close("BTCUSDT", 8.0, 25, key=KEY(2))
        self.assertEqual(stale.exception.status_code, 409)
        self.assertEqual(len(self.L.orders), 1)

    def test_exchange_reject_before_accept_places_no_order(self):
        self.L.add("BTCUSDT", "SHORT", 8.0)
        self.L.modes["BTCUSDT"] = "reject_before"
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(self.L.orders, [])

    def test_duplicate_click_same_key_places_exactly_one_order(self):
        self.L.add("BTCUSDT", "SHORT", 8.0)
        self.close("BTCUSDT", 8.0, 25, key=KEY(7))
        with self.assertRaises(self.HTTP):
            self.close("BTCUSDT", 8.0, 25, key=KEY(7))
        self.assertEqual(len(self.L.orders), 1)

    def test_lock_state_unreadable_fails_closed_before_any_order(self):
        import aster_position_loss_auto_hedge_lock as lock
        self.L.add("BTCUSDT", "SHORT", 8.0)
        lock.configure_auto_hedge_lock_reader(lambda u, s: (_ for _ in ()).throw(RuntimeError("boom")))
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.L.orders, [])


class AutoHedgeConcurrencyTests(Base):
    def test_worker_cannot_take_the_account_lease_while_the_manual_close_orders(self):
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        self.seed_pair("BTCUSDT", pair())
        seen = {}
        self.L.on_before_order = lambda sym: seen.setdefault(
            "worker", self.ns._acquire_aster_account_coordination("u1", "AUTO_HEDGE", "POSITION_LOSS_EXACT_1_TO_1"))
        self.close("BTCUSDT", 8.0, 25)
        self.assertIsNone(seen["worker"])                                    # worker is deferred during the close
        self.assertTrue(self.ns._acquire_aster_account_coordination("u1", "AUTO_HEDGE", "x"))   # free afterwards

    def test_busy_lease_refuses_before_freeze_and_order(self):
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        self.seed_pair("BTCUSDT", pair())
        self.assertTrue(self.ns._acquire_aster_account_coordination("u1", "AUTO_HEDGE", "x"))   # worker holds it
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Auto Hedge verwerkt momenteel dezelfde accountstatus", ctx.exception.detail)
        self.assertEqual(self.L.orders, [])
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "HEDGED")       # nothing frozen

    def test_worker_changes_quantity_between_first_read_and_lease_is_caught_by_reread(self):
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        self.seed_pair("BTCUSDT", pair())
        reads = []

        def worker_between_reads():
            reads.append(1)
            if len(reads) == 2:                          # the re-read under the lease: worker already changed the hedge
                self.L.pos[("BTCUSDT", "SHORT")] = 9.0
        self.L.on_before_read = worker_between_reads
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("positiegrootte is gewijzigd", ctx.exception.detail)
        self.assertEqual(self.L.orders, [])
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "HEDGED")       # not frozen, no wrong-size order, no UNCERTAIN
        self.assertTrue(self.lease_free())

    def test_mutation_without_reread_the_same_race_ends_in_wrong_size_order_and_uncertain_state(self):
        marker = "            live_rows = client.position_risk()\n            fresh = next("
        self.assertIn(marker, MAIN_SRC)
        start = MAIN_SRC.index("            # Positions were read before the lease")
        end = MAIN_SRC.index("            auto_hedge_manual_guard = _begin_position_loss_auto_hedge_manual_release(")
        self.setUp(src=MAIN_SRC[:start] + MAIN_SRC[end:])                     # route as it was before this change
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        self.seed_pair("BTCUSDT", pair())
        calls = []

        def worker():
            calls.append(1)
        self.L.on_before_read = worker
        self.L.on_before_order = lambda sym: None
        # worker acts after our first read but before the lease: SHORT 8 -> 9 (re-hedge top-up)
        original_acquire = self.ns._acquire_aster_account_coordination

        def acquire_after_worker(*a, **k):
            self.L.pos[("BTCUSDT", "SHORT")] = 9.0
            return original_acquire(*a, **k)
        self.route.__globals__["_acquire_aster_account_coordination"] = acquire_after_worker
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(ctx.exception.status_code, 502)                      # order WAS sent, outcome mismatched
        self.assertEqual(len(self.L.orders), 1)
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "MANUAL_RELEASE_UNCERTAIN")


@unittest.skipUnless(HAVE, "needs aster_gateway (httpx)")
class WorkerLeaseOrderSourceTests(unittest.TestCase):
    def test_worker_takes_the_lease_before_reading_positions_or_mutating_pair_state(self):
        src = (Path(__file__).parent / "aster_position_loss_auto_hedge_extension.py").read_text()
        body = src[src.index("def _run_uid("):]
        body = body[:body.index("\n@main.app.get(")]
        acquire = body.index("main._acquire_aster_account_coordination(")
        self.assertEqual(body.count("main._acquire_aster_account_coordination("), 1)
        for later in ("_client(uid, live=execute)", "client.position_risk()", "_prepare_lifecycle(", "reconcile_auto_hedge("):
            self.assertLess(acquire, body.index(later), later)
        self.assertIn("main._release_aster_account_coordination(uid, coordination_token)", body.split("finally:")[-1])

    def test_busy_lease_returns_pending_before_any_state_change(self):
        src = (Path(__file__).parent / "aster_position_loss_auto_hedge_extension.py").read_text()
        body = src[src.index("def _run_uid("):]
        busy = body.index('"reason": "ACCOUNT_COORDINATION_BUSY"')
        self.assertLess(busy, body.index("_prepare_lifecycle("))


if __name__ == "__main__":
    unittest.main()
