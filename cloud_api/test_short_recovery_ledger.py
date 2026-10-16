import unittest
from decimal import Decimal as D
from short_recovery_ledger import Allocation, Fill, Ledger

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.s=Ledger("u","XRPUSDT",(Allocation("z1","c1",D(8)),Allocation("z2","c2",D(4))))
        self.f=Fill("u","XRPUSDT","x1","order1",D(3),D(".6"),D(".03"),D("-.03"))
    def test_split(self):
        n=self.s.apply(self.f,(("z1","c1",D(2)),("z2","c2",D(1))))
        self.assertEqual(n.cycle_realized("c1"),D(".36"))
    def test_duplicate(self):
        n=self.s.apply(self.f,(("z1","c1",D(3)),))
        with self.assertRaises(ValueError): n.apply(self.f,(("z1","c1",D(3)),))
    def test_oversell(self):
        with self.assertRaises(ValueError): self.s.apply(self.f,(("z2","c2",D(5)),))
    def test_mismatch(self):
        with self.assertRaises(ValueError): self.s.apply(self.f,(("z1","c1",D(2)),))
    def test_cross_account(self):
        with self.assertRaises(ValueError): self.s.apply(Fill("v","XRPUSDT","x1","o",D(3),D(0),D(0)),(("z1","c1",D(3)),))
    def test_atomic(self):
        with self.assertRaises(ValueError): self.s.apply(self.f,(("z1","c1",D(2)),("bad","c",D(1))))
        self.assertEqual(self.s.seen,frozenset())
    def test_two_partial_fills(self):
        n=self.s.apply(Fill("u","XRPUSDT","a","o",D(1),D(".1"),D(0)),(("z1","c1",D(1)),))
        n=n.apply(Fill("u","XRPUSDT","b","o",D(2),D(".2"),D(0)),(("z1","c1",D(2)),))
        self.assertEqual(n.allocations[0].remaining,D(5))
    def test_last_fill(self):
        n=self.s.apply(Fill("u","XRPUSDT","last","o",D(8),D(1),D(0)),(("z1","c1",D(8)),))
        self.assertTrue(n.final_fill_confirmed("z1","c1",frozenset({"last"})))
        self.assertFalse(n.final_fill_confirmed("z1","c1",frozenset({"last"}),True))
    def test_duplicate_split(self):
        with self.assertRaises(ValueError): self.s.apply(self.f,(("z1","c1",D(2)),("z1","c1",D(1))))
    def test_cross_cycle(self):
        with self.assertRaises(ValueError): self.s.apply(self.f,(("z1","c2",D(3)),))
    def test_bad_identity(self):
        with self.assertRaises(ValueError): self.s.apply(Fill("u","XRPUSDT","","o",D(3),D(0),D(0)),(("z1","c1",D(3)),))
    def test_rollback(self):self.assertEqual(self.s.rollback_risk(),"LEGACY_1_TO_1_TOPUP_RISK")
