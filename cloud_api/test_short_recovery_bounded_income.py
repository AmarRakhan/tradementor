import unittest
from short_recovery_funding_shadow import read_bounded_symbol_funding,conservative_symbol_funding_floor
class Mock:
 def __init__(self,rows):self.rows=rows;self.calls=[]
 def income_history(self,**kw):
  self.calls.append(kw)
  return [r for r in self.rows if kw['start_time']<=r['time']<=kw['end_time']][:kw['limit']]
class BoundedIncome(unittest.TestCase):
 def row(self,i,t):return {'tranId':str(i),'time':t,'symbol':'XRPUSDT','incomeType':'FUNDING_FEE','income':'-0.01'}
 def read(self,c,**kw):return read_bounded_symbol_funding(c,symbol='XRPUSDT',account='user-1',start_ms=100,end_ms=86_400_101,limit=10,**kw)
 def test_inclusive_intervals_are_disjoint_and_non_authorizing(self):
  c=Mock([self.row(1,100),self.row(2,86_400_099),self.row(3,86_400_100)])
  result=self.read(c)
  self.assertEqual(len(result['rows']),3)
  self.assertEqual([(x['start_time'],x['end_time']) for x in c.calls],[(100,86_400_099),(86_400_100,86_400_100)])
  self.assertFalse(result['independentlyVerified'])
  with self.assertRaisesRegex(ValueError,'COVERAGE_PROOF'):
   conservative_symbol_funding_floor(result['rows'],symbol='XRPUSDT',start_ms=100,end_ms=86_400_101,coverage=result)
 def test_full_page_fails_even_if_rows_have_unique_ids(self):
  c=Mock([self.row(i,100) for i in range(10)])
  with self.assertRaisesRegex(ValueError,'PAGE_COMPLETENESS'):self.read(c)
 def test_duplicate_transaction_across_pages_fails(self):
  c=Mock([self.row(1,100),self.row(1,86_400_100)])
  with self.assertRaisesRegex(ValueError,'BLOCKED_FUNDING_ROW'):self.read(c)
 def test_wrong_symbol_or_income_type_fails(self):
  c=Mock([self.row(1,100)|{'incomeType':'COMMISSION'}])
  with self.assertRaisesRegex(ValueError,'BLOCKED_FUNDING_ROW'):self.read(c)
 def test_empty_income_never_certifies_zero(self):
  result=self.read(Mock([]))
  self.assertFalse(result['complete'])
 def test_no_account_scope_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'WINDOW'):
   read_bounded_symbol_funding(Mock([]),symbol='XRPUSDT',account='',start_ms=100,end_ms=200)
