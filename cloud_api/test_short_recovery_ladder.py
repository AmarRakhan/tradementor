import unittest
from decimal import Decimal as D

from short_recovery_ladder import (
    desired_short, ladder, normalize_settings, plan, released_quantity, steps_reached,
)

FOUR = {"enabled": True, "steps": 4, "stepPct": "2"}
TEN = {"enabled": True, "steps": 10, "stepPct": "0.2"}


def run(**kw):
    base = dict(long_qty=100, short_qty=100, base=100, anchor=100, mark=100, settings=FOUR,
                previous_steps=0, qty_step="1", min_qty=0, min_notional=0)
    base.update(kw)
    return plan(**base)


class Settings(unittest.TestCase):
    def test_defaults_off(self):
        self.assertEqual(normalize_settings(None), {"enabled": False, "steps": 4, "stepPct": "2"})

    def test_free_choice(self):
        self.assertEqual(normalize_settings({"steps": 10, "stepPct": "0.1"})["steps"], 10)
        self.assertEqual(normalize_settings({"steps": 1, "stepPct": "50"})["stepPct"], "50")

    def test_rejects_invalid(self):
        for bad in ({"steps": 0}, {"steps": 101}, {"steps": True}, {"steps": 2.5},
                    {"stepPct": 0}, {"stepPct": "-1"}, {"stepPct": "nan"}, {"steps": 4, "stepPct": 25},
                    {"enabled": "yes"}):
            with self.assertRaises(ValueError, msg=bad):
                normalize_settings(bad)


class Ladder(unittest.TestCase):
    def test_levels_from_same_anchor(self):
        self.assertEqual([r["price"] for r in ladder(100, FOUR)], [D("98"), D("96"), D("94"), D("92")])

    def test_spec_example_five_percent(self):
        cfg = {"steps": 4, "stepPct": "5"}
        self.assertEqual([r["price"] for r in ladder(100, cfg)], [D("95"), D("90"), D("85"), D("80")])

    def test_steps_monotonic_bounce_never_lowers(self):
        self.assertEqual(steps_reached(100, "95.9", FOUR), 2)
        self.assertEqual(steps_reached(100, 101, FOUR, previous=2), 2)

    def test_gap_down_reaches_several_steps_at_once(self):
        self.assertEqual(steps_reached(100, 91, FOUR), 4)

    def test_released_and_desired(self):
        self.assertEqual(released_quantity(100, 1, 4, 1), D(25))
        self.assertEqual(released_quantity(10, 1, 4, 1), D(2))  # floored to step
        self.assertEqual(released_quantity(10, 4, 4, 1), D(10))  # last step releases all
        self.assertEqual(desired_short(100, 100, 2, 4, 1), D(50))


class Plan(unittest.TestCase):
    def test_hold_above_first_level(self):
        r = run(mark="98.5")
        self.assertEqual((r["action"], r["quantity"]), ("HOLD", D(0)))

    def test_each_step_reduces_quarter(self):
        r = run(mark=98)
        self.assertEqual((r["action"], r["quantity"], r["reason"]), ("REDUCE_SHORT", D(25), "STEP_1_OF_4"))
        r = run(mark=96, short_qty=75, previous_steps=1)
        self.assertEqual(r["quantity"], D(25))

    def test_never_reduces_already_reduced(self):
        r = run(mark=97, short_qty=75, previous_steps=1)
        self.assertEqual(r["action"], "HOLD")

    def test_gap_down_combines(self):
        r = run(mark=95)
        self.assertEqual(r["quantity"], D(50))

    def test_small_step_carries_then_combines(self):
        r = run(mark=98, min_qty=40)
        self.assertEqual((r["action"], r["reason"]), ("HOLD", "BELOW_MINIMUM_CARRY_TO_NEXT_STEP"))
        r = run(mark=96, previous_steps=r["stepsReached"], min_qty=40)
        self.assertEqual((r["action"], r["quantity"]), ("REDUCE_SHORT", D(50)))

    def test_min_notional_carry(self):
        r = run(mark=98, min_notional=5000)
        self.assertEqual(r["reason"], "BELOW_MINIMUM_CARRY_TO_NEXT_STEP")

    def test_cycle_complete_triggers_refill(self):
        r = run(mark=92, short_qty=0, previous_steps=4)
        self.assertEqual((r["action"], r["reason"]), ("CYCLE_COMPLETE", "LADDER_FINISHED_REFILL"))

    def test_final_remainder_below_minimum_completes(self):
        r = run(mark=92, short_qty=3, previous_steps=4, min_qty=5)
        self.assertEqual((r["action"], r["reason"]), ("CYCLE_COMPLETE", "FINAL_REMAINDER_BELOW_MINIMUM_REFILL"))

    def test_never_reduces_more_than_open(self):
        r = run(mark=50, short_qty=10, previous_steps=0)
        self.assertLessEqual(r["quantity"], D(10))

    def test_long_growth_stays_hedged(self):
        # DCA added 50 LONG after the anchor: only the original base is released.
        r = run(mark=96, long_qty=150, short_qty=150)
        self.assertEqual((r["targetShort"], r["quantity"]), (D(100), D(50)))

    def test_over_hedged_left_to_auto_hedge(self):
        r = run(mark=92, long_qty=50, short_qty=60)
        self.assertEqual(r["action"], "HOLD")

    def test_ten_small_steps(self):
        r = run(mark="99.6", settings=TEN, qty_step="0.1")
        self.assertEqual((r["stepsReached"], r["quantity"]), (2, D("20.0")))


if __name__ == "__main__":
    unittest.main()
