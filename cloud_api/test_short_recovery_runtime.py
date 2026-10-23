import unittest
from decimal import Decimal as D

from short_recovery_runtime import decide

ON = {"enabled": True, "steps": 4, "stepPct": "2"}


def go(record=None, **kw):
    args = dict(record=record, settings=ON, long_qty=100, short_qty=100, short_entry=100, mark=100,
                has_pending_short_order=False, qty_step=1, min_qty=0, min_notional=0,
                available_balance=100000, leverage=10)
    args.update(kw)
    return decide(**args)


class Lifecycle(unittest.TestCase):
    def test_disabled_is_legacy(self):
        r = go(settings={"enabled": False})
        self.assertEqual((r["override"], r["record"]), (None, None))

    def test_invalid_settings_fall_back_to_legacy(self):
        self.assertIsNone(go(settings={"enabled": True, "steps": 0})["override"])

    def test_waits_for_exact_1_to_1(self):
        r = go(short_qty=0)
        self.assertEqual((r["override"], r["event"]), (None, "WAIT_FOR_1_TO_1"))


    def test_refill_after_switch_on_uses_short_entry(self):
        rec = {"cycleId": 1, "phase": "REFILL", "lastTarget": "100"}
        r = go(rec, short_entry=80, mark=81, start_at_mark=True)
        self.assertEqual(r["record"]["anchor"], "80")

    def test_starts_cycle_with_anchor(self):
        r = go()
        self.assertEqual(r["event"], "CYCLE_STARTED")
        self.assertEqual((r["record"]["anchor"], r["record"]["base"], r["override"]), ("100", "100", D(100)))

    def full_ladder(self):
        rec = go()["record"]
        short = D(100)
        for mark in (98, 96, 94, 92):
            r = go(rec, mark=mark, short_qty=short)
            self.assertEqual(r["event"], "STEP_REDUCE")
            short = r["override"]
            rec = r["record"]
        return rec, short



    def test_pending_order_holds_last_target(self):
        rec = go()["record"]
        rec = go(rec, mark=98)["record"]
        r = go(rec, mark=90, short_qty=80, has_pending_short_order=True)
        self.assertEqual((r["override"], r["event"], r["record"]["stepsReached"]), (D(75), "PENDING_ORDER_HOLD", 1))

    def test_dca_growth_stays_hedged(self):
        rec = go()["record"]
        r = go(rec, mark=98, long_qty=150, short_qty=150)
        self.assertEqual(r["override"], D(125))

    def test_target_never_above_long(self):
        rec = go()["record"]
        r = go(rec, mark=100, long_qty=60, short_qty=60)
        self.assertLessEqual(r["override"], D(60))

    def test_long_gone_clears(self):
        rec = go()["record"]
        r = go(rec, long_qty=0, short_qty=100)
        self.assertEqual((r["override"], r["record"], r["event"]), (None, None, "NO_LONG"))




class PublicUnwind(unittest.TestCase):
    def test_live_first_then_test_mode(self):
        from short_recovery_runtime import public_unwind
        pair = {"currentProtectedQty": 10, "shortRecoveryShadow": {"phase": "LADDER", "stepsReached": 1, "steps": 4,
                "lastTarget": "7.5", "cycleId": 1}}
        self.assertEqual(public_unwind(pair)["mode"], "TEST")
        self.assertEqual(public_unwind(pair)["hedgePct"], 75.0)
        pair["shortRecovery"] = {"phase": "LADDER", "stepsReached": 2, "steps": 4, "lastTarget": "5", "cycleId": 1}
        self.assertEqual((public_unwind(pair)["mode"], public_unwind(pair)["stepsReached"]), ("LIVE", 2))
        self.assertIsNone(public_unwind({"status": "HEDGED"}))




if __name__ == "__main__":
    unittest.main()


