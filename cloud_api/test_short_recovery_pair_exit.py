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
    def setUp(self):
        self.requests = []
        self.pair = {}
        X.configure(lambda u, s: self.pair, lambda u, s: self.requests.append(s))

    def tearDown(self):
        X.configure(None, None)

    def test_legacy_pair_unchanged(self):
        self.pair = {"status": "HEDGED"}
        self.assertEqual(X.long_tp_gate(account_uid="u", symbol="SOLUSDT", short_qty=5)[0], "ALLOW")
        self.assertEqual(self.requests, [])

    def test_managed_pair_with_short_waits_and_requests(self):
        self.pair = {"shortRecovery": {"phase": "LADDER"}}
        self.assertEqual(X.long_tp_gate(account_uid="u", symbol="solusdt", short_qty=5),
                         ("WAIT", "JOINT_EXIT_REQUESTED_WAIT_FOR_NET_CHECK"))
        self.assertEqual(self.requests, ["SOLUSDT"])

    def test_short_flat_allows(self):
        self.pair = {"shortRecovery": {"phase": "PAIR_EXIT"}}
        self.assertEqual(X.long_tp_gate(account_uid="u", symbol="SOLUSDT", short_qty=0),
                         ("ALLOW", "SHORT_FLAT_JOINT_EXIT"))

    def test_unreadable_pair_waits(self):
        def boom(u, s):
            raise RuntimeError("down")
        X.configure(boom, None)
        self.assertEqual(X.long_tp_gate(account_uid="u", symbol="SOLUSDT", short_qty=5)[0], "WAIT")

    def test_not_configured_is_legacy(self):
        X.configure(None, None)
        self.assertEqual(X.long_tp_gate(account_uid="u", symbol="SOLUSDT", short_qty=5)[0], "ALLOW")


if __name__ == "__main__":
    unittest.main()
