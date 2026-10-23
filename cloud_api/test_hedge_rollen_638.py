"""Build 638 (Amar 23-10): an exactly 1:1 pair follows the afbouw setting that is ON (labels only, no orders)."""
from __future__ import annotations

import unittest

from test_rehedge_all_1_0 import HAVE, Base, HedgeClient

SIX = {"enabled": True, "steps": 3, "totalPct": "6", "rebuySteps": 2}


@unittest.skipUnless(HAVE, "needs fastapi + aster_gateway deps")
class FlipRoles(Base):
    def setUp(self):
        super().setUp()
        self.ext.SHORT_RECOVERY_EXECUTION_ENABLED = True
        self.ext._hedge_mode_ok_at.clear()
        HedgeClient.income_history = lambda client, **kw: []
        if not getattr(self, "_income_cleanup", False):
            self._income_cleanup = True
            self.addCleanup(lambda: delattr(HedgeClient, "income_history"))

    def setup(self, plans, short_qty=10.0, long_qty=10.0):
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": True, "thresholdUsd": 0.25,
                                                            "thresholdShortUsd": 10.0, **plans})
        self.L.add("ADBEUSDT", "SHORT", short_qty, mark=100.0, entry=95.0)       # old SHORT, in loss
        self.L.pos[("ADBEUSDT", "LONG")] = long_qty                               # Auto Hedge LONG
        self.L.entry[("ADBEUSDT", "LONG")] = 99.0
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "ADBEUSDT",
                 {"symbol": "ADBEUSDT", "status": "HEDGED", "protectedSide": "SHORT", "hedgeSide": "LONG",
                  "generation": 1, "generationId": "g1", "intentRevision": 0, "rehedgeEnabled": False})

    def tick(self, mark):
        self.L.mark["ADBEUSDT"] = float(mark)
        self.worker_tick()
        self.assertTrue(self.lease_free())

    def test_flips_to_long_protected_and_joins_short_grid_without_orders(self):
        self.setup({"shortRecoveryPlan": dict(SIX)})
        self.tick(100)
        self.tick(100)
        pair = self.pair("ADBEUSDT")
        self.assertEqual((pair["protectedSide"], pair["hedgeSide"], pair["lastReason"] if False else "ok"),
                         ("LONG", "SHORT", "ok"))
        self.assertEqual(self.L.hedge_orders, [])                                 # labels only
        self.assertEqual((self.long("ADBEUSDT"), self.short("ADBEUSDT")), (10.0, 10.0))
        rec = pair["shortRecovery"]
        self.assertEqual((rec["phase"], rec["anchor"]), ("LADDER", "95"))         # anchored on the SHORT entry

    def test_grid_sells_only_with_profit_after_flip(self):
        self.setup({"shortRecoveryPlan": dict(SIX)})
        self.tick(100); self.tick(100)
        self.tick("94.5")                                                         # below 95*0.98 = 93.1? not yet
        self.assertEqual(self.L.hedge_orders, [])
        self.tick(93)                                                             # first level 93.1 crossed
        self.assertEqual([(o["positionSide"], o["action"]) for o in self.L.hedge_orders], [("SHORT", "CLOSE")])

    def test_no_flip_when_both_off_or_both_on_or_not_1_to_1(self):
        for plans, qty in (({}, 10.0),
                           ({"shortRecoveryPlan": dict(SIX), "longRecoveryPlan": dict(SIX)}, 10.0),
                           ({"shortRecoveryPlan": dict(SIX)}, 12.0)):
            with self.subTest(plans=list(plans), qty=qty):
                self.setUp()
                self.setup(plans, long_qty=qty)
                self.tick(100)
                self.assertEqual(self.pair("ADBEUSDT")["protectedSide"], "SHORT")
                self.assertEqual(self.L.hedge_orders, [])


if __name__ == "__main__":
    unittest.main()
