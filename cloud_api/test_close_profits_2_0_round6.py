"""Close Profits 2.0 round 6 — exchange edge cases and lease expiry, model based.

Mocked: Firestore (in-memory model), Aster ledger + a controllable clock. REAL: the individual close route, the
manual-release helpers, the lease functions, the lock / dynamic-hedge guards and — in these tests — the REAL
aster_execution.execute_leg_once (single POST, fill confirmation, fail-closed on NEW/PARTIALLY_FILLED).
NOT real: Firestore, Aster, the Auto Hedge worker loop (modelled by a probe that follows its lease-first protocol).
Tests named KNOWN_RESIDUAL document behaviour that is NOT safe-by-proof; they exist so the risk stays visible."""
from __future__ import annotations

import re
import unittest
from datetime import timedelta
from pathlib import Path

import offline_close_harness as H
from test_close_profits_2_0_integration import Base, KEY, pair


class RealLeg(Base):
    def setUp(self, src=None):
        self.fs, real = self.make_store()
        self.L = H.Ledger(self.fs)
        self.route, self.ns, self.HTTP = H.build_backend(self.L, self.fs, src=src, real=real, real_leg=True)
        self.n = 0

    def world(self):
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        self.L.add("ETHUSDT", "SHORT", 5.0); self.L.add("ETHUSDT", "LONG", 5.0)
        self.L.add("SOLUSDT", "SHORT", 7.0)
        self.seed_pair("BTCUSDT", pair())
        self.before = dict(self.L.pos)

    def others_untouched(self):
        for k, v in self.before.items():
            if k[0] != "BTCUSDT" or k[1] == "LONG":
                self.assertEqual(self.L.pos[k], v, k)


class ExchangeEdgeCaseTests(RealLeg):
    def test_partial_fill_stops_with_one_order_and_never_a_second_market_order(self):
        self.world(); self.L.modes["BTCUSDT"] = "partial_fill"
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 50, key=KEY(1))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("er wordt niet opnieuw besteld", ctx.exception.detail)
        self.assertEqual(len(self.L.orders), 1)
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "MANUAL_RELEASE_UNCERTAIN")
        self.assertEqual(self.L.pos[("BTCUSDT", "SHORT")], 8.0 - 4.0 * 0.4)        # only the partial fill happened
        self.others_untouched(); self.assertTrue(self.lease_free())
        for key in (KEY(1), KEY(2)):                                              # same key / new key with the stale size
            with self.assertRaises(self.HTTP) as again:
                self.close("BTCUSDT", 8.0, 50, key=key)
            self.assertEqual(again.exception.status_code, 409)
        self.assertEqual(len(self.L.orders), 1)

    def test_exchange_reject_before_execution_leaves_everything_untouched(self):
        self.world(); self.L.modes["BTCUSDT"] = "reject_before"
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(self.L.orders, []); self.assertEqual(self.L.pos, self.before); self.assertTrue(self.lease_free())

    def test_timeout_after_accept_recovered_by_the_single_readonly_query_is_one_order(self):
        self.world(); self.L.modes["BTCUSDT"] = "timeout_after_accept"
        out = self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(len(self.L.orders), 1)
        self.assertEqual(out["remainingSize"], 6.0)
        self.others_untouched()

    def test_timeout_after_accept_with_failing_query_is_unknown_and_stops(self):
        self.world(); self.L.modes["BTCUSDT"] = "timeout_after_accept"; self.L.query_fails.add("BTCUSDT")
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25, key=KEY(1))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(len(self.L.orders), 1)
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "MANUAL_RELEASE_UNCERTAIN")
        with self.assertRaises(self.HTTP):
            self.close("BTCUSDT", 8.0, 25, key=KEY(1))                            # replay: refused, no second order
        self.assertEqual(len(self.L.orders), 1); self.others_untouched()

    def test_order_ack_without_final_fill_new_status_is_unknown_not_a_new_order(self):
        self.world(); self.L.modes["BTCUSDT"] = "ack_new"
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(len(self.L.orders), 1); self.others_untouched()

    def test_order_ack_new_then_confirmed_filled_by_the_readonly_query_is_one_order(self):
        self.world(); self.L.modes["BTCUSDT"] = "ack_new_then_filled"
        out = self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(len(self.L.orders), 1); self.assertEqual(out["remainingSize"], 6.0)

    def test_delayed_position_reflection_is_not_confirmed_and_stops_without_second_order(self):
        self.world(); self.L.reflection_lag["BTCUSDT"] = 1                        # next position read still shows the old size
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25, key=KEY(1))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("niet opnieuw besteld", ctx.exception.detail)
        self.assertEqual(len(self.L.orders), 1)
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "MANUAL_RELEASE_UNCERTAIN")
        with self.assertRaises(self.HTTP):
            self.close("BTCUSDT", 8.0, 25, key=KEY(1))                            # same key: idempotent refusal
        self.assertEqual(len(self.L.orders), 1)

    def test_KNOWN_RESIDUAL_manual_click_with_new_key_while_exchange_still_shows_old_size_can_order_again(self):
        """Pre-existing behaviour of the individual route (not reachable from the green button, which stops on 502):
        while Aster's position endpoint still shows the OLD size, a human clicking again with a NEW key passes the
        expected_quantity check. Documented, not fixed (route must stay unchanged)."""
        self.world(); self.L.reflection_lag["BTCUSDT"] = 4
        with self.assertRaises(self.HTTP):
            self.close("BTCUSDT", 8.0, 25, key=KEY(1))
        self.close("BTCUSDT", 8.0, 25, key=KEY(2))
        self.assertEqual(len(self.L.orders), 2)              # measured: the second click DOES place a second MARKET close
        self.assertEqual(self.L.pos[("BTCUSDT", "SHORT")], 4.0)   # 8 -> 6 -> 4: 25% of the stale displayed 8, twice

    def test_series_stops_at_the_first_unknown_and_other_shorts_are_never_touched(self):
        self.world(); self.L.modes["ETHUSDT"] = "partial_fill"
        sent = []
        for sym, qty in (("BTCUSDT", 8.0), ("ETHUSDT", 5.0), ("SOLUSDT", 7.0)):      # what the frontend loop does
            try:
                self.close(sym, qty, 50); sent.append((sym, "ok"))
            except self.HTTP:
                sent.append((sym, "stop")); break
        self.assertEqual(sent, [("BTCUSDT", "ok"), ("ETHUSDT", "stop")])
        self.assertEqual(self.L.pos[("SOLUSDT", "SHORT")], 7.0)
        self.assertEqual(self.L.pos[("ETHUSDT", "LONG")], 5.0); self.assertEqual(self.L.pos[("BTCUSDT", "LONG")], 8.0)


class LeaseExpiryTests(RealLeg):
    def worker_acquires(self, store):
        token = self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "POSITION_LOSS_EXACT_1_TO_1")
        store.append(token)
        return token

    def test_lease_expired_during_a_late_response_worker_may_take_it_but_cannot_rehedge_the_frozen_pair(self):
        self.world(); self.L.modes["BTCUSDT"] = "late_response"                   # response arrives 60 s late > 45 s TTL
        worker, seen = [], {}
        reads = {"n": 0}

        def on_read():
            reads["n"] += 1
            if reads["n"] == 3 and not worker:                                     # the read AFTER the late order
                self.worker_acquires(worker)
                seen["pair"] = dict(self.pair_doc("BTCUSDT"))
        self.L.on_before_read = on_read
        out = self.close("BTCUSDT", 8.0, 25)
        self.assertTrue(worker and worker[0])                                      # FACT: lease can be taken after expiry
        self.assertIn(seen["pair"]["status"], {"MANUAL_RELEASE_PENDING"})          # ... but the pair is frozen,
        self.assertFalse(seen["pair"]["rehedgeEnabled"])                           # re-hedge is OFF while pending
        self.assertEqual(len(self.L.orders), 1)
        self.assertEqual(out["remainingSize"], 6.0)
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "RECOVERY")
        lease = (self.get("asterAccountCoordination", self.uid) or {}).get("lease") or {}
        self.assertEqual(lease.get("token"), worker[0])                            # route's release did NOT clobber the worker's lease
        self.others_untouched()

    def test_lease_expiring_during_the_exchange_reread_is_refused_before_any_freeze_or_order(self):
        """Was a model of the pre-release route (pair frozen after the worker created it). The release renews OUR lease
        before the freeze and refuses (409, nothing frozen or ordered) when it had already expired."""
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": True})
        done = {"v": False}
        calls = {"n": 0}

        def on_read():
            calls["n"] += 1
            if calls["n"] == 2 and not done["v"]:                                 # the re-read under the lease is slow (50 s)
                done["v"] = True
                self.ns.clock.offset += timedelta(seconds=50)
                token = self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "x")
                self.assertTrue(token)
                self.seed_pair("BTCUSDT", pair())                                  # worker creates the pair after expiry
                self.ns._release_aster_account_coordination(self.uid, token)
        self.L.on_before_read = on_read
        with self.assertRaises(self.HTTP) as ctx:
            self.close("BTCUSDT", 8.0, 25)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("account-lease is verlopen", ctx.exception.detail)
        self.assertEqual(self.L.orders, [])
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "HEDGED")             # nothing frozen, the worker's pair untouched

    def test_KNOWN_RESIDUAL_plain_short_pair_created_after_lease_expiry_while_the_order_is_in_flight(self):
        """Only reachable if the exchange POST (or a Firestore stall) outlives the 45 s lease: the worker then creates
        the pair AFTER the route's last pair read, so the close is not frozen. Needs >45 s; Aster calls time out at
        15 s per phase. Not fixed (no lease renewal / TTL change without proven necessity) -> production NO-GO stays."""
        self.L.add("BTCUSDT", "SHORT", 8.0); self.L.add("BTCUSDT", "LONG", 8.0)
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": True})
        self.L.modes["BTCUSDT"] = "late_response"
        state = {"n": 0}

        def on_before_order(sym):
            token = self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "x")
            self.assertIsNone(token)                                               # lease still valid at the moment of ordering
        self.L.on_before_order = on_before_order
        reads = {"n": 0}

        def on_read():
            reads["n"] += 1
            if reads["n"] == 3:                                                    # after the late response (lease expired)
                token = self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "x")
                if token:
                    self.seed_pair("BTCUSDT", pair())
                    self.ns._release_aster_account_coordination(self.uid, token)
                    state["pair_created_late"] = True
        self.L.on_before_read = on_read
        self.close("BTCUSDT", 8.0, 25)
        self.assertTrue(state.get("pair_created_late"))
        self.assertEqual(self.pair_doc("BTCUSDT")["status"], "HEDGED")             # NOT frozen: the residual, made visible
        self.assertEqual(len(self.L.orders), 1)                                    # but still exactly one close order


class ClockModelTests(RealLeg):
    def test_injected_datetime_accepts_foreign_datetime_subclasses_like_firestore_timestamps(self):
        from datetime import datetime, timezone

        class DatetimeWithNanoseconds(datetime):
            pass
        foreign = DatetimeWithNanoseconds(2030, 1, 1, tzinfo=timezone.utc)
        self.assertIsInstance(foreign, self.ns.datetime)
        self.put("asterAccountCoordination", self.uid, {"lease": {"token": "x", "until": foreign}})
        self.assertIsNone(self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "x"))   # still held


class WorkerStatusSourceTests(unittest.TestCase):
    SRC = (Path(__file__).parent / "aster_position_loss_auto_hedge_extension.py").read_text()

    def sets(self, name):
        m = re.search(name + r" = \{([^}]*)\}", self.SRC)
        return set(re.findall(r'"([A-Z_]+)"', m.group(1)))

    def test_manual_release_states_are_recovery_states_the_worker_never_treats_as_active_or_rehedgeable(self):
        recovery, active, rehedgeable = self.sets("RECOVERY_STATUSES"), self.sets("ACTIVE_STATUSES"), self.sets("REHEDGEABLE_STATUSES")
        for status in ("MANUAL_RELEASE_PENDING", "MANUAL_RELEASE_UNCERTAIN"):
            self.assertIn(status, recovery)
            self.assertNotIn(status, active)
            self.assertNotIn(status, rehedgeable)

    def test_begin_release_turns_rehedge_off_before_the_order(self):
        src = (Path(__file__).parent / "main.py").read_text()
        body = src[src.index("def _begin_position_loss_auto_hedge_manual_release"):src.index("def _complete_position_loss_auto_hedge_manual_release")]
        self.assertIn('"rehedgeEnabled": False', body.replace("False,", "False,"))
        self.assertIn("MANUAL_RELEASE_PENDING", body)


if __name__ == "__main__":
    unittest.main()
