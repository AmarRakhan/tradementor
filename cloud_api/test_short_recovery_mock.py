import unittest
from decimal import Decimal as D
from short_recovery_mock import Cycle,mock_scan,confirmed_fill,canonical_settings
class Tests(unittest.TestCase):
    def setUp(self):
        self.s={"enabled":True,"stepPct":"3","steps":4}
        self.c=Cycle(D(2),D(100))
    def test_default_off(self): self.assertFalse(canonical_settings({})["enabled"])
    def test_invalid(self):
        with self.assertRaises(ValueError): canonical_settings({"enabled":True,"steps":20,"stepPct":"5"})
    def test_historical_catchup(self): self.assertEqual(mock_scan(self.c,D("1.8"),self.s,exchange_short=100),("MOCK_REDUCE",D(75)))
    def test_first_step(self): self.assertEqual(mock_scan(self.c,D("1.94"),self.s,exchange_short=100),("MOCK_REDUCE",D(25)))
    def test_partial_fill(self):
        c=confirmed_fill(self.c,D(30))
        self.assertEqual(mock_scan(c,D("1.8"),self.s,exchange_short=70),("MOCK_REDUCE",D(45)))
    def test_no_topup_on_bounce(self):
        c=confirmed_fill(self.c,D(75))
        self.assertEqual(mock_scan(c,D("2.2"),self.s,exchange_short=25),("HOLD_PARTIAL",D(0)))
    def test_last_fill_required(self):
        c=confirmed_fill(self.c,D(75))
        self.assertEqual(mock_scan(c,D("1.7"),self.s,exchange_short=25),("MOCK_REDUCE",D(25)))
    def test_rehedge_only_zero(self):
        c=confirmed_fill(self.c,D(100))
        self.assertEqual(mock_scan(c,D("1.7"),self.s,exchange_short=0,long_qty=100),("REHEDGE_PREVIEW",D(100)))
    def test_exit_priority(self): self.assertEqual(mock_scan(self.c,D("1.8"),self.s,exchange_short=100,net_tp=True),("EXIT_PAIR",D(0)))
    def test_exchange_mismatch(self): self.assertEqual(mock_scan(self.c,D("1.8"),self.s,exchange_short=120),("BLOCKED_EXCHANGE_MISMATCH",D(0)))
    def test_no_trading_disabled(self): self.assertEqual(mock_scan(self.c,D("1.8"),{},exchange_short=100),("OFF",D(0)))
    def test_pending(self):
        c=Cycle(D(2),D(100),pending=True)
        self.assertEqual(mock_scan(c,D("1.8"),self.s,exchange_short=100),("WAIT_PENDING",D(0)))
if __name__=="__main__":unittest.main()
