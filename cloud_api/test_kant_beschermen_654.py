"""Build 654 (Amar 24-10): "LONG-posities beschermen" / "SHORT-posities beschermen".

Uit = Auto Hedge zet voor die kant geen NIEUWE hedge (trigger of automatisch opnieuw hedgen na Recovery).
Lopende pairs blijven gewoon beheerd; de SHORT-hedge van een LONG (afbouwen) werkt door.
"""
from __future__ import annotations

import unittest

from aster_position_loss_auto_hedge import evaluate_auto_hedge
from test_hedge_grid_634 import GridWorker
from test_max_hedge_verdeling_647 import _pos
from test_rehedge_all_1_0 import HAVE


@unittest.skipUnless(HAVE, "needs aster_gateway deps")
class Engine(unittest.TestCase):
    def test_short_side_off_skips_new_short_trigger(self):
        rows = [_pos("ABCUSDT", "SHORT", 4, 103, 98)]                    # SHORT -$20
        self.assertEqual(len(evaluate_auto_hedge(rows, 10)), 1)
        self.assertEqual(evaluate_auto_hedge(rows, 10, allowed_sides={"LONG"}), [])

    def test_active_pair_keeps_its_side(self):
        rows = [_pos("ABCUSDT", "SHORT", 4, 103, 98), _pos("ABCUSDT", "LONG", 2, 103, 100)]
        a = evaluate_auto_hedge(rows, 10, protected_sides={"ABCUSDT": "SHORT"}, allowed_sides={"LONG"})
        self.assertEqual((a[0].protected_side, a[0].operation), ("SHORT", "OPEN"))


class Worker(GridWorker):
    test_wave_sells_down_and_buys_back_up = None
    test_mirrored_long_hedge_on_rising_price = None
    test_vangnet_in_the_worker = None

    def _settings(self, **extra):
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": True, "thresholdUsd": 0.25,
                                                            "thresholdShortUsd": 10.0, **extra})

    def test_short_off_no_long_hedge_for_a_losing_short(self):
        self._settings(protectShortPositions=False)
        self.L.add("ABCUSDT", "SHORT", 4.0, mark=103.0, entry=98.0)
        self.L.mark["ABCUSDT"] = 103.0
        self.worker_tick()
        self.assertEqual(self.orders(), [])

    def test_short_off_long_still_protected(self):
        self._settings(protectShortPositions=False)
        self.L.add("SOLUSDT", "LONG", 10.0, mark=100.0, entry=101.0)
        self.at(100)
        self.assertEqual(self.orders(), [("SHORT", "OPEN", 10.0)])

    def test_default_both_on(self):
        self._settings()
        self.L.add("ABCUSDT", "SHORT", 4.0, mark=103.0, entry=98.0)
        self.worker_tick()
        self.assertEqual([o[:2] for o in self.orders()], [("LONG", "OPEN")])

    def test_flags_in_public_state_and_saved(self):
        self._settings(protectShortPositions=False)
        flags = self.ext._protect_flags(self.ext._current(self.uid))
        self.assertEqual(flags, {"protectLongPositions": True, "protectShortPositions": False})


if __name__ == "__main__":
    unittest.main()
