"""Build 647 (Amar 24-10) — Max hedge % per kant en Verdeling (Gelijk / Oplopend / Sterk oplopend), terugkopen B.

Verdeling: weg van het startpunt eerst de kleine delen, ver weg de grote. Terug (keuze B): eerst het kleinste
verkochte deel, de grote delen pas hoger. Max hedge: de hedge is X% van de positie (nooit verkopen om er te komen);
afbouw, terughedgen, noodrem en Re-Hedge All rekenen vanaf die X%.
"""
from __future__ import annotations

import unittest
from decimal import Decimal as D

from aster_position_loss_auto_hedge import evaluate_auto_hedge
from short_recovery_ladder import normalize_settings, part_weights, parts_released
from test_hedge_grid_634 import GridWorker, go, walk
from test_rehedge_all_1_0 import HAVE

ASC = {"enabled": True, "steps": 5, "totalPct": "10", "distribution": "ASCENDING"}
AMAR = {**ASC, "rebuySteps": 3, "rehedgePct": "75", "safetyNetPct": "6"}


class Ladder(unittest.TestCase):
    def test_weights_and_settings(self):
        self.assertEqual(part_weights(5, "ASCENDING"), [D(1), D(2), D(3), D(4), D(5)])
        self.assertEqual(part_weights(4, "STEEP"), [D(1), D(2), D(4), D(8)])
        self.assertEqual(normalize_settings({"enabled": True})["distribution"], "EQUAL")
        self.assertEqual(normalize_settings(ASC)["distribution"], "ASCENDING")
        with self.assertRaises(ValueError):
            normalize_settings({**ASC, "distribution": "RANDOM"})
        self.assertEqual(parts_released(10, [1], 5, "0.001", "ASCENDING"), D("0.666"))
        self.assertEqual(parts_released(10, [1, 2, 3, 4, 5], 5, "0.001", "ASCENDING"), D("10"))


class Runtime(unittest.TestCase):
    def test_ascending_sells_small_first_big_last(self):
        out, _ = walk([98, 96, 94, 92, 90], settings=ASC)
        self.assertEqual([s for _, s, _ in out], [9.334, 8.0, 6.0, 3.334, 0.0])

    def test_amar_option_b_small_parts_come_back_first(self):
        out, _ = walk([98, 96, 94, 92, 90, 92, 94, 96, 98, 100, 102, 104], settings=AMAR)
        up = [s for _, s, _ in out[7:]]                                     # 96, 98, 100, 102, 104
        for got, want in zip(up, [0.5, 1.5, 3.0, 5.0, 7.5]):
            self.assertAlmostEqual(got, want, delta=0.01)

    def test_equal_distribution_is_unchanged(self):
        out, _ = walk([98, 96, 94, 96, 98, 100])
        self.assertEqual([s for _, s, _ in out], [6.667, 3.334, 0.0, 3.334, 6.667, 10.0])

    def test_pre_647_record_without_sold_parts_continues(self):
        old = {"phase": "LADDER", "cycleId": 3, "anchor": "100", "base": "10", "longAtStart": "10", "sold": 1,
               "gridParts": 3, "gridKey": "3|6|1|EQUAL", "steps": 3, "totalPct": "6", "lastTarget": "6.667"}
        r = go(old, short_qty="6.667", mark=99)
        self.assertEqual((r["record"]["soldParts"], r["override"]), ([1], D("6.667")))

    def test_max_hedge_cycle_starts_on_the_max_share(self):
        r = go(None, short_qty=0, mark=100, max_hedge="0.6")
        self.assertEqual((r["event"], r["override"]), ("WAIT_FOR_REHEDGE_PCT", D("6")))
        r = go(None, short_qty=6, mark=100, max_hedge="0.6")
        self.assertEqual((r["event"], r["record"]["base"]), ("CYCLE_STARTED", "6"))

    def test_existing_full_hedge_is_kept_and_reduced_by_the_grid(self):
        r = go(None, short_qty=10, mark=100, max_hedge="0.6")
        self.assertEqual((r["event"], r["record"]["base"]), ("CYCLE_STARTED", "10"))   # never sold to reach 60%

    def test_noodrem_is_terughedgen_of_the_max(self):
        _, rec = walk([94, 88], settings={"enabled": True, "steps": 3, "totalPct": "6", "rehedgePct": "75"},
                      max_hedge="0.6", short_qty=6)
        self.assertEqual((rec["phase"], rec["lastTarget"]), ("REFILL", "4.5"))   # 75% of 60% of 10

    def test_dca_is_hedged_at_the_max_share(self):
        r = go(None, short_qty=6, mark=100, max_hedge="0.6")
        r = go(r["record"], long_qty=15, short_qty=6, mark=100, max_hedge="0.6")
        self.assertEqual(r["override"], D("9"))                                 # 6 + 60% of 5


def _pos(symbol, side, qty, mark, entry):
    return {"symbol": symbol, "positionSide": side, "positionAmt": str(qty if side == "LONG" else -qty),
            "markPrice": str(mark), "entryPrice": str(entry),
            "unRealizedProfit": str((mark - entry) * qty if side == "LONG" else (entry - mark) * qty)}


@unittest.skipUnless(HAVE, "needs aster_gateway deps")
class Engine(unittest.TestCase):
    def act(self, short_qty, cap):
        rows = [_pos("SOLUSDT", "LONG", 10, 100, 101)]
        if short_qty:
            rows.append(_pos("SOLUSDT", "SHORT", short_qty, 100, 100))
        return evaluate_auto_hedge(rows, 0.25, max_caps={("SOLUSDT", "LONG"): cap})[0]

    def test_new_hedge_opens_only_the_max(self):
        a = self.act(0, 6.0)
        self.assertEqual((a.operation, a.target_qty, round(a.delta_qty, 9), a.reason), ("OPEN", 6.0, 6.0, "MAX_HEDGE_OPEN"))

    def test_bigger_hedge_is_kept_never_sold(self):
        for qty in (10, 7):
            a = self.act(qty, 6.0)
            self.assertEqual((a.operation, a.status), ("HOLD", "HEDGED"))

    def test_without_cap_still_one_to_one(self):
        rows = [_pos("SOLUSDT", "LONG", 10, 100, 101)]
        a = evaluate_auto_hedge(rows, 0.25)[0]
        self.assertEqual((a.target_qty, a.delta_qty), (10.0, 10.0))


class Worker(GridWorker):
    def test_new_trigger_hedges_the_max_share(self):
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": True, "thresholdUsd": 0.25,
                                                            "thresholdShortUsd": 10.0, "maxHedgePct": 60})
        self.L.add("SOLUSDT", "LONG", 10.0, mark=100.0, entry=101.0)
        self.at(100)
        self.assertEqual(self.orders(), [("SHORT", "OPEN", 6.0)])
        self.at(100)
        self.assertEqual(self.orders(), [("SHORT", "OPEN", 6.0)])            # no top-up to 1:1 afterwards
        self.assertEqual(self.pair("SOLUSDT")["status"], "HEDGED")


if __name__ == "__main__":
    unittest.main()
