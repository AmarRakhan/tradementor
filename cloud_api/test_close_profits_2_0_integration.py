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
    EMULATOR = False

    def make_store(self):
        """In-memory Firestore MODEL (default). EmulatorMixin swaps in a real Firestore client."""
        self.uid = "u1"
        return H.FakeFirestore(), None

    def setUp(self, src=None):
        self.fs, real = self.make_store()
        self.L = H.Ledger(self.fs)
        self.route, self.ns, self.HTTP = H.build_backend(self.L, self.fs, src=src, real=real)
        self.n = 0

    # --- store access that works for both the model and a real Firestore -------------------------------
    def get(self, *path):
        if self.EMULATOR:
            snap = self.fs.document("/".join(path)).get()
            return snap.to_dict() if snap.exists else None
        return self.fs.docs.get(path)

    def put(self, *path_and_data):
        *path, data = path_and_data
        if self.EMULATOR:
            self.fs.document("/".join(path)).set(data)
        else:
            self.fs.docs[tuple(path)] = data

    def close(self, symbol, qty, pct, key=None):
        self.n += 1
        return self.route(symbol.lower(), H.request(qty, percentage=pct, key=key or KEY(self.n)), {"uid": self.uid})

    def pair_doc(self, symbol):
        return self.get("asterPositionLossAutoHedge", self.uid, "pairs", symbol)

    def lease_free(self):
        lease = (self.get("asterAccountCoordination", self.uid) or {}).get("lease") or {}
        return not lease.get("token")

    def seed_pair(self, symbol, doc):
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", symbol, doc)


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
            "worker", self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "POSITION_LOSS_EXACT_1_TO_1"))
        self.close("BTCUSDT", 8.0, 25)
        self.assertIsNone(seen["worker"])                                    # worker is deferred during the close
        self.assertTrue(self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "x"))   # free afterwards

    def test_busy_lease_refuses_before_freeze_and_order(self):
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        self.seed_pair("BTCUSDT", pair())
        self.assertTrue(self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "x"))   # worker holds it
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
        start = MAIN_SRC.index("            # Positions and pair were read before the lease")
        end = MAIN_SRC.index("            pair_before_close = _position_loss_auto_hedge_pair(uid, normalized_symbol)\n            # The reads above can be slow")
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


class PlainShortBecomesAutoHedgeTests(Base):
    """A plain SHORT whose same-symbol LONG crosses the Auto Hedge loss threshold between selection and close."""

    def worker_creates_pair(self):
        token = self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "POSITION_LOSS_EXACT_1_TO_1")
        self.assertTrue(token)                                                   # worker follows the lease-first protocol
        self.seed_pair("BTCUSDT", pair())                                        # pair created: SHORT is now the hedge leg
        self.ns._release_aster_account_coordination(self.uid, token)

    def enable_auto_hedge(self, enabled=True):
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": enabled})

    def race(self):
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        original = self.ns._position_loss_auto_hedge_pair
        fired = []

        def read_then_worker(uid, symbol):
            value = original(uid, symbol)
            if not fired:
                fired.append(1)
                self.worker_creates_pair()                                       # worker acts right after the route's first read
            return value
        self.route.__globals__["_position_loss_auto_hedge_pair"] = read_then_worker

    def test_pair_created_between_pair_read_and_order_is_frozen_like_a_manual_release(self):
        self.enable_auto_hedge()
        self.race()
        self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "RECOVERY")         # existing manual semantics, not a re-hedgeable HEDGED
        self.assertFalse(self.pair_doc("BTCUSDT")["rehedgeEnabled"])
        self.assertEqual(len(self.L.orders), 1)
        self.assertTrue(self.lease_free())

    def test_worker_cannot_create_the_pair_while_the_close_is_ordering(self):
        self.enable_auto_hedge()
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        got = {}
        self.L.on_before_order = lambda sym: got.setdefault(
            "token", self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "x"))
        self.close("BTCUSDT", 8.0, 25)
        self.assertIsNone(got["token"])

    def test_auto_hedge_disabled_keeps_the_original_lease_free_individual_close(self):
        self.enable_auto_hedge(False)
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        taken = []
        self.L.on_before_order = lambda sym: taken.append(self.lease_free())
        self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(taken, [True])                                          # no lease: identical to the old manual path

    def test_lone_short_without_opposite_leg_takes_no_lease(self):
        self.enable_auto_hedge()
        self.L.add("BTCUSDT", "SHORT", 8.0)
        taken = []
        self.L.on_before_order = lambda sym: taken.append(self.lease_free())
        self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(taken, [True])

    def test_settings_unreadable_is_treated_as_enabled_fail_safe(self):
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        real_db = self.route.__globals__["db"]

        class BrokenDoc:
            def __init__(self_inner, doc): self_inner.doc = doc
            def get(self_inner, *a, **k): raise RuntimeError("firestore down")      # settings read fails ...
            def collection(self_inner, name): return self_inner.doc.collection(name)   # ... pair sub-collection still works

        class BrokenCol:
            def __init__(self_inner, col): self_inner.col = col
            def document(self_inner, doc_id): return BrokenDoc(self_inner.col.document(doc_id))

        class Broken:
            def collection(self_inner, name):
                col = real_db.collection(name)
                return BrokenCol(col) if name == "asterPositionLossAutoHedge" else col
            def transaction(self_inner):
                return real_db.transaction()
        self.route.__globals__["db"] = Broken()
        taken = []
        self.L.on_before_order = lambda sym: taken.append(self.lease_free())
        try:
            self.close("BTCUSDT", 8.0, 25)
        except Exception:
            pass
        self.route.__globals__["db"] = real_db
        self.assertEqual(taken, [False])                                         # lease held although settings unreadable


class RetrySafetyProofTests(unittest.TestCase):
    """The frontend retries ONLY the exact 'account busy' message. Prove that message can only be produced
    before any freeze, manual-action lock or order, and that no other route text can equal it."""
    MSG = "Auto Hedge verwerkt momenteel dezelfde accountstatus; probeer de sluiting zo opnieuw"

    def test_message_has_one_raise_site_before_any_state_change_or_order(self):
        self.assertEqual(MAIN_SRC.count(self.MSG), 1)
        route = MAIN_SRC[MAIN_SRC.index("def close_one_aster_position("):]
        route = route[:route.index('@app.post("/v1/me/aster/simulate")')]
        site = route.index(self.MSG)
        for later in ("_begin_position_loss_auto_hedge_manual_release(", "require_auto_hedge_close_allowed(",
                      "begin_manual_action(", "execute_aster_leg(", "complete_manual_action("):
            self.assertLess(site, route.index(later), later)
        # the handler ahead of it is `except HTTPException`: guard is None there, so nothing is marked uncertain
        self.assertLess(route.index("auto_hedge_manual_guard = None"), site)

    def test_frontend_matches_only_the_full_exact_message(self):
        # Close Profits 2.1: the busy retry moved from the browser loop to the server round engine. It still matches
        # ONLY the two exact pre-order texts (set membership = exact equality), at most MAX_BUSY_RETRIES times, and the
        # browser no longer classifies route messages at all.
        import profit_close_rounds as rounds
        lease_msg = "De account-lease is verlopen voordat de sluiting kon starten; er is niets geplaatst, probeer opnieuw"
        self.assertEqual(rounds._BUSY, {self.MSG, lease_msg})
        self.assertEqual(rounds.MAX_BUSY_RETRIES, 3)
        engine = (Path(__file__).parent / "profit_close_rounds.py").read_text()
        self.assertEqual(engine.count("if detail in _BUSY:"), 1)
        source = (Path(__file__).parent.parent / "web/components/aster-recent-trades.tsx").read_text()
        self.assertNotIn(self.MSG, source)
        self.assertNotIn("busyRetries", source)

    def test_release_guards_run_before_any_freeze_or_order(self):
        route = (Path(__file__).parent / "main.py").read_text()
        route = route[route.index('def close_one_aster_position('):]
        route = route[:route.index('@app.post("/v1/me/aster/simulate")')]
        order = route.index("execute_aster_leg(")
        freeze = route.index("_begin_position_loss_auto_hedge_manual_release(")
        for needle in ("_refuse_if_recent_close_unconfirmed(", "_enforce_min_open_pnl(position, request)",
                       "_enforce_min_open_pnl(fresh, request)", "_renew_aster_account_coordination("):
            self.assertLess(route.index(needle), freeze, needle)
        self.assertLess(route.index('"orderMayHaveBeenSent": True'), order)      # durable marker precedes the single order
        self.assertEqual(route.count("execute_aster_leg("), 1)                    # still exactly one order call site

    def test_new_close_profits_code_needs_no_firestore_index(self):
        """Only get-by-id, plain collection listing and writes: no filtered/ordered query, no collection-group query,
        so there is nothing that could need a composite (or any non-automatic) index in production."""
        root = Path(__file__).parent
        main_src = (root / "main.py").read_text()
        route = main_src[main_src.index("def _series_guard_intents("):]
        route = route[:route.index('@app.post("/v1/me/aster/simulate")')]
        parts = {"route": route}
        for name in ("manual_profit_close_planner.py", "manual_profit_close_snapshot.py"):
            parts[name] = (root / name).read_text()
        for name, text in parts.items():
            for forbidden in (".where(", ".order_by(", "collection_group(", ".start_after(", ".limit("):
                self.assertNotIn(forbidden, text, f"{name} uses {forbidden}")


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
