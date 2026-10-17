import unittest
from decimal import Decimal
from short_recovery_funding_shadow import conservative_symbol_funding_floor as floor
class ConservativeSymbolFunding(unittest.TestCase):
 def setUp(self):
  self.coverage={'independentlyVerified':True,'complete':True,'symbol':'XRPUSDT','startMs':100,'endMs':200}
  self.rows=[{'incomeType':'FUNDING_FEE','symbol':'XRPUSDT','time':150,'tranId':'a','income':'-0.03'}, {'incomeType':'FUNDING_FEE','symbol':'XRPUSDT','time':151,'tranId':'b','income':'0.01'}, {'incomeType':'FUNDING_FEE','symbol':'XRPUSDT','time':152,'tranId':'c','income':'-0.04'}]
 def call(self,rows=None,coverage=None):return floor(self.rows if rows is None else rows,symbol='XRPUSDT',start_ms=100,end_ms=200,coverage=self.coverage if coverage is None else coverage)
 def test_charges_all_symbol_losses_ignores_benefits(self):self.assertEqual(self.call(),Decimal('-0.07'))
 def test_missing_coverage_never_assumes_zero(self):
  with self.assertRaisesRegex(ValueError,'BLOCKED_SYMBOL_COVERAGE_PROOF'):self.call([],{})
 def test_incomplete_income_never_authorized(self):
  with self.assertRaisesRegex(ValueError,'BLOCKED_SYMBOL_COVERAGE_PROOF'):self.call(self.rows,self.coverage|{'complete':False})
 def test_mismatched_window_never_authorized(self):
  with self.assertRaisesRegex(ValueError,'BLOCKED_SYMBOL_COVERAGE_PROOF'):self.call(self.rows,self.coverage|{'startMs':101})
 def test_duplicate_income_never_debits_twice(self):
  with self.assertRaisesRegex(ValueError,'BLOCKED_SYMBOL_INCOME'):self.call(self.rows+[self.rows[0]])
 def test_nonfinite_amount_blocked(self):
  with self.assertRaisesRegex(ValueError,'BLOCKED_SYMBOL_INCOME'):self.call([self.rows[0]|{'income':'NaN'}])
 def test_verified_empty_window_is_zero_only_with_separate_attestation(self):self.assertEqual(self.call([]),Decimal('0'))
