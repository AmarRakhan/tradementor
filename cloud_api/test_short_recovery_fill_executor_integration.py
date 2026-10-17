"""Full mock order preview -> confirmed exchange fill -> immutable zone ledger.

No exchange client, API routes, Firestore operations, or real orders.
"""
import unittest
from decimal import Decimal as D
from short_recovery_mock import Cycle, confirmed_fill
from short_recovery_executor_adapter import preview_mock_executor
from short_recovery_ledger import Ledger, Allocation, Fill

SETTINGS = {"enabled": True, "steps": 4, "stepPct": "3"}

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.cycle = Cycle(D("2"), D("100"))
        self.ledger = Ledger("account1", "XRPUSDT", (Allocation("zone1", "cycle1", D("100")),))
    def preview(self, mark, *, net_tp=False, busy=False):
        return preview_mock_executor(
            self.cycle, D(mark), SETTINGS,
            exchange_short=self.ledger.allocations[0].remaining,
            long_qty=D("100"), net_tp=net_tp, claims_busy=busy)
    def fill(self, execution, qty):
        self.ledger = self.ledger.apply(
            Fill("account1", "XRPUSDT", execution, "order-"+execution, D(qty), D("1"), D("0.01")),
            (("zone1","cycle1",D(qty)),))
        self.cycle = confirmed_fill(self.cycle, qty)
    def test_reached_levels_then_partial_fill(self):
        self.assertEqual(self.preview("1.8")["quantity"], "75")
        self.fill("fill1", "30")
        self.assertEqual(self.preview("1.8")["quantity"], "45")
        self.fill("fill2", "45")
        self.assertEqual(self.preview("2.1")["status"], "HOLD_PARTIAL")
    def test_final_fill_then_rehedge(self):
        self.fill("fill1", "75")
        self.assertEqual(self.preview("1.76")["quantity"], "25")
        self.fill("fill2", "25")
        self.assertTrue(self.ledger.final_fill_confirmed("zone1","cycle1",frozenset({"fill1","fill2"})))
        self.assertEqual(self.preview("1.76")["status"], "MOCK_REHEDGE_AFTER_FINAL")
    def test_exit_priority_over_hedge(self):
        self.fill("fill1", "100")
        self.assertEqual(self.preview("1.76",net_tp=True)["status"], "EXIT_PAIR")
    def test_duplicate_fill_does_not_change_inventory(self):
        self.fill("fill1", "30")
        before = self.ledger
        with self.assertRaises(ValueError):
            before.apply(Fill("account1","XRPUSDT","fill1","order-2",D("30"),D("1"),D("0")), (("zone1","cycle1",D("30")),))
        self.assertEqual(before,self.ledger)
    def test_wrong_account_cannot_modify_inventory(self):
        with self.assertRaises(ValueError):
            self.ledger.apply(Fill("account2","XRPUSDT","fill1","o",D("20"),D(0),D(0)), (("zone1","cycle1",D("20")),))
    def test_claim_busy_never_submits(self):
        self.assertEqual(self.preview("1.8",busy=True)["status"], "BLOCKED_CLAIM_BUSY")
        self.assertEqual(self.preview("1.8",busy=True)["ordersSent"], 0)
    def test_legacy_topup_requires_explicit_handoff(self):
        self.fill("fill1","25")
        self.assertEqual(self.ledger.rollback_risk(),"LEGACY_1_TO_1_TOPUP_RISK")
        self.assertEqual(self.preview("2.1")["status"],"HOLD_PARTIAL")

if __name__ == "__main__":
    unittest.main()
