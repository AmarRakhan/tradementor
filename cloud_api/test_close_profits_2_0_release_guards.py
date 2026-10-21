"""Close Profits 2.0 release guards, on the REAL stack (FastAPI app + Firestore emulator + gateway + HTTP-fake Aster):
 1. server-side open-profit check right before the order (green series only; plain manual Close unchanged),
 2. the series skips a symbol whose earlier close may have been sent but is unconfirmed (delayed position data),
 3. the account lease is renewed before the pair freeze, and a lease that already expired is NOT used."""
from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone

import test_close_profits_2_0_e2e_stack as base

setUpModule = base.setUpModule
tearDownModule = base.tearDownModule
S = base.S

PNL_GONE = "Open winst is niet meer boven de ingestelde grens; geen order geplaatst"
UNCONFIRMED = "Vorige sluiting van dit symbool is nog niet bevestigd; controleer Aster en gebruik de individuele Close-knop"
LEASE = "De account-lease is verlopen voordat de sluiting kon starten; er is niets geplaatst, probeer opnieuw"


class ProfitGuard(base.E2E):
    def intent_statuses(self):
        docs = self.db.collection("users").document(self.uid).collection("asterManualCloseIntents").stream()
        return [d.to_dict() for d in docs]

    def test_profit_at_or_below_the_limit_is_refused_without_any_order(self):
        self.seed_world(n=3, hedged=0)
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": False})
        for sym in ("EDGEUSDT", "LOSSUSDT"):                      # exactly $0.50, and a loss
            r = self.close(sym, 10.0, 50, bulk=True)
            self.assertEqual((r.status_code, r.json()["detail"]), (409, PNL_GONE), sym)
        self.assertEqual(self.fake.accepted(), [])
        self.assertEqual(self.fake.pos[("EDGEUSDT", "SHORT")], 10.0)

    def test_profit_that_drops_after_the_fresh_check_is_caught_before_the_order(self):
        self.seed_world(n=3, hedged=0)
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": False})
        fresh = self.preview(50)
        self.assertIn("S01USDT", [s["symbol"] for s in fresh["selected"]])        # the frontend's fresh check passes
        self.fake.mark["S01USDT"] = 105.0                                           # then the price moves: profit is 0
        r = self.close("S01USDT", self.expected["S01USDT"], 50, bulk=True)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, PNL_GONE))
        self.assertEqual(self.fake.accepted(), [])
        self.assertEqual(self.fake.pos[("S01USDT", "SHORT")], self.expected["S01USDT"])
        self.assertEqual([i.get("status") for i in self.intent_statuses()], ["failed_closed"])
        self.assertFalse(any(i.get("orderMayHaveBeenSent") for i in self.intent_statuses()))

    def test_unreadable_profit_fails_closed(self):
        self.seed_world(n=3, hedged=0)
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": False})
        original = S.fake._position_rows

        def broken():
            rows = original()
            for row in rows:
                if row["symbol"] == "S01USDT":
                    row["unRealizedProfit"] = "NaN"
            return rows
        S.fake._position_rows = broken
        try:
            r = self.close("S01USDT", self.expected["S01USDT"], 50, bulk=True)
        finally:
            S.fake._position_rows = original
        self.assertEqual(r.status_code, 409)
        self.assertIn("niet betrouwbaar leesbaar", r.json()["detail"])
        self.assertEqual(self.fake.accepted(), [])

    def test_plain_manual_close_is_unchanged_without_the_series_fields(self):
        self.seed_world(n=3, hedged=0)
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": False})
        r = self.close("EDGEUSDT", 10.0, 50)                                        # profit exactly $0.50: allowed manually
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.fake.accepted(symbol="EDGEUSDT")), 1)

    def test_profit_that_drops_inside_the_lease_window_of_an_auto_hedge_short_is_caught(self):
        self.seed_world(n=3, hedged=3)
        reads = {"n": 0}

        def hook():
            reads["n"] += 1
            if reads["n"] == 2:                                                      # the re-read UNDER the lease
                self.fake.mark["S00USDT"] = 105.0
        self.fake.on_position_read = hook
        r = self.close("S00USDT", self.expected["S00USDT"], 50, bulk=True)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, PNL_GONE), r.text)
        self.assertEqual(self.fake.accepted(), [])
        self.assertEqual(self.pair("S00USDT")["status"], "HEDGED")                  # nothing was frozen
        lease = (self.db.collection("asterAccountCoordination").document(self.uid).get().to_dict() or {}).get("lease") or {}
        self.assertFalse(lease.get("token"))                                         # lease released


class SeriesLock(base.E2E):
    def test_unconfirmed_earlier_close_makes_the_series_skip_that_symbol_without_an_order(self):
        self.seed_world(n=3, hedged=0)
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": False})
        self.fake.lag["S00USDT"] = 3                                                 # Aster keeps showing the OLD size
        first = self.close("S00USDT", self.expected["S00USDT"], 50, bulk=True)
        self.assertEqual(first.status_code, 502)
        self.assertEqual(len(self.fake.accepted(symbol="S00USDT")), 1)
        second = self.close("S00USDT", self.expected["S00USDT"], 50, bulk=True)     # new key, stale quantity still shown
        self.assertEqual((second.status_code, second.json()["detail"]), (409, UNCONFIRMED))
        self.assertEqual(len(self.fake.accepted(symbol="S00USDT")), 1)               # NO second MARKET order
        other = self.close("S01USDT", self.expected["S01USDT"], 50, bulk=True)       # other symbols are unaffected
        self.assertEqual(other.status_code, 200)

    def test_KNOWN_RESIDUAL_plain_manual_click_with_a_new_key_is_not_covered_by_the_series_lock(self):
        """Pre-existing and unchanged: the plain individual Close has no such lock (measured, not gated)."""
        self.seed_world(n=3, hedged=0)
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": False})
        self.fake.lag["S00USDT"] = 3
        self.assertEqual(self.close("S00USDT", self.expected["S00USDT"], 50, bulk=True).status_code, 502)
        manual = self.close("S00USDT", self.expected["S00USDT"], 50)
        orders = len(self.fake.accepted(symbol="S00USDT"))
        print("INFO-manual-after-unconfirmed status", manual.status_code, "orders", orders)
        self.assertIn(orders, (1, 2))

    def test_lock_expires_after_ten_minutes(self):
        self.seed_world(n=3, hedged=0)
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": False})
        self.fake.lag["S00USDT"] = 1
        self.assertEqual(self.close("S00USDT", self.expected["S00USDT"], 50, bulk=True).status_code, 502)
        refs = self.db.collection("users").document(self.uid).collection("asterManualCloseIntents")
        for doc in refs.stream():
            doc.reference.set({"createdAt": datetime.now(timezone.utc) - timedelta(minutes=11)}, merge=True)
        self.fake._position_rows()                                                   # burn the delayed reflection
        live = self.fake.pos[("S00USDT", "SHORT")]
        again = self.close("S00USDT", live, 50, bulk=True)
        self.assertEqual(again.status_code, 200, again.text)

    def test_confirmed_closes_never_block_the_next_series(self):
        self.seed_world(n=3, hedged=0)
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": False})
        first = self.bulk(25)
        self.assertIsNone(first["stopped"], first)
        for symbol in list(first["closed"]):
            self.expected[symbol] = self.fake.pos[(symbol, "SHORT")]
        second = self.bulk(25)
        self.assertIsNone(second["stopped"], second)
        self.assertEqual(sorted(second["closed"]), sorted(first["closed"]))


class LeaseWindow(base.E2E):
    def wrap_acquire(self, after):
        original = S.main._acquire_aster_account_coordination
        seen = {}

        def wrapped(uid, owner, purpose):
            token = original(uid, owner, purpose)
            if token and owner == "MANUAL_POSITION_CLOSE":
                seen["token"], seen["t"] = token, time.time()
                after(uid, token)
            return token
        S.main._acquire_aster_account_coordination = wrapped
        self.addCleanup(setattr, S.main, "_acquire_aster_account_coordination", original)
        return seen

    def lease(self):
        return (self.db.collection("asterAccountCoordination").document(self.uid).get().to_dict() or {}).get("lease") or {}

    def test_lease_that_expired_before_the_freeze_is_refused_and_nothing_is_frozen_or_ordered(self):
        self.seed_world(n=3, hedged=3)

        def expire(uid, token):                                     # simulate a stall longer than the 45 s TTL
            self.db.collection("asterAccountCoordination").document(uid).set(
                {"lease": {"token": token, "until": datetime.now(timezone.utc) - timedelta(seconds=1)}}, merge=True)
        self.wrap_acquire(expire)
        r = self.close("S00USDT", self.expected["S00USDT"], 50, bulk=True)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, LEASE), r.text)
        self.assertEqual(self.fake.accepted(), [])
        self.assertEqual(self.pair("S00USDT")["status"], "HEDGED")                  # not frozen
        self.assertTrue(self.pair("S00USDT")["rehedgeEnabled"])

    def test_valid_lease_is_extended_before_the_order(self):
        self.seed_world(n=3, hedged=3)
        seen = self.wrap_acquire(lambda uid, token: None)
        reads = {"n": 0}

        def slow_second_read():
            reads["n"] += 1
            if reads["n"] == 2:
                time.sleep(1.5)                                      # slow exchange read under the lease
        self.fake.on_position_read = slow_second_read
        captured = {}

        def at_order(symbol):
            until = self.lease().get("until")
            captured["until"] = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
        self.fake.on_order_start = at_order
        r = self.close("S00USDT", self.expected["S00USDT"], 50, bulk=True)
        self.assertEqual(r.status_code, 200, r.text)
        acquired = datetime.fromtimestamp(seen["t"], tz=timezone.utc)
        self.assertGreater((captured["until"] - acquired).total_seconds(), 45 + 1.0, "lease was not extended")
        self.assertFalse(self.lease().get("token"))                                  # and released afterwards


if __name__ == "__main__":
    unittest.main()
