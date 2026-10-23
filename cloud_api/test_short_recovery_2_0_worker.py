"""SHORT Recovery 2.0 — the REAL Auto Hedge worker tick (_run_uid) with the ladder wired in.

Real: aster_position_loss_auto_hedge_extension, the engine, ContractRules, account lease.
Mocked: Firestore (in-memory model), Aster (ledger). No network, no credentials, no real orders.
"""
from __future__ import annotations

import unittest

from datetime import datetime, timezone

import short_recovery_pair_exit as pair_exit
from test_rehedge_all_1_0 import HAVE, Base, HedgeClient

PLAN = {"enabled": True, "steps": 4, "stepPct": "2"}


def hedged_pair(symbol, generation="g1"):
    return {"symbol": symbol, "status": "HEDGED", "protectedSide": "LONG", "hedgeSide": "SHORT",
            "generation": 1, "generationId": generation, "intentRevision": 0, "rehedgeEnabled": False}


@unittest.skipUnless(HAVE, "needs fastapi + aster_gateway deps")
class Recovery(Base):
    LIVE = True

    def setUp(self):
        super().setUp()
        self.ext.SHORT_RECOVERY_EXECUTION_ENABLED = self.LIVE
        self.settings(PLAN)

    def settings(self, plan):
        self.put("asterPositionLossAutoHedge", self.uid,
                 {"enabled": True, "thresholdUsd": 0.25, "shortRecoveryPlan": dict(plan)})  # copy: the model store merges in place

    def open_pair(self, symbol, qty=10.0, mark=100.0, minimum=0.001, step=0.001):
        self.L.add(symbol, "LONG", qty, mark=mark, entry=mark + 1, minimum=minimum, step=step)
        self.L.pos[(symbol, "SHORT")] = float(qty)
        self.L.entry[(symbol, "SHORT")] = mark
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", symbol, hedged_pair(symbol))

    def at(self, symbol, mark):
        self.L.mark[symbol] = float(mark)
        report = self.worker_tick()
        self.check_invariant()
        return report

    def orders(self, symbol=None):
        return [(o["action"], round(o["qty"], 9)) for o in self.L.hedge_orders if symbol in (None, o["symbol"])]

    def rec(self, symbol, field="shortRecovery"):
        return self.pair(symbol).get(field) or {}

    def check_invariant(self):
        for (symbol, side), qty in self.L.pos.items():
            if side == "SHORT":
                self.assertLessEqual(qty, self.long(symbol) + 1e-9, f"{symbol}: SHORT {qty} > LONG")
        for order in self.L.hedge_orders:
            self.assertEqual(order["positionSide"], "SHORT", order)      # never a LONG order
        self.assertTrue(self.lease_free())


class LiveLadder(Recovery):

    def test_quiet_ticks_do_not_rewrite_the_record(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 98)
        self.at("SOLUSDT", "98.5")                                    # event changes once: STEP -> HOLD
        first = dict(self.rec("SOLUSDT"))
        for _ in range(5):
            self.at("SOLUSDT", "98.5")                                # nothing changes
        self.assertEqual(self.rec("SOLUSDT")["evaluatedAt"], first["evaluatedAt"])

    def test_old_hedge_anchors_at_hedge_moment_and_catches_up(self):
        # Amar 21:36: the ladder counts from the hedge moment (SHORT entry), also for hedges that existed
        # before switching ON. A coin already 6% below the hedge price reduces 2 steps at once (one order).
        self.open_pair("SOLUSDT")                                      # SHORT entry 100
        self.at("SOLUSDT", 94)
        self.assertEqual(self.rec("SOLUSDT")["anchor"], "100")
        self.at("SOLUSDT", 94)
        self.assertEqual(self.orders(), [("CLOSE", 7.5)])            # steps 1-3 (98/96/94) in one order

    def test_records_anchored_at_switch_on_are_restarted(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        doc = self.pair("SOLUSDT")
        old = {**doc["shortRecovery"], "anchor": "90", "startReason": "ANCHOR_AT_SWITCH_ON"}
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "SOLUSDT", {**doc, "shortRecovery": old})
        self.at("SOLUSDT", 98)
        self.assertEqual(self.rec("SOLUSDT")["anchor"], "100")

    def test_gap_down_combines_steps_in_one_order(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 95)
        self.assertEqual(self.orders(), [("CLOSE", 5.0)])

    def test_switching_off_restores_full_hedge(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 96)
        self.assertAlmostEqual(self.short("SOLUSDT"), 5.0)
        self.settings({**PLAN, "enabled": False})
        self.at("SOLUSDT", 96)
        self.assertAlmostEqual(self.short("SOLUSDT"), 10.0)
        self.assertEqual(self.rec("SOLUSDT"), {})

    def test_new_auto_hedge_generation_never_inherits_old_ladder(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 98)
        doc = self.pair("SOLUSDT")
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "SOLUSDT", {**doc, "generationId": "g2"})
        self.at("SOLUSDT", 98)                                       # old record ignored -> legacy 1:1 first
        self.assertAlmostEqual(self.short("SOLUSDT"), 10.0)

    def test_concurrent_ticks_place_one_step_order(self):
        import threading
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.L.mark["SOLUSDT"] = 98.0
        threads = [threading.Thread(target=self.worker_tick) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.worker_tick()
        self.check_invariant()
        self.assertEqual(self.orders(), [("CLOSE", 2.5)])
        self.assertAlmostEqual(self.short("SOLUSDT"), 7.5)

    def test_one_failing_symbol_never_blocks_the_others(self):
        self.open_pair("AAAUSDT")
        self.open_pair("BBBUSDT")
        self.at("AAAUSDT", 100)
        self.L.hedge_modes["AAAUSDT"] = "reject"
        self.L.mark["AAAUSDT"] = 98.0
        self.L.mark["BBBUSDT"] = 98.0
        self.worker_tick()
        self.check_invariant()
        self.assertEqual(self.orders("BBBUSDT"), [("CLOSE", 2.5)])
        self.assertAlmostEqual(self.short("AAAUSDT"), 10.0)


class UncertainFills(Recovery):
    """Partial fills and an uncertain order status (timeout after Aster accepted) during Recovery."""

    def closed_total(self, symbol):
        return round(sum(o["filled"] for o in self.L.hedge_orders if o["symbol"] == symbol and o["action"] == "CLOSE"), 9)

    def test_partial_step_fill_is_completed_never_overshoots(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.L.partial_ratio = 0.5
        self.L.hedge_modes["SOLUSDT"] = "partial"
        self.at("SOLUSDT", 98)
        self.assertAlmostEqual(self.short("SOLUSDT"), 8.75)          # half of the 2.5 step filled
        self.at("SOLUSDT", 98)
        self.at("SOLUSDT", 98)
        self.assertAlmostEqual(self.short("SOLUSDT"), 7.5)           # completed, not beyond
        self.assertAlmostEqual(self.closed_total("SOLUSDT"), 2.5)

    def test_timeout_after_acceptance_is_not_sent_twice(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.L.hedge_modes["SOLUSDT"] = "timeout"
        self.at("SOLUSDT", 98)                                      # Aster filled, answer lost
        self.at("SOLUSDT", 98)
        self.at("SOLUSDT", 98)
        self.assertAlmostEqual(self.short("SOLUSDT"), 7.5)
        self.assertEqual(len([o for o in self.L.hedge_orders if o["action"] == "CLOSE"]), 1)



    def test_pending_open_order_holds(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.L.open_order_rows = [{"symbol": "SOLUSDT", "positionSide": "SHORT", "side": "BUY", "status": "NEW",
                                   "origQty": "2.5", "executedQty": "0"}]
        self.at("SOLUSDT", 96)
        self.assertEqual(self.L.hedge_orders, [])                   # nothing new while an order is open
        self.assertEqual(self.rec("SOLUSDT")["lastEvent"], "PENDING_ORDER_HOLD")




class JointExit(Recovery):
    FUNDING: list = []

    def setUp(self):
        super().setUp()
        HedgeClient.income_history = lambda client, **kw: list(self.FUNDING)
        self.addCleanup(lambda: delattr(HedgeClient, "income_history"))

    def request_exit(self, symbol):
        self.assertEqual(pair_exit.long_tp_gate(account_uid=self.uid, symbol=symbol, short_qty=self.short(symbol))[0], "WAIT")
        self.assertIsNotNone(self.pair(symbol).get("pairExitRequestedAt"))

    def test_net_positive_closes_short_then_long_tp_allowed(self):
        self.open_pair("SOLUSDT")                                   # LONG entry 101, SHORT entry 100
        self.at("SOLUSDT", 100)
        self.at("SOLUSDT", 98)                                      # ladder: SHORT 7.5
        self.L.entry[("SOLUSDT", "LONG")] = 90.0                    # LONG deep in profit at mark 110
        self.L.mark["SOLUSDT"] = 110.0
        self.request_exit("SOLUSDT")
        self.worker_tick()
        self.check_invariant()
        self.assertEqual(self.short("SOLUSDT"), 0.0)
        self.assertEqual(self.long("SOLUSDT"), 10.0)
        self.assertEqual(self.pair("SOLUSDT")["pairExit"]["phase"], "CLOSING_OPPOSITE")   # build 623: own field
        self.assertEqual(pair_exit.long_tp_gate(account_uid=self.uid, symbol="SOLUSDT", short_qty=0),
                         ("ALLOW", "OPPOSITE_FLAT_JOINT_EXIT"))
        self.worker_tick()                                          # SHORT stays flat while LONG TP runs
        self.assertEqual(self.short("SOLUSDT"), 0.0)

    def test_net_negative_waits_and_keeps_short(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.L.entry[("SOLUSDT", "LONG")] = 100.4                   # LONG +0.4/coin, SHORT -0.5/coin at 100.5
        self.L.mark["SOLUSDT"] = 100.5
        self.request_exit("SOLUSDT")
        self.worker_tick()
        self.check_invariant()
        self.assertEqual(self.short("SOLUSDT"), 10.0)
        self.assertNotEqual(self.rec("SOLUSDT").get("phase"), "PAIR_EXIT")

    def test_paid_funding_can_block_exit(self):
        self.FUNDING = [{"symbol": "SOLUSDT", "income": "-500"}]
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.L.entry[("SOLUSDT", "LONG")] = 90.0
        self.L.mark["SOLUSDT"] = 110.0
        self.request_exit("SOLUSDT")
        self.worker_tick()
        self.assertEqual(self.short("SOLUSDT"), 10.0)

    def test_unreadable_funding_waits(self):
        HedgeClient.income_history = lambda client, **kw: (_ for _ in ()).throw(RuntimeError("down"))
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.L.entry[("SOLUSDT", "LONG")] = 90.0
        self.L.mark["SOLUSDT"] = 110.0
        self.request_exit("SOLUSDT")
        self.worker_tick()
        self.assertEqual(self.short("SOLUSDT"), 10.0)

    def test_plain_hedged_pair_tp_now_also_waits_for_joint_exit(self):
        # Build 623 (Amar 23-10): every Auto Hedge pair, also with afbouwen OFF / test mode: LONG never alone.
        self.ext.SHORT_RECOVERY_EXECUTION_ENABLED = False
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.assertEqual(pair_exit.long_tp_gate(account_uid=self.uid, symbol="SOLUSDT", short_qty=10)[0], "WAIT")


class SettingsRoute(Recovery):
    def save(self, **kw):
        from fastapi import Response
        body = {"enabled": True, "steps": 10, "totalPct": "20", **kw}
        return self.ext.put_position_loss_auto_hedge_short_recovery(
            self.ext.ShortRecoverySettingsRequest(**body), Response(), {"uid": self.uid})

    def test_free_settings_saved_and_public(self):
        out = self.save()
        self.assertEqual(out["shortRecoveryPlan"], {"enabled": True, "steps": 10, "totalPct": "20", "stepPct": "2",
                                                    "rebuySteps": 1, "safetyNetPct": "20"})
        self.assertEqual(self.get("asterPositionLossAutoHedge", self.uid)["shortRecoveryPlan"]["steps"], 10)
        self.assertEqual(self.L.hedge_orders, [])                    # saving never places an order

    def test_invalid_combination_rejected(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.save(steps=10, totalPct="100")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_requires_auto_hedge_on(self):
        from fastapi import HTTPException
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": False, "thresholdUsd": 0.25})
        with self.assertRaises(HTTPException) as ctx:
            self.save()
        self.assertEqual(ctx.exception.status_code, 409)
        self.save(enabled=False)                                     # switching off is always allowed


class Shadow(Recovery):
    LIVE = False

    def test_shadow_records_grid_and_sends_no_order(self):
        self.open_pair("SOLUSDT")
        for mark in (100, 98, 96, 98, 94):
            self.at("SOLUSDT", mark)
        self.assertEqual(self.orders(), [])                          # test mode: real hedge stays 1:1
        self.assertAlmostEqual(self.short("SOLUSDT"), 10.0)
        self.assertEqual(self.rec("SOLUSDT"), {})
        self.assertEqual(self.rec("SOLUSDT", "shortRecoveryShadow")["phase"], "LADDER")




if __name__ == "__main__":
    unittest.main()
