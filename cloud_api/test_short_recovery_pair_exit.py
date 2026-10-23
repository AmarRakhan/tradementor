import unittest
from decimal import Decimal as D

import short_recovery_pair_exit as X


class Net(unittest.TestCase):
    def test_amar_examples(self):
        ok = X.net_exit(long_pnl=3, short_pnl="-0.5", long_notional=0, short_notional=0, funding_paid=D(0))
        self.assertEqual((ok["allowed"], ok["net"]), (True, D("2.5")))
        wait = X.net_exit(long_pnl="0.4", short_pnl="-0.5", long_notional=0, short_notional=0, funding_paid=D(0))
        self.assertEqual((wait["allowed"], wait["reason"]), (False, "NET_NOT_POSITIVE_WAIT"))

    def test_fees_and_paid_funding_count(self):
        r = X.net_exit(long_pnl="1", short_pnl="-0.5", long_notional=500, short_notional=500, funding_paid=D("0.1"))
        self.assertEqual(r["net"], D("1") - D("0.5") - D("0.5") - D("0.1"))
        self.assertFalse(r["allowed"])

    def test_exactly_zero_waits(self):
        self.assertFalse(X.net_exit(long_pnl=1, short_pnl=-1, long_notional=0, short_notional=0, funding_paid=D(0))["allowed"])

    def test_unknown_inputs_wait(self):
        self.assertFalse(X.net_exit(long_pnl="x", short_pnl=0, long_notional=0, short_notional=0, funding_paid=D(0))["allowed"])
        self.assertFalse(X.net_exit(long_pnl=5, short_pnl=0, long_notional=0, short_notional=0, funding_paid=None)["allowed"])


class Funding(unittest.TestCase):
    class C:
        def __init__(self, rows=None, fail=False):
            self.rows, self.fail = rows or [], fail
        def income_history(self, **kw):
            if self.fail:
                raise RuntimeError("down")
            return self.rows

    def test_only_paid_funding_counts(self):
        rows = [{"symbol": "SOLUSDT", "income": "-0.3"}, {"symbol": "SOLUSDT", "income": "0.8"},
                {"symbol": "SOLUSDT", "income": "-0.2"}]
        self.assertEqual(X.paid_funding(self.C(rows), symbol="SOLUSDT", start_ms=0), D("0.5"))

    def test_received_funding_never_becomes_profit(self):
        self.assertEqual(X.paid_funding(self.C([{"symbol": "SOLUSDT", "income": "5"}]), symbol="SOLUSDT", start_ms=0), D(0))

    def test_unreadable_or_full_page_fails_closed(self):
        self.assertIsNone(X.paid_funding(self.C(fail=True), symbol="SOLUSDT", start_ms=0))
        full = [{"symbol": "SOLUSDT", "income": "-0.01"}] * 1000
        self.assertIsNone(X.paid_funding(self.C(full), symbol="SOLUSDT", start_ms=0))
        self.assertIsNone(X.paid_funding(self.C([{"symbol": "SOLUSDT", "income": "abc"}]), symbol="SOLUSDT", start_ms=0))


class Gate(unittest.TestCase):
    """Build 623 (Amar 23-10): every Auto Hedge pair, both sides, joint exit only when net positive."""

    def setUp(self):
        self.requests = []
        self.pair = {}
        X.configure(lambda u, s: self.pair, lambda u, s, side: self.requests.append((s, side)))

    def tearDown(self):
        X.configure(None, None)

    def gate(self, side="LONG", opposite=5, symbol="SOLUSDT"):
        return X.pair_tp_gate(account_uid="u", symbol=symbol, side=side, opposite_qty=opposite)

    def test_no_auto_hedge_pair_is_unchanged(self):
        for pair in ({}, {"status": "CLOSED"}):
            self.pair = pair
            self.assertEqual(self.gate(), ("ALLOW", "NOT_AUTO_HEDGE_PAIR"))
        self.assertEqual(self.requests, [])

    def test_hedged_pair_without_afbouw_record_now_waits_for_joint_exit(self):
        # Was ALLOW before build 623 (LONG closed alone, SHORT left open = net SHORT).
        self.pair = {"status": "HEDGED", "protectedSide": "LONG"}
        self.assertEqual(self.gate(), ("WAIT", "JOINT_EXIT_REQUESTED_WAIT_FOR_NET_CHECK"))
        self.assertEqual(self.requests, [("SOLUSDT", "LONG")])

    def test_protected_short_tp_waits_for_joint_exit(self):
        self.pair = {"status": "HEDGED", "protectedSide": "SHORT"}
        self.assertEqual(self.gate(side="SHORT", symbol="solusdt"), ("WAIT", "JOINT_EXIT_REQUESTED_WAIT_FOR_NET_CHECK"))
        self.assertEqual(self.requests, [("SOLUSDT", "SHORT")])

    def test_tp_on_hedge_side_of_active_pair_is_not_joint(self):
        self.pair = {"status": "HEDGED", "protectedSide": "LONG"}
        self.assertEqual(self.gate(side="SHORT"), ("ALLOW", "TP_ON_HEDGE_SIDE"))
        self.assertEqual(self.requests, [])

    def test_recovery_pair_with_both_legs_waits_for_joint_exit(self):
        self.pair = {"status": "RECOVERY", "protectedSide": "SHORT", "hedgeSide": "LONG"}
        self.assertEqual(self.gate(side="LONG"), ("WAIT", "JOINT_EXIT_REQUESTED_WAIT_FOR_NET_CHECK"))

    def test_manual_release_in_progress_waits_without_request(self):
        self.pair = {"status": "MANUAL_RELEASE_PENDING", "protectedSide": "LONG"}
        self.assertEqual(self.gate(), ("WAIT", "MANUAL_RELEASE_IN_PROGRESS"))
        self.assertEqual(self.requests, [])

    def test_opposite_flat_allows(self):
        self.pair = {"status": "HEDGED", "protectedSide": "LONG", "pairExit": {"phase": "CLOSING_OPPOSITE"}}
        self.assertEqual(self.gate(opposite=0), ("ALLOW", "OPPOSITE_FLAT_JOINT_EXIT"))
        self.pair = {"status": "HEDGED", "protectedSide": "LONG"}
        self.assertEqual(self.gate(opposite=0), ("ALLOW", "OPPOSITE_FLAT"))

    def test_long_tp_gate_wrapper(self):
        self.pair = {"status": "HEDGED", "protectedSide": "LONG"}
        self.assertEqual(X.long_tp_gate(account_uid="u", symbol="SOLUSDT", short_qty=5)[0], "WAIT")

    def test_unreadable_pair_waits(self):
        def boom(u, s):
            raise RuntimeError("down")
        X.configure(boom, None)
        self.assertEqual(self.gate()[0], "WAIT")

    def test_not_configured_is_legacy(self):
        X.configure(None, None)
        self.assertEqual(self.gate()[0], "ALLOW")


if __name__ == "__main__":
    unittest.main()
