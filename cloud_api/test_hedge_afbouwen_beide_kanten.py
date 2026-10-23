"""Build 623 (Amar 23-10) — hedge afbouwen for BOTH sides, pure: ladder + runtime.

LONG protected / SHORT hedge (DOWN) is the original case; SHORT protected / LONG hedge (UP) mirrors it.
Also: a step only sells when profitable after fees, an over-covered pair is never sold to straighten it,
and after Re-Hedge All the next cycle is anchored at the price of that moment.
"""
from __future__ import annotations

import unittest
from decimal import Decimal as D

from short_recovery_ladder import (
    direction_for, hedge_side_for, ladder, plan, profitable_after_fees, step_price, steps_reached,
)
from short_recovery_runtime import decide

THREE_OF_6 = {"enabled": True, "steps": 3, "totalPct": "6"}       # Amar: 6% in 3 steps -> every 2%


def run(**kw):
    base = dict(long_qty=10, short_qty=10, base=10, anchor=100, mark=100, settings=THREE_OF_6,
                previous_steps=0, qty_step="0.001", min_qty=0, min_notional=0)
    base.update(kw)
    return plan(**base)


def go(record=None, **kw):
    args = dict(record=record, settings=THREE_OF_6, long_qty=10, short_qty=10, short_entry=100, mark=100,
                has_pending_short_order=False, qty_step="0.001", min_qty=0, min_notional=0,
                available_balance=100000, leverage=10)
    args.update(kw)
    return decide(**args)


class Sides(unittest.TestCase):
    def test_side_mapping(self):
        self.assertEqual((direction_for("LONG"), hedge_side_for("LONG")), ("DOWN", "SHORT"))
        self.assertEqual((direction_for("SHORT"), hedge_side_for("SHORT")), ("UP", "LONG"))


class MirroredLadder(unittest.TestCase):
    def test_levels_mirror(self):
        self.assertEqual([r["price"] for r in ladder(100, THREE_OF_6)], [D("98"), D("96"), D("94")])
        self.assertEqual([r["price"] for r in ladder(100, THREE_OF_6, "UP")], [D("102"), D("104"), D("106")])
        self.assertEqual(step_price(100, 1, 3, "6", "UP"), D("102"))

    def test_steps_reached_up_only_on_rising_price(self):
        self.assertEqual(steps_reached(100, 101, THREE_OF_6, direction="UP"), 0)
        self.assertEqual(steps_reached(100, 102, THREE_OF_6, direction="UP"), 1)
        self.assertEqual(steps_reached(100, "104.5", THREE_OF_6, direction="UP"), 2)
        self.assertEqual(steps_reached(100, 90, THREE_OF_6, direction="UP"), 0)      # falling price: nothing
        self.assertEqual(steps_reached(100, 103, THREE_OF_6, previous=2, direction="UP"), 2)  # never back

    def test_up_step_sells_a_third_of_the_long_hedge(self):
        r = run(mark=102, direction="UP", hedge_entry=100)
        self.assertEqual((r["action"], r["stepsReached"]), ("REDUCE_SHORT", 1))
        self.assertEqual(r["targetShort"], D("6.667"))

    def test_down_unchanged(self):
        r = run(mark=98, direction="DOWN", hedge_entry=100)
        self.assertEqual((r["action"], r["targetShort"]), ("REDUCE_SHORT", D("6.667")))


class AfterFees(unittest.TestCase):
    def test_profit_after_fees_both_sides(self):
        self.assertTrue(profitable_after_fees(direction="DOWN", hedge_entry=100, price=98))
        self.assertTrue(profitable_after_fees(direction="UP", hedge_entry=100, price=102))
        # 0.05% move: gross 0.05 < fees (200 * 0.0005 = 0.1) -> not profitable
        self.assertFalse(profitable_after_fees(direction="DOWN", hedge_entry=100, price="99.95"))
        self.assertFalse(profitable_after_fees(direction="UP", hedge_entry=100, price="100.05"))
        self.assertFalse(profitable_after_fees(direction="DOWN", hedge_entry=0, price=98))   # unknown entry

    def test_tiny_step_waits_until_profitable(self):
        tiny = {"enabled": True, "steps": 10, "totalPct": "0.5"}          # every 0.05%
        r = run(settings=tiny, mark="99.95", hedge_entry=100)
        self.assertEqual((r["action"], r["reason"], r["targetShort"]), ("HOLD", "STEP_WAIT_PROFIT_AFTER_FEES", D("10")))
        r = run(settings=tiny, mark="99.8", hedge_entry=100)               # 0.2% below entry: fees covered
        self.assertEqual(r["action"], "REDUCE_SHORT")

    def test_step_below_hedge_average_entry_waits(self):
        # Hedge average entry 97 (topped up at a lower price), step level 98 reached: selling there is a loss.
        r = run(mark=98, hedge_entry=97)
        self.assertEqual((r["action"], r["reason"]), ("HOLD", "STEP_WAIT_PROFIT_AFTER_FEES"))

    def test_runtime_keeps_hedge_when_waiting(self):
        # Build 629 (keuze B): the ladder measures from the live hedge entry, so a refilled hedge at 97 has no
        # step at 98 yet (was: level from the old anchor 100 touched, sale waits for profit).
        cycle = go(short_entry="100", mark="100")["record"]
        r = go(cycle, short_entry="97", mark="98")
        self.assertEqual((r["event"], r["override"], r["record"]["stepsReached"]), ("LADDER_HOLD", D("10"), 0))
        r = go(r["record"], short_entry="97", mark="96")                    # 1% below 97: still no full step
        self.assertEqual(r["record"]["anchor"], "97")


class RuntimeBothSides(unittest.TestCase):
    def test_up_cycle_and_steps(self):
        r = go(direction="UP")
        self.assertEqual((r["event"], r["record"]["direction"], r["record"]["anchor"]), ("CYCLE_STARTED", "UP", "100"))
        r = go(r["record"], mark=102, direction="UP")
        self.assertEqual((r["event"], r["override"]), ("STEP_REDUCE", D("6.667")))
        r = go(r["record"], short_qty="6.667", mark=101, direction="UP")    # falls back: no top-up
        self.assertEqual(r["override"], D("6.667"))
        r = go(r["record"], short_qty="6.667", mark=106, direction="UP")    # to the end: empty
        self.assertEqual(r["override"], D("0"))
        r = go(r["record"], short_qty=0, mark=106, direction="UP")
        self.assertEqual((r["event"], r["override"]), ("LADDER_DONE_REFILL_1_TO_1", None))  # 100% again

    def test_over_covered_never_starts_a_cycle(self):
        # Own position on the hedge side larger than the protected leg: no cycle, no target, nothing sold.
        r = go(short_qty=12, mark=98)
        self.assertEqual((r["event"], r["override"]), ("WAIT_FOR_1_TO_1", None))

    def test_plan_over_covered_keeps_hedge(self):
        r = run(short_qty=12, mark=98, hedge_entry=100)
        self.assertEqual((r["action"], r["targetShort"]), ("HOLD", D("12")))

    def test_rehedge_all_anchors_at_mark(self):
        refill = {"phase": "REFILL", "anchorAtMark": True, "cycleId": 3, "lastTarget": "10"}
        r = go(refill, short_entry="97.3", mark="99.1")
        self.assertEqual((r["record"]["anchor"], r["record"]["startReason"], r["record"]["cycleId"]),
                         ("99.1", "REHEDGE_ALL_AT_MARK", 4))

    def test_normal_refill_still_anchors_at_hedge_entry(self):
        r = go({"phase": "REFILL", "cycleId": 1, "lastTarget": "10"}, short_entry="97.3", mark="99.1")
        self.assertEqual(r["record"]["anchor"], "97.3")


if __name__ == "__main__":
    unittest.main()
