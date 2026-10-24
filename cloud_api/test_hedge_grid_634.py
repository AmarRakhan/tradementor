"""Build 634 (Amar 23-10) — grid on the hedge. Pure (ladder + runtime) and real worker tick.

Rules: away from the anchor sell one part per level (profit after fees only); back ``rebuySteps`` levels above the
last sold part buy it back; everything sold and ``safetyNetPct`` beyond the last level -> re-hedge 100% (vangnet).
Small coins use fewer, larger parts (each one Aster minimum order or more); no close-all / reopen-90 any more.
"""
from __future__ import annotations

import unittest
from decimal import Decimal as D

from short_recovery_ladder import effective_parts, grid_step, normalize_settings
from short_recovery_runtime import decide
from test_rehedge_all_1_0 import HAVE, Base, HedgeClient

SIX = {"enabled": True, "steps": 3, "totalPct": "6"}


def go(record=None, **kw):
    args = dict(record=record, settings=SIX, long_qty=10, short_qty=10, short_entry=100, mark=100,
                has_pending_short_order=False, qty_step="0.001", min_qty=0, min_notional=0,
                available_balance=100000, leverage=10)
    args.update(kw)
    return decide(**args)


def walk(prices, settings=SIX, direction="DOWN", **kw):
    r = go(settings=settings, direction=direction, **kw)
    rec, short, out = r["record"], D(str(kw.get("short_qty", 10))), []
    for p in prices:
        r = go(rec, settings=settings, direction=direction, short_qty=short, mark=p,
               **{k: v for k, v in kw.items() if k != "short_qty"})
        rec = r["record"]
        if r["override"] is not None:
            short = r["override"]
        out.append((p, float(short), r["event"]))
    return out, rec


class Settings(unittest.TestCase):
    def test_defaults(self):
        cfg = normalize_settings({"enabled": True, "steps": 3, "totalPct": "6"})
        self.assertEqual((cfg["rebuySteps"], cfg["safetyNetPct"]), (1, "6"))
        cfg = normalize_settings({"enabled": True, "steps": 10, "totalPct": "20", "rebuySteps": 2, "safetyNetPct": "8"})
        self.assertEqual((cfg["rebuySteps"], cfg["safetyNetPct"]), (2, "8"))
        for bad in ({"rebuySteps": -1}, {"safetyNetPct": "0"}, {"safetyNetPct": "100"}, {"rebuySteps": True}):
            with self.assertRaises(ValueError):
                normalize_settings({"enabled": True, "steps": 3, "totalPct": "6", **bad})


class GridPure(unittest.TestCase):
    def test_example_path_from_the_picture(self):
        a = dict(anchor=100, n=3, total_pct="6", rebuy_steps=1, safety_pct="6", hedge_entry=100)
        sold, seen = 0, []
        for p in (98, 96, 98, 96, 94, 96, 98, 100):
            r = grid_step(price=p, sold=sold, **a)
            sold = r["sold"]
            seen.append(sold)
        self.assertEqual(seen, [1, 2, 1, 2, 3, 2, 1, 0])

    def test_no_ping_pong_on_one_level(self):
        a = dict(anchor=100, n=3, total_pct="6", rebuy_steps=1, safety_pct="6", hedge_entry=100)
        self.assertEqual(grid_step(price=98, sold=0, **a)["sold"], 1)
        for p in (98, "97.5", "98.5", "99.9", 98):
            self.assertEqual(grid_step(price=p, sold=1, **a)["sold"], 1)          # rebuy only at 100

    def test_rebuy_two_levels(self):
        a = dict(anchor=100, n=3, total_pct="6", rebuy_steps=2, safety_pct="6", hedge_entry=100)
        self.assertEqual(grid_step(price=98, sold=3, **a)["sold"], 2)            # part sold at 94 back at 98
        self.assertEqual(grid_step(price=96, sold=3, **a)["sold"], 3)

    def test_up_mirror(self):
        a = dict(anchor=100, n=3, total_pct="6", rebuy_steps=1, safety_pct="6", hedge_entry=100, direction="UP")
        self.assertEqual(grid_step(price=102, sold=0, **a)["sold"], 1)
        self.assertEqual(grid_step(price=98, sold=0, **a)["sold"], 0)
        self.assertEqual(grid_step(price=100, sold=1, **a)["sold"], 0)
        self.assertEqual(grid_step(price="112.4", sold=3, **a)["event"], "SAFETY_NET_REHEDGE")

    def test_sale_waits_until_profitable_after_fees(self):
        a = dict(anchor=100, n=3, total_pct="6", rebuy_steps=1, safety_pct="6")
        self.assertEqual(grid_step(price=98, sold=0, hedge_entry=97, **a)["event"], "STEP_WAIT_PROFIT_AFTER_FEES")
        self.assertEqual(grid_step(price=96, sold=0, hedge_entry=97, **a)["sold"], 2)

    def test_small_coin_gets_fewer_larger_parts(self):
        self.assertEqual(effective_parts(10, 3, 100, "0.001", 0, 5), 3)          # $333 per part
        self.assertEqual(effective_parts("0.09", 10, 100, "0.01", 0, 5), 1)      # $9: one part only
        self.assertEqual(effective_parts("0.12", 10, 100, "0.01", 0, 5), 2)
        self.assertEqual(effective_parts("0.04", 3, 100, "0.01", 0, 5), 0)       # below one Aster order


class GridRuntime(unittest.TestCase):
    def test_full_wave_down_and_up(self):
        out, rec = walk([98, 96, 94, 96, 98, 100])
        self.assertEqual([s for _, s, _ in out], [6.667, 3.334, 0.0, 3.334, 6.667, 10.0])
        self.assertEqual(rec["phase"], "LADDER")                                  # no refill at the bottom

    def test_vangnet_rehedges_and_new_cycle_at_that_price(self):
        out, rec = walk([94, 88])
        self.assertEqual(out[-1][2], "SAFETY_NET_REHEDGE")
        self.assertEqual((rec["phase"], rec.get("anchorAtMark")), ("REFILL", True))
        r = go(rec, short_qty=10, mark=88, short_entry="88.2")
        self.assertEqual((r["event"], r["record"]["anchor"]), ("CYCLE_STARTED", "88"))

    def test_small_coin_unwinds_without_close_all(self):
        out, rec = walk([98, 96, 94], long_qty="0.09", short_qty="0.09", qty_step="0.01", min_notional=5)
        self.assertEqual(rec["gridParts"], 1)
        self.assertEqual([s for _, s, _ in out], [0.09, 0.09, 0.0])               # whole hedge at the last level
        self.assertNotIn("CLOSE", " ".join(e for _, _, e in out if "CLOSE" in e and "ALL" in e))

    def test_mirrored_long_hedge(self):
        out, _ = walk([102, 104, 102, 100], direction="UP")
        self.assertEqual([s for _, s, _ in out], [6.667, 3.334, 6.667, 10.0])

    def test_dca_on_protected_leg_stays_hedged(self):
        out, rec = walk([98])
        r = go(rec, long_qty=15, short_qty="6.667", mark=98)
        self.assertEqual(r["override"], D("11.667"))

    def test_settings_change_keeps_hedge_and_recounts(self):
        _, rec = walk([96])                                                       # 2 of 3 sold: hedge 3.334
        r = go(rec, settings={"enabled": True, "steps": 6, "totalPct": "6"}, short_qty="3.334", mark=96)
        self.assertEqual((r["record"]["sold"], r["override"]), (4, D("3.334")))  # 4 of 6 = same hedge

    def test_legacy_reopen_record_goes_back_to_refill(self):
        r = go({"phase": "REOPEN_CLOSE", "reopenQty": "9", "cycleId": 1}, short_qty=4, mark=98)
        self.assertEqual((r["event"], r["record"]["phase"], r["override"]), ("REOPEN_PHASE_REPLACED_BY_GRID", "REFILL", None))

    def test_pre_634_ladder_record_continues_as_grid(self):
        old = {"phase": "LADDER", "cycleId": 3, "anchor": "100", "base": "10", "longAtStart": "10",
               "stepsReached": 1, "steps": 3, "totalPct": "6", "lastTarget": "6.667"}
        r = go(old, short_qty="6.667", mark=99)
        self.assertEqual((r["record"]["sold"], r["override"]), (1, D("6.667")))
        r = go(r["record"], short_qty="6.667", mark=100)
        self.assertEqual(r["override"], D("10"))


@unittest.skipUnless(HAVE, "needs fastapi + aster_gateway deps")
class GridWorker(Base):
    def setUp(self):
        super().setUp()
        self.ext.SHORT_RECOVERY_EXECUTION_ENABLED = True
        self.ext._hedge_mode_ok_at.clear()
        HedgeClient.income_history = lambda client, **kw: []
        self.addCleanup(lambda: delattr(HedgeClient, "income_history"))

    def setup_pair(self, protected="LONG", plan=None, qty=10.0):
        hedge = "SHORT" if protected == "LONG" else "LONG"
        field = "shortRecoveryPlan" if protected == "LONG" else "longRecoveryPlan"
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": True, "thresholdUsd": 0.25,
                                                            "thresholdShortUsd": 10.0, field: dict(plan or SIX)})
        self.L.add("SOLUSDT", protected, qty, mark=100.0, entry=101.0 if protected == "LONG" else 99.0)
        self.L.pos[("SOLUSDT", hedge)] = qty
        self.L.entry[("SOLUSDT", hedge)] = 100.0
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "SOLUSDT",
                 {"symbol": "SOLUSDT", "status": "HEDGED", "protectedSide": protected, "hedgeSide": hedge,
                  "generation": 1, "generationId": "g1", "intentRevision": 0, "rehedgeEnabled": False})

    def at(self, mark):
        self.L.mark["SOLUSDT"] = float(mark)
        self.worker_tick()
        self.assertTrue(self.lease_free())

    def orders(self):
        return [(o["positionSide"], o["action"], round(o["qty"], 3)) for o in self.L.hedge_orders]

    def test_wave_sells_down_and_buys_back_up(self):
        self.setup_pair()
        for p in (100, 98, 96, 98, 100):
            self.at(p)
        self.assertEqual(self.orders(), [("SHORT", "CLOSE", 3.333), ("SHORT", "CLOSE", 3.333),
                                         ("SHORT", "OPEN", 3.333), ("SHORT", "OPEN", 3.333)])
        self.assertAlmostEqual(self.short("SOLUSDT"), 10.0)
        self.assertEqual(self.long("SOLUSDT"), 10.0)                            # protected leg never touched

    def test_mirrored_long_hedge_on_rising_price(self):
        self.setup_pair(protected="SHORT")
        for p in (100, 102, 104, 102):
            self.at(p)
        self.assertEqual([o[:2] for o in self.orders()], [("LONG", "CLOSE"), ("LONG", "CLOSE"), ("LONG", "OPEN")])

    def test_vangnet_in_the_worker(self):
        self.setup_pair()
        for p in (100, 94, 94, 88, 88):
            self.at(p)
        self.assertAlmostEqual(self.short("SOLUSDT"), 10.0)                     # re-hedged 100% at 88
        self.L.entry[("SOLUSDT", "SHORT")] = 88.0
        self.at(88)
        self.assertEqual(self.pair("SOLUSDT")["shortRecovery"]["anchor"], "88")


if __name__ == "__main__":
    unittest.main()
