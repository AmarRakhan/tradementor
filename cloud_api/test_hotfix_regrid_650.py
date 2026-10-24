"""Build 650 hotfix: a recount never moves the hedge (649 rounded sold parts down and tried to buy SHORT back)."""
from __future__ import annotations

import unittest
from decimal import Decimal as D

from test_hedge_grid_634 import go

TEN = {"enabled": True, "steps": 5, "totalPct": "10", "rehedgePct": "75"}


class Recount(unittest.TestCase):
    def test_649_record_with_target_above_hedge_is_recounted_to_the_hedge(self):
        # APT-like: base 40.7, hedge 13.6 (sold 27.1 = 3.33 parts of 8.14), 649 stored parts [1,2,3] -> target 16.3
        bad = {"phase": "LADDER", "cycleId": 2, "anchor": "100", "base": "40.7", "longAtStart": "40.7", "sold": 3,
               "soldParts": [1, 2, 3], "gridParts": 5, "gridKey": "5|10|1|EQUAL", "kept": "0", "lastTarget": "16.3"}
        r = go(bad, settings=TEN, long_qty="40.7", short_qty="13.6", mark="93.5", qty_step="0.1")
        self.assertEqual(r["override"], D("13.6"))                       # no order: hedge stays exactly where it is
        self.assertEqual((r["record"]["gridFix"], r["record"]["soldParts"]), (650, [1, 2, 3]))
        r2 = go(r["record"], settings=TEN, long_qty="40.7", short_qty="13.6", mark="93.5", qty_step="0.1")
        self.assertEqual((r2["event"], r2["override"]), ("GRID_HOLD", D("13.6")))

    def test_recount_after_settings_change_keeps_the_hedge(self):
        for short in ("3.334", "5", "7.7", "10"):
            rec = {"phase": "LADDER", "cycleId": 1, "anchor": "100", "base": "10", "longAtStart": "10", "sold": 1,
                   "soldParts": [1], "gridParts": 3, "gridKey": "3|6|1|EQUAL", "gridFix": 650, "kept": "0"}
            r = go(rec, settings={"enabled": True, "steps": 7, "totalPct": "6", "rebuySteps": 7}, short_qty=short, mark=100)
            self.assertEqual(r["override"], D(short), short)


if __name__ == "__main__":
    unittest.main()
