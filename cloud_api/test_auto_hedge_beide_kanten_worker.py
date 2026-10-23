"""Build 623 (Amar 23-10) — Auto Hedge for BOTH sides with the REAL worker tick (_run_uid).

Agreed rules (project doc auto-hedge-2-beide-kanten-plan-20261023.md):
 1. separate loss threshold for a LONG and a SHORT position; the other side is hedged exactly 1:1
 2. hedge afbouwen mirrored, separate settings per side (SHORT-hedge on a falling price, LONG-hedge on a rising one)
 3. a step only sells when profitable after fees
 4. TP closes both legs together and only when net positive, for every Auto Hedge pair
 5. Re-Hedge All puts everything back to 100% (also halfway the afbouw), next cycle anchored at that price
 8. vangnet: never sold to straighten a pair; a leg made smaller outside the app -> RECOVERY
Real: extension, engine, ladder, runtime, account lease. Mocked: Firestore (in-memory model), Aster (ledger).
No network, no credentials, no real orders.
"""
from __future__ import annotations

import unittest

import short_recovery_pair_exit as pair_exit
from test_rehedge_all_1_0 import HAVE, Base, HedgeClient, recovery_pair

SIX_IN_THREE = {"enabled": True, "steps": 3, "totalPct": "6"}


def hedged(symbol, protected, generation="g1", **extra):
    hedge = "SHORT" if protected == "LONG" else "LONG"
    return {"symbol": symbol, "status": "HEDGED", "protectedSide": protected, "hedgeSide": hedge,
            "generation": 1, "generationId": generation, "intentRevision": 0, "rehedgeEnabled": False, **extra}


@unittest.skipUnless(HAVE, "needs fastapi + aster_gateway deps")
class BothSides(Base):
    def setUp(self):
        super().setUp()
        self.ext.SHORT_RECOVERY_EXECUTION_ENABLED = True
        self.ext._hedge_mode_ok_at.clear()
        HedgeClient.income_history = lambda client, **kw: []
        self.addCleanup(lambda: delattr(HedgeClient, "income_history"))
        self.settings()

    def settings(self, **extra):
        doc = {"enabled": True, "thresholdUsd": 0.25, "thresholdShortUsd": 10.0}
        doc.update(extra)
        self.put("asterPositionLossAutoHedge", self.uid, doc)

    def open_pair(self, symbol, protected, qty=10.0, mark=100.0, protected_entry=None, hedge_entry=None):
        hedge = "SHORT" if protected == "LONG" else "LONG"
        self.L.add(symbol, protected, qty, mark=mark,
                   entry=protected_entry if protected_entry is not None else (mark + 1 if protected == "LONG" else mark - 1))
        self.L.pos[(symbol, hedge)] = float(qty)
        self.L.entry[(symbol, hedge)] = float(hedge_entry if hedge_entry is not None else mark)
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", symbol, hedged(symbol, protected))

    def at(self, symbol, mark):
        self.L.mark[symbol] = float(mark)
        report = self.worker_tick()
        self.assertTrue(self.lease_free())
        return report

    def orders(self, symbol=None):
        return [(o["positionSide"], o["action"], round(o["qty"], 9))
                for o in self.L.hedge_orders if symbol in (None, o["symbol"])]

    # 1 ---------------------------------------------------------------------------------------------------
    def test_losing_short_entry_gets_an_exact_long_hedge_at_its_own_threshold(self):
        self.L.add("ABCUSDT", "SHORT", 4.0, mark=100.0, entry=98.0)          # -$8: below the SHORT threshold
        self.worker_tick()
        self.assertEqual(self.orders(), [])                                  # $10 for SHORT, not $0.25
        self.L.mark["ABCUSDT"] = 103.0                                       # -$20
        self.worker_tick()
        self.assertEqual(self.orders(), [("LONG", "OPEN", 4.0)])
        pair = self.pair("ABCUSDT")
        self.assertEqual((pair["protectedSide"], pair["hedgeSide"], pair["triggerThresholdUsd"]), ("SHORT", "LONG", 10.0))

    def test_losing_long_entry_still_uses_the_long_threshold(self):
        self.L.add("XYZUSDT", "LONG", 2.0, mark=100.0, entry=100.2)           # -$0.40
        self.worker_tick()
        self.assertEqual(self.orders(), [("SHORT", "OPEN", 2.0)])

    def test_threshold_settings_saved_separately(self):
        from fastapi import Response
        self.ext.put_position_loss_auto_hedge(
            self.ext.AutoHedgeSettingsRequest(enabled=True, thresholdUsd=0.25, thresholdShortUsd=3.5),
            Response(), {"uid": self.uid})
        doc = self.get("asterPositionLossAutoHedge", self.uid)
        self.assertEqual((doc["thresholdUsd"], doc["thresholdShortUsd"]), (0.25, 3.5))
        out = self.ext.put_position_loss_auto_hedge(                         # old client: SHORT value kept
            self.ext.AutoHedgeSettingsRequest(enabled=True, thresholdUsd=0.5), Response(), {"uid": self.uid})
        self.assertEqual((out["thresholdLongUsd"], out["thresholdShortUsd"]), (0.5, 3.5))

    # 2 ---------------------------------------------------------------------------------------------------
    def test_long_hedge_of_a_short_is_reduced_on_a_rising_price(self):
        self.settings(longRecoveryPlan=dict(SIX_IN_THREE))
        self.open_pair("SOLUSDT", "SHORT", hedge_entry=100)                 # LONG hedge entry 100
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 102)                                             # step 1 (+2%)
        self.assertEqual(self.orders(), [("LONG", "CLOSE", 3.333)])
        self.at("SOLUSDT", 101)                                             # falls back: no top-up
        self.assertEqual(len(self.orders()), 1)
        self.at("SOLUSDT", 106)                                             # to the end: LONG hedge empty
        self.assertAlmostEqual(self.long("SOLUSDT"), 0.0)
        self.assertEqual(self.short("SOLUSDT"), 10.0)                       # the protected SHORT is never touched
        self.at("SOLUSDT", 106)                                             # empty -> 100% again
        self.assertAlmostEqual(self.long("SOLUSDT"), 10.0)
        self.assertTrue(all(side == "LONG" for side, _, _ in self.orders()))

    def test_settings_are_per_side(self):
        self.settings(shortRecoveryPlan=dict(SIX_IN_THREE))                 # only SHORT-hedge afbouwen ON
        self.open_pair("SOLUSDT", "SHORT", hedge_entry=100)
        self.open_pair("ETHUSDT", "LONG", hedge_entry=100)
        self.at("SOLUSDT", 100); self.L.mark["ETHUSDT"] = 100.0
        self.L.mark["SOLUSDT"] = 104.0; self.L.mark["ETHUSDT"] = 96.0
        self.worker_tick()
        self.assertEqual(self.orders("SOLUSDT"), [])                       # LONG-hedge afbouwen is OFF
        self.assertEqual(self.orders("ETHUSDT"), [("SHORT", "CLOSE", 6.666)])

    def test_settings_route_per_side(self):
        from fastapi import Response
        out = self.ext.put_position_loss_auto_hedge_short_recovery(
            self.ext.ShortRecoverySettingsRequest(enabled=True, steps=5, totalPct="10", hedgeSide="LONG"),
            Response(), {"uid": self.uid})
        self.assertEqual(out["longRecoveryPlan"]["steps"], 5)
        self.assertFalse(out["shortRecoveryPlan"]["enabled"])                # default OFF, untouched
        self.assertEqual(self.L.hedge_orders, [])

    # 3 ---------------------------------------------------------------------------------------------------
    def test_step_waits_when_not_profitable_after_fees(self):
        self.settings(shortRecoveryPlan={"enabled": True, "steps": 3, "totalPct": "6"})
        self.open_pair("SOLUSDT", "LONG", hedge_entry=100)                 # cycle anchored at 100
        self.at("SOLUSDT", 100)
        self.L.entry[("SOLUSDT", "SHORT")] = 97.0                          # later the SHORT average became 97
        self.at("SOLUSDT", 98)                                              # step level reached, but 98 > 97
        self.assertEqual(self.orders(), [])
        self.at("SOLUSDT", 96)                                              # now profitable: 2 steps at once
        self.assertEqual(self.orders(), [("SHORT", "CLOSE", 6.666)])

    # 4 ---------------------------------------------------------------------------------------------------
    def test_short_tp_closes_both_when_net_positive(self):
        self.settings(longRecoveryPlan=dict(SIX_IN_THREE))
        self.open_pair("SOLUSDT", "SHORT", protected_entry=120, hedge_entry=100)
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 102)                                             # LONG hedge 6.667 left
        self.L.mark["SOLUSDT"] = 90.0                                       # SHORT +300, LONG hedge -66.67
        self.assertEqual(pair_exit.pair_tp_gate(account_uid=self.uid, symbol="SOLUSDT", side="SHORT",
                                                opposite_qty=self.long("SOLUSDT"))[0], "WAIT")
        self.worker_tick()
        self.assertAlmostEqual(self.long("SOLUSDT"), 0.0)
        self.assertEqual(self.short("SOLUSDT"), 10.0)
        self.assertEqual(pair_exit.pair_tp_gate(account_uid=self.uid, symbol="SOLUSDT", side="SHORT", opposite_qty=0),
                         ("ALLOW", "OPPOSITE_FLAT_JOINT_EXIT"))
        self.worker_tick()                                                  # hedge stays flat while TP runs
        self.assertAlmostEqual(self.long("SOLUSDT"), 0.0)

    def test_plain_hedge_with_afbouwen_off_never_closes_net_negative(self):
        self.open_pair("SOLUSDT", "LONG", protected_entry=100.5, hedge_entry=100)   # exact 1:1, net about -$5
        self.at("SOLUSDT", 100)
        self.L.mark["SOLUSDT"] = 130.0
        self.assertEqual(pair_exit.long_tp_gate(account_uid=self.uid, symbol="SOLUSDT", short_qty=10)[0], "WAIT")
        self.worker_tick()
        self.assertEqual(self.orders(), [])                                 # net not positive: wait, keep both
        self.assertEqual(self.short("SOLUSDT"), 10.0)
        self.assertIsNone(self.pair("SOLUSDT").get("pairExit"))

    def test_recovery_pair_with_both_legs_exits_jointly(self):
        # Manual 25% SHORT close earlier -> RECOVERY with LONG 10 / SHORT 7.5; LONG TP later, net positive.
        self.L.add("XRPUSDT", "LONG", 10.0, mark=120.0, entry=100.0)        # +200
        self.L.pos[("XRPUSDT", "SHORT")] = 7.5
        self.L.entry[("XRPUSDT", "SHORT")] = 101.0                          # -142.5
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "XRPUSDT",
                 {**recovery_pair("XRPUSDT", survivor="LONG"),
                  "triggerAt": __import__("datetime").datetime(2026, 10, 22, tzinfo=__import__("datetime").timezone.utc)})
        self.assertEqual(pair_exit.long_tp_gate(account_uid=self.uid, symbol="XRPUSDT", short_qty=7.5)[0], "WAIT")
        self.worker_tick()
        self.assertEqual(self.orders(), [("SHORT", "CLOSE", 7.5)])
        self.assertEqual(self.long("XRPUSDT"), 10.0)
        self.assertEqual(pair_exit.long_tp_gate(account_uid=self.uid, symbol="XRPUSDT", short_qty=0)[0], "ALLOW")

    # 5 ---------------------------------------------------------------------------------------------------
    def test_rehedge_all_tops_up_a_half_reduced_pair_and_restarts_at_that_price(self):
        self.settings(shortRecoveryPlan=dict(SIX_IN_THREE))
        self.open_pair("SOLUSDT", "LONG", hedge_entry=100)
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 98)                                              # SHORT 6.667 (HEDGED 67%)
        self.L.mark["SOLUSDT"] = 99.0
        result = self.press()
        self.assertEqual(self.item(result, "SOLUSDT")["outcome"], "PROTECTED")
        self.assertAlmostEqual(self.short("SOLUSDT"), 10.0)
        self.at("SOLUSDT", 99)
        rec = self.pair("SOLUSDT")["shortRecovery"]
        self.assertEqual((rec["phase"], rec["anchor"], rec["startReason"]), ("LADDER", "99", "REHEDGE_ALL_AT_MARK"))

    def test_rehedge_all_survivor_short(self):
        self.L.add("ABCUSDT", "SHORT", 5.0, mark=100.0, entry=105.0)
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "ABCUSDT", recovery_pair("ABCUSDT", survivor="SHORT"))
        self.press()
        self.assertEqual(self.orders(), [("LONG", "OPEN", 5.0)])

    # 8 ---------------------------------------------------------------------------------------------------
    def test_own_larger_short_is_never_sold(self):
        self.L.add("DOGEUSDT", "LONG", 10.0, mark=100.0, entry=101.0)       # -$10
        self.L.pos[("DOGEUSDT", "SHORT")] = 12.0
        self.L.entry[("DOGEUSDT", "SHORT")] = 101.0                         # own SHORT (in profit) already covers it
        self.worker_tick()
        self.worker_tick()
        self.assertEqual(self.orders(), [])
        self.assertEqual(self.short("DOGEUSDT"), 12.0)

    def test_own_smaller_short_is_only_topped_up(self):
        self.L.add("DOGEUSDT", "LONG", 10.0, mark=100.0, entry=101.0)
        self.L.pos[("DOGEUSDT", "SHORT")] = 4.0
        self.L.entry[("DOGEUSDT", "SHORT")] = 99.0
        self.worker_tick()
        self.assertEqual(self.orders(), [("SHORT", "OPEN", 6.0)])

    def test_protected_leg_reduced_outside_the_app_goes_to_recovery(self):
        self.open_pair("SOLUSDT", "LONG")
        self.at("SOLUSDT", 100)                                             # synced: 10 / 10
        self.L.pos[("SOLUSDT", "LONG")] = 7.0                               # closed 3 on the Aster website
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 100)
        pair = self.pair("SOLUSDT")
        self.assertEqual((pair["status"], pair["lastReason"]), ("RECOVERY", "PROTECTED_REDUCED_OUTSIDE_APP"))
        self.assertEqual(self.orders(), [])                                 # SHORT 10 not sold
        self.assertEqual(self.short("SOLUSDT"), 10.0)

    def test_hedge_reduced_outside_the_app_goes_to_recovery_until_rehedge_all(self):
        self.open_pair("SOLUSDT", "LONG")
        self.at("SOLUSDT", 100)
        self.L.pos[("SOLUSDT", "SHORT")] = 6.0                              # closed 4 SHORT on the website
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 99)
        pair = self.pair("SOLUSDT")
        self.assertEqual((pair["status"], pair["lastReason"]), ("RECOVERY", "HEDGE_REDUCED_OUTSIDE_APP"))
        self.assertEqual(self.orders(), [])                                 # not topped up by itself
        self.press()
        self.assertEqual(self.orders(), [("SHORT", "OPEN", 4.0)])           # Re-Hedge All: LONG protected again

    def test_own_afbouw_step_with_lagging_positions_is_not_outside_the_app(self):
        self.settings(shortRecoveryPlan=dict(SIX_IN_THREE))
        self.open_pair("SOLUSDT", "LONG", hedge_entry=100)
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 98)                                              # own step: SHORT 10 -> 6.667
        pair = self.pair("SOLUSDT")
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "SOLUSDT", {**pair, "currentHedgeQty": 10.0})  # stale view
        self.at("SOLUSDT", "97.9")
        self.assertEqual(self.pair("SOLUSDT")["status"], "HEDGED")
        self.assertEqual(len(self.orders()), 1)

    def test_new_cycle_never_inherits_an_old_joint_exit(self):
        self.L.add("NEWUSDT", "LONG", 10.0, mark=100.0, entry=101.0)        # -$10 -> new cycle
        old = {"symbol": "NEWUSDT", "status": "CLOSED", "generation": 3, "generationId": "g3",
               "pairExit": {"phase": "CLOSING_OPPOSITE", "tpSide": "LONG"}}
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "NEWUSDT", old)
        self.worker_tick()
        self.worker_tick()
        self.assertEqual(self.orders(), [("SHORT", "OPEN", 10.0)])          # hedged, never closed again
        self.assertIsNone(self.pair("NEWUSDT").get("pairExit"))
        self.assertEqual(self.short("NEWUSDT"), 10.0)

    def test_one_position_per_coin_reader_follows_auto_hedge_switch(self):
        import aster_position_loss_auto_hedge_lock as lock
        self.ext._enabled_cache.clear()
        self.assertTrue(lock.one_position_per_coin_active(self.uid))
        self.put("asterPositionLossAutoHedge", "u9", {"enabled": False})
        self.assertFalse(lock.one_position_per_coin_active("u9"))


@unittest.skipUnless(HAVE, "needs fastapi + aster_gateway deps")
class RealOrdersDefault(unittest.TestCase):
    def test_short_recovery_executes_by_default_and_env_false_is_the_emergency_stop(self):
        from pathlib import Path
        src = (Path(__file__).parent / "aster_position_loss_auto_hedge_extension.py").read_text()
        self.assertIn('os.getenv("ASTER_SHORT_RECOVERY_EXECUTION_ENABLED", "true").lower() == "true"', src)


class EntryGateSource(unittest.TestCase):
    def test_bot_skips_an_opposite_side_entry_when_auto_hedge_is_on(self):
        from pathlib import Path
        core = (Path(__file__).parent / "aster_multi_bb_core.py").read_text()
        gate = core[core.index("if one_position_per_coin_active(uid):"):core.index("paired = bool(settings.asymmetric_hedge_enabled)")]
        for needle in ('opposite_key in active', 'opposite_key in pmap', 'coin_managed',
                       '"ONE_POSITION_PER_COIN_AUTO_HEDGE"', "continue"):
            self.assertIn(needle, gate)
        self.assertIn("pair_tp_gate(account_uid=uid, symbol=symbol, side=side", core)


if __name__ == "__main__":
    unittest.main()
