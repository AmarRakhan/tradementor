import unittest
from decimal import Decimal as D
from short_recovery_ownership import ZoneLong, ClosedFill, check_ownership, attribute_fill, combined_cycle_pnl

class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.rows = [ZoneLong('a','XRPUSDT','zone1',D('10'),D('7.5')),
                     ZoneLong('a','XRPUSDT','zone2',D('5'),D('5'))]
    def status(self, rows=None, long=15, short='12.5'):
        return check_ownership(self.rows if rows is None else rows, account_id='a', symbol='XRPUSDT', exchange_long_qty=long, exchange_short_qty=short)
    def test_exact_aggregate(self): self.assertEqual(self.status(), 'RECONCILED_FOR_PREVIEW_ONLY')
    def test_unmatched_short(self): self.assertEqual(self.status(short=15),'BLOCKED_SHORT_RECONCILIATION')
    def test_unmatched_long(self): self.assertEqual(self.status(long=16),'BLOCKED_LONG_RECONCILIATION')
    def test_duplicate_zone(self): self.assertEqual(self.status(rows=[self.rows[0],self.rows[0]]),'BLOCKED_DUPLICATE_ZONE_POSITION')
    def test_cross_account(self):
        rows=[ZoneLong('b','XRPUSDT','zone1',D(10),D('7.5')),self.rows[1]]
        self.assertEqual(self.status(rows=rows),'BLOCKED_SCOPE_MISMATCH')
    def test_no_borrowing_over_allocation(self):
        rows=[ZoneLong('a','XRPUSDT','zone1',D(10),D(11)),self.rows[1]]
        self.assertEqual(self.status(rows=rows),'BLOCKED_BAD_ALLOCATION')
    def test_empty(self): self.assertEqual(self.status(rows=[]),'BLOCKED_MISSING_OWNERSHIP')
    def test_partial_fill(self):
        fill=ClosedFill('a','XRPUSDT','trade1',D('2.5'),D('.14'),D('.01'))
        self.assertEqual(attribute_fill(fill,expected_account='a',expected_symbol='XRPUSDT',seen_ids=frozenset(),cycle_id='cycle1',intended_qty=D('2.5'),outstanding_allocated_qty=D('7.5'))['net_realized_pnl'],D('.13'))
    def test_duplicate_fill(self):
        fill=ClosedFill('a','XRPUSDT','trade1',D(1),D('.1'),D(0))
        with self.assertRaises(ValueError):attribute_fill(fill,expected_account='a',expected_symbol='XRPUSDT',seen_ids=frozenset({'trade1'}),cycle_id='c',intended_qty=1,outstanding_allocated_qty=1)
    def test_cross_account_fill(self):
        fill=ClosedFill('b','XRPUSDT','trade1',D(1),D('.1'),D(0))
        with self.assertRaises(ValueError):attribute_fill(fill,expected_account='a',expected_symbol='XRPUSDT',seen_ids=frozenset(),cycle_id='c',intended_qty=1,outstanding_allocated_qty=1)
    def test_oversell(self):
        fill=ClosedFill('a','XRPUSDT','trade1',D(3),D('.1'),D(0))
        with self.assertRaises(ValueError):attribute_fill(fill,expected_account='a',expected_symbol='XRPUSDT',seen_ids=frozenset(),cycle_id='c',intended_qty=2,outstanding_allocated_qty=5)
    def test_cycle_pnl(self):
        self.assertEqual(combined_cycle_pnl(long_open='-.5',short_open='-.1',confirmed_fill_net_pnls=['.3','.4'],other_fees='.05',funding='-.01'), D('.04'))
if __name__=='__main__':unittest.main()
