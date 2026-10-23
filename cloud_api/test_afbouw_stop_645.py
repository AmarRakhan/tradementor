"""Build 645 (Amar 24-10) — "Opnieuw hedgen na afbouw" (algemene instelling per afbouwkaart, standaard AAN).

UIT: is de hedge helemaal afgebouwd, dan gebeurt er niets meer voor dat pair (geen terugkoop, geen vangnet, geen
nieuwe Auto Hedge); tijdens de afbouw werkt terugkopen gewoon. Weer AAN: de grid gaat verder waar hij staat, het
vangnet telt vanaf de koers van dat moment (als die voorbij het laatste niveau ligt) -> niets meteen opnieuw hedgen.
"""
from __future__ import annotations

import unittest
from decimal import Decimal as D

from short_recovery_ladder import grid_step, normalize_settings
from test_hedge_grid_634 import SIX, GridWorker, go, walk

OFF = {**SIX, "rehedgeAfterAfbouw": False}


class Settings(unittest.TestCase):
    def test_default_on_and_validated(self):
        self.assertIs(normalize_settings(SIX)["rehedgeAfterAfbouw"], True)
        self.assertIs(normalize_settings(OFF)["rehedgeAfterAfbouw"], False)
        with self.assertRaises(ValueError):
            normalize_settings({**SIX, "rehedgeAfterAfbouw": "nee"})


class Pure(unittest.TestCase):
    kw = dict(anchor=100, n=3, total_pct="6", rebuy_steps=1, safety_pct="6")

    def test_done_means_no_rebuy_and_no_vangnet(self):
        for p in (100, 80):
            self.assertEqual(grid_step(price=p, sold=3, rehedge=False, **self.kw)["event"], "GRID_DONE_NO_REHEDGE")

    def test_rebuy_still_works_while_not_fully_sold(self):
        self.assertEqual(grid_step(price=100, sold=1, rehedge=False, **self.kw), {"sold": 0, "event": "GRID_REBUY"})

    def test_vangnet_counts_from_resume_price(self):
        self.assertEqual(grid_step(price=79, sold=3, safety_from=80, **self.kw)["event"], "GRID_HOLD")
        self.assertEqual(grid_step(price=75, sold=3, safety_from=80, **self.kw)["event"], "SAFETY_NET_REHEDGE")
        # resume price above the last level -> normal vangnet (94 * 0.94 = 88.36)
        self.assertEqual(grid_step(price=88, sold=3, safety_from=95, **self.kw)["event"], "SAFETY_NET_REHEDGE")


class Runtime(unittest.TestCase):
    def test_off_stops_after_full_reduction(self):
        out, rec = walk([98, 96, 94, 96, 98, 100, 80, 60], settings=OFF)
        self.assertEqual([s for _, s, _ in out], [6.667, 3.334, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(out[-1][2], "GRID_DONE_NO_REHEDGE")
        self.assertEqual((rec["phase"], rec["afbouwDone"]), ("LADDER", True))

    def test_off_still_buys_back_during_reduction(self):
        out, _ = walk([98, 100], settings=OFF)
        self.assertEqual([s for _, s, _ in out], [6.667, 10.0])

    def test_switch_back_on_resumes_without_rehedge(self):
        _, rec = walk([94, 80], settings=OFF)
        r = go(rec, settings=SIX, short_qty=0, mark=80)
        self.assertEqual((r["event"], r["override"], r["record"]["afbouwDone"]), ("GRID_HOLD", D("0"), False))
        r = go(r["record"], settings=SIX, short_qty=0, mark=76)
        self.assertEqual(r["event"], "GRID_HOLD")
        r = go(r["record"], settings=SIX, short_qty=0, mark=75)                 # 80 * 0.94 = 75.2
        self.assertEqual(r["event"], "SAFETY_NET_REHEDGE")

    def test_switch_back_on_buys_back_when_price_rises(self):
        _, rec = walk([94, 80], settings=OFF)
        r = go(rec, settings=SIX, short_qty=0, mark=80)
        r = go(r["record"], settings=SIX, short_qty=0, mark=96)
        self.assertEqual((r["event"], r["override"]), ("GRID_REBUY", D("3.334")))
        self.assertNotIn("safetyFrom", r["record"])


class Worker(GridWorker):
    def test_off_in_the_worker_no_orders_after_full_sale(self):
        self.setup_pair(plan=OFF)
        for p in (100, 94, 94, 88, 80, 96, 100):
            self.at(p)
        self.assertEqual(self.orders(), [("SHORT", "CLOSE", 10.0)])
        self.assertAlmostEqual(self.short("SOLUSDT"), 0.0)
        self.assertEqual(self.long("SOLUSDT"), 10.0)
        self.assertTrue(self.pair("SOLUSDT")["shortRecovery"]["afbouwDone"])

    # the inherited GridWorker tests run again with the default (ON): unchanged behaviour


if __name__ == "__main__":
    unittest.main()
