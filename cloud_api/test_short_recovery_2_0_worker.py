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
    def test_four_steps_no_topup_then_refill_and_new_cycle(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.assertEqual(self.orders(), [])
        self.assertEqual(self.rec("SOLUSDT")["anchor"], "100")
        self.at("SOLUSDT", 98)
        self.assertEqual(self.orders(), [("CLOSE", 2.5)])
        self.at("SOLUSDT", 99.5)                                     # bounce: no top-up, no re-short
        self.at("SOLUSDT", 99.5)
        self.assertEqual(self.orders(), [("CLOSE", 2.5)])
        self.assertAlmostEqual(self.short("SOLUSDT"), 7.5)
        self.assertEqual(self.pair("SOLUSDT")["status"], "HEDGED")
        for mark in (96, 94, 92):
            self.at("SOLUSDT", mark)
        self.assertAlmostEqual(self.short("SOLUSDT"), 0.0)
        self.assertEqual(self.long("SOLUSDT"), 10.0)                  # LONG never touched
        self.at("SOLUSDT", 92)                                       # ladder done -> 100% refill
        self.assertAlmostEqual(self.short("SOLUSDT"), 10.0)
        self.L.entry[("SOLUSDT", "SHORT")] = 92.0                    # Aster reports the new average entry
        self.at("SOLUSDT", 92)
        rec = self.rec("SOLUSDT")
        self.assertEqual((rec["phase"], rec["anchor"], rec["cycleId"]), ("LADDER", "92", 2))
        self.at("SOLUSDT", "90.16")                                   # first step of the NEW ladder (92 * 0.98)
        self.assertEqual(self.orders()[-1], ("CLOSE", 2.5))

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

    def test_timeout_on_reopen_never_double_opens(self):
        self.open_pair("PEPEUSDT", qty=10.0, minimum=3, step=1)
        self.at("PEPEUSDT", 100)
        self.at("PEPEUSDT", 98)                                     # close all
        self.L.hedge_modes["PEPEUSDT"] = "timeout"
        self.at("PEPEUSDT", 98)                                     # reopen 9 accepted, answer lost
        self.L.entry[("PEPEUSDT", "SHORT")] = 98.0                  # Aster: new average entry of the reopened SHORT
        for _ in range(3):
            self.at("PEPEUSDT", 98)
        self.assertAlmostEqual(self.short("PEPEUSDT"), 9.0)
        self.assertEqual([o["action"] for o in self.L.hedge_orders], ["CLOSE", "OPEN"])

    def test_partial_close_all_completes_before_reopen(self):
        self.open_pair("PEPEUSDT", qty=10.0, minimum=3, step=1)
        self.at("PEPEUSDT", 100)
        self.L.partial_ratio = 0.5
        self.L.hedge_modes["PEPEUSDT"] = "partial"
        self.at("PEPEUSDT", 98)
        self.assertAlmostEqual(self.short("PEPEUSDT"), 5.0)
        self.assertNotIn("OPEN", [o["action"] for o in self.L.hedge_orders])   # no reopen while not flat
        for _ in range(3):
            self.at("PEPEUSDT", 98)
        self.assertAlmostEqual(self.short("PEPEUSDT"), 9.0)
        self.assertEqual([o["action"] for o in self.L.hedge_orders], ["CLOSE", "CLOSE", "OPEN"])

    def test_pending_open_order_holds(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.L.open_order_rows = [{"symbol": "SOLUSDT", "positionSide": "SHORT", "side": "BUY", "status": "NEW",
                                   "origQty": "2.5", "executedQty": "0"}]
        self.at("SOLUSDT", 96)
        self.assertEqual(self.L.hedge_orders, [])                   # nothing new while an order is open
        self.assertEqual(self.rec("SOLUSDT")["lastEvent"], "PENDING_ORDER_HOLD")


class LiveReopenNinety(Recovery):
    def test_too_small_step_closes_all_and_reopens_90(self):
        self.open_pair("PEPEUSDT", qty=10.0, minimum=3, step=1)
        self.at("PEPEUSDT", 100)
        self.at("PEPEUSDT", 98)
        self.assertEqual(self.orders(), [("CLOSE", 10.0)])
        self.at("PEPEUSDT", 98)
        self.assertEqual(self.orders()[-1], ("OPEN", 9.0))
        self.assertAlmostEqual(self.short("PEPEUSDT"), 9.0)
        self.L.entry[("PEPEUSDT", "SHORT")] = 98.0
        self.at("PEPEUSDT", 98)
        self.assertEqual(self.rec("PEPEUSDT")["base"], "9")
        self.at("PEPEUSDT", 99)                                      # the 10% gap is kept
        self.at("PEPEUSDT", 99)
        self.assertAlmostEqual(self.short("PEPEUSDT"), 9.0)
        self.assertEqual(len(self.orders()), 2)

    def test_no_margin_for_reopen_never_closes_all(self):
        self.open_pair("PEPEUSDT", qty=10.0, minimum=3, step=1)
        self.at("PEPEUSDT", 100)
        self.L.available = 0.0
        self.at("PEPEUSDT", 98)
        self.assertEqual(self.orders(), [])
        self.assertAlmostEqual(self.short("PEPEUSDT"), 10.0)

    def test_reopen_below_minimum_is_skipped(self):
        self.open_pair("PEPEUSDT", qty=10.0, minimum=10, step=1)
        self.at("PEPEUSDT", 100)
        self.at("PEPEUSDT", 98)
        self.assertEqual(self.orders(), [])
        self.assertEqual(self.rec("PEPEUSDT")["lastEvent"], "SKIPPED_BELOW_MINIMUM")


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
        self.assertEqual(self.rec("SOLUSDT")["phase"], "PAIR_EXIT")
        self.assertEqual(pair_exit.long_tp_gate(account_uid=self.uid, symbol="SOLUSDT", short_qty=0),
                         ("ALLOW", "SHORT_FLAT_JOINT_EXIT"))
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

    def test_legacy_pair_tp_is_unchanged(self):
        self.ext.SHORT_RECOVERY_EXECUTION_ENABLED = False
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        self.assertEqual(pair_exit.long_tp_gate(account_uid=self.uid, symbol="SOLUSDT", short_qty=10)[0], "ALLOW")


class SettingsRoute(Recovery):
    def save(self, **kw):
        from fastapi import Response
        body = {"enabled": True, "steps": 10, "totalPct": "20", **kw}
        return self.ext.put_position_loss_auto_hedge_short_recovery(
            self.ext.ShortRecoverySettingsRequest(**body), Response(), {"uid": self.uid})

    def test_free_settings_saved_and_public(self):
        out = self.save()
        self.assertEqual(out["shortRecoveryPlan"], {"enabled": True, "steps": 10, "totalPct": "20", "stepPct": "2"})
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

    def test_shadow_records_ladder_and_sends_no_recovery_order(self):
        self.open_pair("SOLUSDT")
        for mark in (100, 98, 99, 96, 94, 92, 92):
            self.at("SOLUSDT", mark)
        self.assertEqual(self.orders(), [])                         # legacy 1:1 already exact
        self.assertAlmostEqual(self.short("SOLUSDT"), 10.0)
        self.assertEqual(self.rec("SOLUSDT"), {})
        shadow = self.rec("SOLUSDT", "shortRecoveryShadow")
        self.assertEqual(shadow["phase"], "REFILL")
        self.at("SOLUSDT", 92)
        shadow = self.rec("SOLUSDT", "shortRecoveryShadow")
        self.assertEqual((shadow["phase"], shadow["cycleId"], shadow["anchor"]), ("LADDER", 2, "92"))

    def test_shadow_reports_decisions(self):
        self.open_pair("SOLUSDT")
        self.at("SOLUSDT", 100)
        report = self.at("SOLUSDT", 98)
        row = report["shortRecovery"][0]
        self.assertEqual((row["event"], row["targetShort"], row["mode"]), ("STEP_REDUCE", 7.5, "shortRecoveryShadow"))


if __name__ == "__main__":
    unittest.main()
