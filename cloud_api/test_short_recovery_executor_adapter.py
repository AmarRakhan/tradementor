import unittest
from decimal import Decimal as D
from short_recovery_mock import Cycle
from short_recovery_executor_adapter import preview_mock_executor
class MockAdapterTests(unittest.TestCase):
 def setUp(self):
  self.c=Cycle(D(2),D(100));self.s={"enabled":True,"steps":4,"stepPct":"3"}
 def test_reduce_never_sends(self):
  v=preview_mock_executor(self.c,D("1.8"),self.s,exchange_short=100,long_qty=100)
  self.assertEqual(v["quantity"],"75");self.assertEqual(v["ordersSent"],0)
 def test_claim_busy(self):
  self.assertEqual(preview_mock_executor(self.c,D("1.8"),self.s,exchange_short=100,long_qty=100,claims_busy=True)["status"],"BLOCKED_CLAIM_BUSY")
 def test_exit_first(self):
  self.assertEqual(preview_mock_executor(self.c,D("1.8"),self.s,exchange_short=100,long_qty=100,net_tp=True)["status"],"EXIT_PAIR")
 def test_no_premature_rehedge(self):
  c=Cycle(D(2),D(100),D(75))
  self.assertEqual(preview_mock_executor(c,D("2.2"),self.s,exchange_short=25,long_qty=100)["status"],"HOLD_PARTIAL")
 def test_last_fill_rehedge(self):
  c=Cycle(D(2),D(100),D(100))
  self.assertEqual(preview_mock_executor(c,D("1.7"),self.s,exchange_short=0,long_qty=100)["status"],"MOCK_REHEDGE_AFTER_FINAL")
if __name__=="__main__":unittest.main()
