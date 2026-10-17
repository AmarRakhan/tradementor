import unittest
from short_recovery_executor_adapter import verify_pair_exit_settlement

class PairExit(unittest.TestCase):
 def row(self,side,**kwargs):
  row={'positionSide':side,'action':'CLOSE','orderId':side+'-id','status':'FILLED','terminalVerified':True,'executedQty':'100' if side=='LONG' else '75','fillsComplete':True,'financialVerified':True,'fundingOwnershipVerified':True,'incomeHistoryComplete':True}
  row.update(kwargs);return row
 def gate(self,long=None,short=None):
  return verify_pair_exit_settlement(long_order=self.row('LONG') if long is None else long,short_order=self.row('SHORT') if short is None else short,required_long=100,required_short=75)
 def test_both_fully_verified(self):
  x=self.gate();self.assertEqual(x['status'],'PAIR_EXIT_SETTLED_SHADOW');self.assertTrue(x['pairClosed']);self.assertEqual(x['ordersSent'],0)
 def test_one_side_partial_fails_closed(self):
  self.assertEqual(self.gate(short=self.row('SHORT',executedQty='25',status='PARTIALLY_FILLED'))['status'],'BLOCKED_NOT_TERMINAL')
  self.assertEqual(self.gate(short=self.row('SHORT',executedQty='25'))['status'],'BLOCKED_PARTIAL_OR_MISMATCH')
 def test_one_side_missing_or_unknown(self):
  self.assertEqual(self.gate(short={})['status'],'BLOCKED_QUANTITY_EVIDENCE')
  self.assertEqual(self.gate(long=self.row('LONG',status='UNKNOWN'))['status'],'BLOCKED_NOT_TERMINAL')
 def test_rejected_side_does_not_flatten_pair(self):
  self.assertEqual(self.gate(short=self.row('SHORT',status='REJECTED',executedQty='0'))['status'],'BLOCKED_NOT_TERMINAL')
 def test_costs_and_funding_incomplete(self):
  for name in ('fillsComplete','financialVerified','fundingOwnershipVerified','incomeHistoryComplete'):
   with self.subTest(name=name):self.assertEqual(self.gate(short=self.row('SHORT',**{name:False}))['status'],'BLOCKED_FINANCIAL_EVIDENCE')
 def test_no_crossed_side_evidence(self):
  self.assertEqual(self.gate(short=self.row('LONG'))['status'],'BLOCKED_SIDE_IDENTITY')
 def test_cancelled_with_partial_execution(self):
  self.assertEqual(self.gate(long=self.row('LONG',status='CANCELED',executedQty='50'))['status'],'BLOCKED_NOT_TERMINAL')
