"""Close Profits 2.1 — rounds end-to-end on the REAL stack (same setup as test_close_profits_2_0_e2e_stack):
 * the production ASGI entrypoint (p0_close_scope_guard -> withdraw_app -> main.app + the new rounds router),
 * real pydantic request models, real `main.close_one_aster_position`, real AsterV3Client + execute_leg_once,
 * real Firestore SDK against the Firestore EMULATOR,
 * Aster = HTTP-level fake (offline_fake_aster), including the read-only order query (-2013 when absent).
Only mocked: Aster (HTTP fake), Firebase ID-token verification, the Secret Manager lookup. SKIPs without a localhost
emulator. Never run against production."""
from __future__ import annotations

import unittest
import uuid
from datetime import timedelta

import test_close_profits_2_0_e2e_stack as base

setUpModule = base.setUpModule
tearDownModule = base.tearDownModule


@unittest.skipUnless(base.READY, "needs Firestore emulator")
class RoundsE2E(base.E2E):
    def create(self, pct=25, key=None, symbols=None):
        preview = self.preview(pct)
        picked = {s["symbol"] for s in preview["selected"] if str(s["side"]).upper() == "SHORT"}
        targets = [{"symbol": r["symbol"], "side": "SHORT", "quantity": abs(float(r["quantity"]))}
                   for r in preview["snapshot"]["rows"]
                   if r["symbol"] in picked and r["side"] == "SHORT" and (symbols is None or r["symbol"] in symbols)]
        return self.http.post("/v1/me/aster/profit-close-rounds", json={
            "confirm": True, "percentage": pct, "idempotency_key": key or ("e2e-round-" + uuid.uuid4().hex),
            "targets": targets})

    def advance(self, rid):
        r = self.http.post(f"/v1/me/aster/profit-close-rounds/{rid}/advance")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def run_round(self, rid, steps=400):
        for _ in range(steps):
            out = self.advance(rid)
            if out["round"]["status"] in {"FINISHED", "ABANDONED", "PAUSED"}:
                return out["round"]
        self.fail("round did not finish")

    def item(self, rnd, sym):
        return next(i for i in rnd["items"] if i["symbol"] == sym)

    def per_symbol(self):
        out = {}
        for order in self.fake.accepted():
            out[order["symbol"]] = out.get(order["symbol"], 0) + 1
        return out

    # ------------------------------------------------------------------------------------------------ tests
    def test_full_round_25_shorts_each_exactly_once_and_noise_untouched(self):
        self.seed_world()
        r = self.create(50)
        self.assertEqual(r.status_code, 200, r.text)
        rnd = self.run_round(r.json()["round"]["roundId"])
        self.assertEqual(rnd["status"], "FINISHED")
        self.assertEqual(rnd["counts"]["done"], 25)
        self.assertEqual(self.per_symbol(), {s: 1 for s in self.expected})
        for sym in ("LOSSUSDT", "LONGUSDT", "EDGEUSDT"):
            self.assertNotIn(sym, self.per_symbol())
        self.assertIsNone(self.http.get("/v1/me/aster/profit-close-rounds/active").json()["round"])

    def test_interrupted_round_resumes_and_a_new_press_is_refused_meanwhile(self):
        self.seed_world(n=15, hedged=3)
        rid = self.create(25).json()["round"]["roundId"]
        self.advance(rid)                                                       # phone dies after the first close
        self.assertEqual(len(self.fake.accepted()), 1)
        again = self.create(25)
        self.assertEqual(again.status_code, 409)
        active = self.http.get("/v1/me/aster/profit-close-rounds/active").json()["round"]
        self.assertEqual(active["roundId"], rid)
        self.assertEqual(active["counts"]["remaining"], 14)
        rnd = self.run_round(rid)
        self.assertEqual(rnd["counts"]["done"], 15)
        self.assertEqual(self.per_symbol(), {s: 1 for s in self.expected})

    def test_same_confirmation_resent_after_a_lost_response_is_the_same_round(self):
        self.seed_world(n=3, hedged=0)
        a = self.create(25, key="e2e-round-same-key-0001").json()
        b = self.create(25, key="e2e-round-same-key-0001").json()
        self.assertEqual(a["round"]["roundId"], b["round"]["roundId"])
        self.assertFalse(b["created"])

    def test_read_timeout_after_accept_is_reconciled_by_query_and_never_ordered_twice(self):
        self.seed_world(n=5, hedged=2)
        self.fake.modes["S02USDT"] = "timeout_after_accept"
        rnd = self.run_round(self.create(50).json()["round"]["roundId"])
        self.assertEqual(self.item(rnd, "S02USDT")["status"], "DONE")
        self.assertEqual(self.per_symbol(), {s: 1 for s in self.expected})
        self.assertEqual(rnd["status"], "FINISHED")

    def test_partial_fill_is_needs_check_and_the_rest_continues(self):
        self.seed_world(n=5, hedged=1)
        self.fake.modes["S02USDT"] = "partial_fill"
        rnd = self.run_round(self.create(50).json()["round"]["roundId"])
        self.assertEqual(self.item(rnd, "S02USDT")["status"], "NEEDS_CHECK")
        self.assertEqual(self.per_symbol(), {s: 1 for s in self.expected})        # one order for S02 only, never two
        self.assertEqual(rnd["counts"]["done"], 4)

    def test_503_without_acceptance_is_retried_once_aster_proves_no_order(self):
        import profit_close_rounds as R
        old = R.NOT_FOUND_GRACE
        R.NOT_FOUND_GRACE = timedelta(0)                                          # test only: skip the 60 s wait
        try:
            self.seed_world(n=3, hedged=0)
            self.fake.modes["S01USDT"] = "http503_unknown"
            rid = self.create(25).json()["round"]["roundId"]
            for _ in range(3):
                self.advance(rid)                                                 # S00 done, S01 unknown -> query -> absent
            self.fake.modes["S01USDT"] = "ok"                                     # Aster recovers
            rnd = self.run_round(rid)
        finally:
            R.NOT_FOUND_GRACE = old
        self.assertEqual(self.item(rnd, "S01USDT")["status"], "DONE")
        self.assertGreaterEqual(self.item(rnd, "S01USDT")["attempt"], 1)
        self.assertEqual(self.per_symbol(), {s: 1 for s in self.expected})

    def test_abandon_over_http_stops_the_rest_and_frees_the_button(self):
        self.seed_world(n=4, hedged=0)
        rid = self.create(25).json()["round"]["roundId"]
        self.advance(rid)
        r = self.http.post(f"/v1/me/aster/profit-close-rounds/{rid}/abandon")
        self.assertEqual(r.json()["round"]["status"], "ABANDONED")
        self.advance(rid)
        self.assertEqual(len(self.fake.accepted()), 1)
        self.assertIsNone(self.http.get("/v1/me/aster/profit-close-rounds/active").json()["round"])

    def test_unknown_round_is_404_and_requests_are_validated(self):
        self.assertEqual(self.http.get("/v1/me/aster/profit-close-rounds/doesnotexist0000").status_code, 404)
        r = self.http.post("/v1/me/aster/profit-close-rounds", json={"confirm": True, "percentage": 33,
                                                                     "idempotency_key": "x" * 20,
                                                                     "targets": [{"symbol": "S00USDT", "side": "SHORT",
                                                                                  "quantity": 1}]})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.fake.accepted(), [])


if __name__ == "__main__":
    unittest.main()
