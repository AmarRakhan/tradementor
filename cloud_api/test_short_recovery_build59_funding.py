import unittest
from decimal import Decimal
from short_recovery_funding_shadow import income_pages, funding_for_cycle

class Mock:
    def __init__(self, rows):
        self.rows=rows;self.calls=[]
    def income_history(self, **kwargs):
        self.calls.append(kwargs)
        return [r for r in self.rows if kwargs['start_time'] <= r['time'] <= kwargs['end_time']][:kwargs['limit']]
    def submit_order(self, *a, **k):
        raise AssertionError('live order forbidden')

class Tests(unittest.TestCase):
    def event(self, identity, time=101, **kw):
        return {'tranId':identity,'time':time,'symbol':'XRPUSDT','positionSide':'SHORT','incomeType':'FUNDING_FEE','income':'-0.03',**kw}
    def test_two_equal_timestamps_in_full_page_are_blocked(self):
        c=Mock([self.event(1),self.event(2),self.event(3)])
        with self.assertRaisesRegex(ValueError,'SAME_TIMESTAMP'):
            income_pages(c,symbol='XRPUSDT',start_ms=100,end_ms=200,page_size=2)
        self.assertEqual(len(c.calls),1)
    def test_short_page_read_only(self):
        c=Mock([self.event(1),self.event(2)])
        result=income_pages(c,symbol='XRPUSDT',start_ms=100,end_ms=200,page_size=3)
        self.assertEqual(len(result),2)
        self.assertEqual(list(c.calls[0]),['symbol','start_time','end_time','limit'])
    def test_unsorted_income_rejected(self):
        with self.assertRaisesRegex(ValueError,'BLOCKED_INCOME_ORDER'):
            income_pages(Mock([self.event(1,time=150),self.event(2,time=110)]),symbol='XRPUSDT',start_ms=100,end_ms=200)
    def test_wrong_symbol_income_rejected(self):
        with self.assertRaisesRegex(ValueError,'BLOCKED_INCOME_IDENTITY'):
            income_pages(Mock([self.event(1,symbol='BTCUSDT')]),symbol='XRPUSDT',start_ms=100,end_ms=200)
    def test_malformed_income_blocks(self):
        with self.assertRaisesRegex(ValueError,'IDENTITY'):
            income_pages(Mock([{'time':101}]),symbol='XRPUSDT',start_ms=100,end_ms=200)
    def test_cycle_requires_proven_event_ownership(self):
        with self.assertRaisesRegex(ValueError,'ATTRIBUTION'):
            funding_for_cycle([self.event(1)],symbol='XRPUSDT',side='SHORT',cycle_id='c1',start_ms=100,end_ms=200,ownership_proof={})
    def test_exclusive_proof_allows_signed_funding(self):
        rows=[self.event(1),self.event(2)]
        self.assertEqual(funding_for_cycle(rows,symbol='XRPUSDT',side='SHORT',cycle_id='c1',start_ms=100,end_ms=200,ownership_proof={'1':('XRPUSDT','SHORT','c1'),'2':('XRPUSDT','SHORT','c1')}),Decimal('-0.06'))
    def test_other_cycle_is_not_assigned(self):
        with self.assertRaisesRegex(ValueError,'ATTRIBUTION'):
            funding_for_cycle([self.event(1)],symbol='XRPUSDT',side='SHORT',cycle_id='c1',start_ms=100,end_ms=200,ownership_proof={'1':('XRPUSDT','SHORT','c2')})
    def test_missing_side_blocks(self):
        row=self.event(1);row.pop('positionSide')
        with self.assertRaisesRegex(ValueError,'ATTRIBUTION'):
            funding_for_cycle([row],symbol='XRPUSDT',side='SHORT',cycle_id='c1',start_ms=100,end_ms=200,ownership_proof={'1':('XRPUSDT','SHORT','c1')})
    def test_duplicate_income_blocks(self):
        with self.assertRaisesRegex(ValueError,'EVIDENCE'):
            funding_for_cycle([self.event(1),self.event(1)],symbol='XRPUSDT',side='SHORT',cycle_id='c1',start_ms=100,end_ms=200,ownership_proof={'1':('XRPUSDT','SHORT','c1')})
    def test_nonfinite_funding_blocks(self):
        row=self.event(1);row['income']='NaN'
        with self.assertRaisesRegex(ValueError,'EVIDENCE'):
            funding_for_cycle([row],symbol='XRPUSDT',side='SHORT',cycle_id='c1',start_ms=100,end_ms=200,ownership_proof={'1':('XRPUSDT','SHORT','c1')})
    def test_interval_boundary_blocks(self):
        with self.assertRaisesRegex(ValueError,'EVIDENCE'):
            funding_for_cycle([self.event(1,time=200)],symbol='XRPUSDT',side='SHORT',cycle_id='c1',start_ms=100,end_ms=200,ownership_proof={'1':('XRPUSDT','SHORT','c1')})

if __name__=='__main__': unittest.main()

class EmptyIncomeCannotProveZero(__import__('unittest').TestCase):
 def test_empty_income_does_not_infer_zero_funding(self):
  with self.assertRaisesRegex(ValueError,'BLOCKED_ZERO_FUNDING_NOT_PROVEN'):
   funding_for_cycle([],symbol='XRPUSDT',side='SHORT',cycle_id='c1',start_ms=100,end_ms=200,ownership_proof={})
 def test_non_funding_income_does_not_infer_zero(self):
  row={'symbol':'XRPUSDT','incomeType':'COMMISSION','time':110,'tranId':'1','income':'-0.02'}
  with self.assertRaisesRegex(ValueError,'BLOCKED_ZERO_FUNDING_NOT_PROVEN'):
   funding_for_cycle([row],symbol='XRPUSDT',side='SHORT',cycle_id='c1',start_ms=100,end_ms=200,ownership_proof={})
