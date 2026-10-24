"""Build 651 (Amar 24-10): kleine posities ($1 inleg x 20 = $20) en "hedge mag groter dan positie".

- Het aantal afbouwstappen wordt bepaald op de koers van de laagste stap (een deel van $5 is na 10% daling $4,50).
- Terugzetten of noodrem onder het Aster-minimum: dan het hele deel / het minimum, nooit een onmogelijke order.
- Max hedge boven 100% alleen met de schakelaar; anders telt alles boven 100 als 100.
"""
from __future__ import annotations

import unittest
from decimal import Decimal as D
from types import SimpleNamespace

from aster_position_loss_auto_hedge import evaluate_auto_hedge
from test_hedge_grid_634 import go, walk
from test_max_hedge_verdeling_647 import _pos
from test_rehedge_all_1_0 import HAVE, Base

SMALL = dict(long_qty="0.2", short_qty="0.2", qty_step="0.001", min_notional=5)       # $20 at price 100


class SmallPositions(unittest.TestCase):
    def test_equal_steps_fit_at_the_bottom_price(self):
        r = go(None, settings={"enabled": True, "steps": 5, "totalPct": "10"}, mark=100, **SMALL)
        r = go(r["record"], settings={"enabled": True, "steps": 5, "totalPct": "10"}, mark=100, **SMALL)
        self.assertEqual(r["record"]["gridParts"], 3)          # 4 parts of $5 would be $4.50 at -10%

    def test_ascending_small_position_gets_two_steps(self):
        st = {"enabled": True, "steps": 5, "totalPct": "10", "distribution": "ASCENDING"}
        r = go(None, settings=st, mark=100, **SMALL)
        r = go(r["record"], settings=st, mark=100, **SMALL)
        self.assertEqual(r["record"]["gridParts"], 2)

    def test_rebuy_below_minimum_restores_the_whole_part(self):
        st = {"enabled": True, "steps": 5, "totalPct": "10", "rehedgePct": "75"}
        out, rec = walk([96, 100], settings=st, **SMALL)
        self.assertEqual([s for _, s, _ in out], [0.134, 0.2])     # 75% of $6.67 = $4.95 < $5 -> whole part back
        self.assertEqual(rec["kept"], "0")

    def test_every_sell_is_sendable_at_its_own_price(self):
        st = {"enabled": True, "steps": 5, "totalPct": "10", "distribution": "ASCENDING"}
        out, _ = walk([98, 96, 94, 92, 90], settings=st, **SMALL)
        prev = 0.2
        for price, short, _ in out:
            sold = round(prev - short, 6)
            if sold > 0:
                self.assertGreaterEqual(sold * price, 5 - 1e-9, (price, sold))
            prev = short


class AboveThePosition(unittest.TestCase):
    def test_runtime_allows_up_to_the_max_share(self):
        r = go(None, short_qty=0, mark=100, max_hedge="1.2")
        self.assertEqual((r["event"], r["override"]), ("WAIT_FOR_REHEDGE_PCT", D("12")))
        r = go(None, short_qty=12, mark=100, max_hedge="1.2")
        self.assertEqual((r["event"], r["record"]["base"]), ("CYCLE_STARTED", "12"))

    def test_runtime_never_above_two_times(self):
        r = go(None, short_qty=0, mark=100, max_hedge="5")
        self.assertEqual(r["override"], D("20"))


@unittest.skipUnless(HAVE, "needs aster_gateway deps")
class EngineAndSettings(unittest.TestCase):
    def test_engine_opens_above_the_position_only_with_a_cap_above(self):
        rows = [_pos("SOLUSDT", "LONG", 10, 100, 101)]
        a = evaluate_auto_hedge(rows, 0.25, max_caps={("SOLUSDT", "LONG"): 12.0})[0]
        self.assertEqual((a.operation, a.target_qty, round(a.delta_qty, 9)), ("OPEN", 12.0, 2.0 + 10.0))
        a = evaluate_auto_hedge(rows, 0.25)[0]
        self.assertEqual(a.target_qty, 10.0)

    def test_bigger_existing_hedge_is_kept(self):
        rows = [_pos("SOLUSDT", "LONG", 10, 100, 101), _pos("SOLUSDT", "SHORT", 13, 100, 100)]
        a = evaluate_auto_hedge(rows, 0.25, max_caps={("SOLUSDT", "LONG"): 12.0})[0]
        self.assertEqual(a.operation, "HOLD")


@unittest.skipUnless(HAVE, "needs fastapi + aster_gateway deps")
class Switch(Base):
    def test_switch_controls_above_100(self):
        ext = self.ext
        self.assertEqual(ext._max_pct(150), 100.0)
        self.assertEqual(ext._max_pct(150, True), 150.0)
        self.assertEqual(ext._max_pct(300, True), 200.0)
        req = SimpleNamespace(allowHedgeAbovePosition=None, maxHedgePct=150, maxHedgeShortPct=None)
        with self.assertRaises(Exception) as ctx:
            ext._max_hedge_update({}, req)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 422)
        req = SimpleNamespace(allowHedgeAbovePosition=True, maxHedgePct=150, maxHedgeShortPct=None)
        self.assertEqual(ext._max_hedge_update({}, req),
                         {"allowHedgeAbovePosition": True, "maxHedgePct": 150.0, "maxHedgeShortPct": 100.0})
        off = ext._max_hedge_by_side({"maxHedgePct": 150, "allowHedgeAbovePosition": False})
        self.assertEqual(off["LONG"], 1.0)                      # switch off later: back to max 100%


if __name__ == "__main__":
    unittest.main()


from test_hedge_grid_634 import GridWorker  # noqa: E402


class WorkerAbove(GridWorker):
    test_wave_sells_down_and_buys_back_up = None
    test_mirrored_long_hedge_on_rising_price = None
    test_vangnet_in_the_worker = None
    def _trigger(self, extra):
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": True, "thresholdUsd": 0.25,
                                                            "thresholdShortUsd": 10.0, **extra})
        self.L.add("SOLUSDT", "LONG", 10.0, mark=100.0, entry=101.0)
        self.at(100)
        self.at(100)

    def test_above_position_only_with_the_switch(self):
        self._trigger({"maxHedgePct": 120, "allowHedgeAbovePosition": True})
        self.assertEqual(self.orders(), [("SHORT", "OPEN", 12.0)])

    def test_stored_120_without_switch_stays_one_to_one(self):
        self._trigger({"maxHedgePct": 120})
        self.assertEqual(self.orders(), [("SHORT", "OPEN", 10.0)])
