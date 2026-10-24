"""Build 646 (Amar 24-10) — afbouwkaart: "Terugkopen na stappen" (0 = uit) en "Terughedgen" X% (standaard 100).

X% geldt voor alles wat de hedge weer groter maakt: een terugkoop zet X% van het verkochte deel terug, het vangnet
hedget X% van de positie terug (altijd X% van de hele positie, niet van de vorige hedge). 0% = na volledige afbouw
niets meer voor dat pair (geen vangnet). Van 0% weer omhoog: grid gaat verder, vangnet vanaf de koers van dat
moment, niets meteen opnieuw hedgen. 100% = gedrag van 634.
"""
from __future__ import annotations

import unittest
from decimal import Decimal as D

from short_recovery_ladder import grid_step, normalize_settings
from test_hedge_grid_634 import SIX, GridWorker, go, walk

ZERO = {**SIX, "rehedgePct": "0"}
HALF = {**SIX, "rehedgePct": "50"}
TEN = {"enabled": True, "steps": 10, "totalPct": "10", "rehedgePct": "50"}


class Settings(unittest.TestCase):
    def test_defaults_and_limits(self):
        cfg = normalize_settings(SIX)
        self.assertEqual((cfg["rehedgePct"], cfg["rebuySteps"]), ("100", 1))
        self.assertEqual(normalize_settings({**SIX, "rebuySteps": 0})["rebuySteps"], 0)
        self.assertEqual(normalize_settings(HALF)["rehedgePct"], "50")
        for bad in ({"rehedgePct": "101"}, {"rehedgePct": "-1"}, {"rehedgePct": "x"}, {"rebuySteps": -1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_settings({**SIX, **bad})


class Pure(unittest.TestCase):
    kw = dict(anchor=100, n=3, total_pct="6", safety_pct="6")

    def test_zero_pct_done_means_no_vangnet(self):
        for p in (100, 80):
            self.assertEqual(grid_step(price=p, sold=3, rebuy_steps=1, rehedge=False, **self.kw)["event"],
                             "GRID_DONE_NO_REHEDGE")

    def test_rebuy_off(self):
        self.assertEqual(grid_step(price=100, sold=2, rebuy_steps=0, **self.kw), {"sold": 2, "event": "GRID_HOLD"})

    def test_vangnet_counts_from_resume_price(self):
        self.assertEqual(grid_step(price=79, sold=3, rebuy_steps=1, safety_from=80, **self.kw)["event"], "GRID_HOLD")
        self.assertEqual(grid_step(price=75, sold=3, rebuy_steps=1, safety_from=80, **self.kw)["event"],
                         "SAFETY_NET_REHEDGE")


class Runtime(unittest.TestCase):
    def test_amar_example_half_buy_back_grows_net_long(self):
        # LONG 10, SHORT 10, 10% in 10 stappen, terugkopen na 1 stap, terughedgen 50%.
        out, rec = walk([99, 100, 99, 100], settings=TEN)
        self.assertEqual([s for _, s, _ in out], [9.0, 9.5, 8.5, 9.0])
        self.assertEqual(rec["kept"], "1")

    def test_rebuy_off_never_buys_back(self):
        out, _ = walk([98, 96, 98, 100], settings={**SIX, "rebuySteps": 0})
        self.assertEqual([s for _, s, _ in out], [6.667, 3.334, 3.334, 3.334])

    def test_vangnet_rehedges_half_of_the_position(self):
        out, rec = walk([94, 88], settings=HALF)
        self.assertEqual(out[-1][2], "SAFETY_NET_REHEDGE")
        self.assertEqual((rec["phase"], rec["refillPct"], out[-1][1]), ("REFILL", "50", 5.0))
        r = go(rec, settings=HALF, short_qty=0, mark=88)                          # order not filled yet
        self.assertEqual((r["event"], r["override"]), ("WAIT_FOR_REHEDGE_PCT", D("5")))
        r = go(r["record"], settings=HALF, short_qty=5, mark=88, short_entry=88)
        self.assertEqual((r["event"], r["record"]["base"], r["record"]["anchor"]), ("CYCLE_STARTED", "5", "88"))

    def test_next_vangnet_is_again_half_of_the_whole_position(self):
        _, rec = walk([94, 88], settings=HALF)
        r = go(rec, settings=HALF, short_qty=5, mark=88, short_entry=88)
        rec, short = r["record"], D(5)
        for p in ("82.72", "77"):                                              # 88 * 0.94 = 82.72; 82.72 * 0.94 = 77.76
            r = go(rec, settings=HALF, short_qty=short, mark=p, short_entry=88)
            rec = r["record"]
            short = r["override"] if r["override"] is not None else short
        self.assertEqual((r["event"], r["override"]), ("SAFETY_NET_REHEDGE", D("5")))

    def test_zero_pct_stops_after_full_reduction(self):
        out, rec = walk([98, 96, 94, 96, 98, 100, 80, 60], settings=ZERO)
        self.assertEqual([s for _, s, _ in out], [6.667, 3.334, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual((out[-1][2], rec["afbouwDone"]), ("GRID_DONE_NO_REHEDGE", True))

    def test_from_zero_back_up_resumes_without_rehedge(self):
        _, rec = walk([94, 80], settings=ZERO)
        r = go(rec, settings=SIX, short_qty=0, mark=80)
        self.assertEqual((r["event"], r["override"], r["record"]["afbouwDone"]), ("GRID_HOLD", D("0"), False))
        r = go(r["record"], settings=SIX, short_qty=0, mark=76)
        self.assertEqual(r["event"], "GRID_HOLD")
        r = go(r["record"], settings=SIX, short_qty=0, mark=75)                   # 80 * 0.94 = 75.2
        self.assertEqual(r["event"], "SAFETY_NET_REHEDGE")

    def test_half_too_small_for_aster_rehedges_the_minimum(self):
        out, rec = walk([98, 96, 94, 88], settings=HALF, long_qty="0.09", short_qty="0.09", qty_step="0.01",
                        min_notional=5)
        # Build 651: 50% (0.04) is below the Aster minimum ($5) -> the noodrem re-hedges the minimum (0.06), not nothing.
        self.assertEqual((out[-1][2], out[-1][1], rec["phase"]), ("SAFETY_NET_REHEDGE", 0.06, "REFILL"))

    def test_hundred_pct_is_unchanged(self):
        out, rec = walk([98, 96, 94, 96, 98, 100])
        self.assertEqual([s for _, s, _ in out], [6.667, 3.334, 0.0, 3.334, 6.667, 10.0])
        self.assertEqual(rec["kept"], "0")


class Worker(GridWorker):
    def test_zero_pct_no_orders_after_full_sale(self):
        self.setup_pair(plan=ZERO)
        for p in (100, 94, 94, 88, 80, 96, 100):
            self.at(p)
        self.assertEqual(self.orders(), [("SHORT", "CLOSE", 10.0)])
        self.assertEqual((self.short("SOLUSDT"), self.long("SOLUSDT")), (0.0, 10.0))
        self.assertTrue(self.pair("SOLUSDT")["shortRecovery"]["afbouwDone"])

    def test_half_vangnet_opens_half_in_the_worker(self):
        self.setup_pair(plan=HALF)
        for p in (100, 94, 94, 88, 88):
            self.at(p)
        self.assertAlmostEqual(self.short("SOLUSDT"), 5.0)
        self.assertEqual(self.long("SOLUSDT"), 10.0)


if __name__ == "__main__":
    unittest.main()
