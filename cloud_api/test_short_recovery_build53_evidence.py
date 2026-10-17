import unittest
from short_recovery_aster_evidence_shadow import validate,EvidenceError
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class EvidenceTests(unittest.TestCase):
 def setUp(self):self.base={'source':'ASTER_READBACK_VERIFIED_MOCK','confirmed':True,'account':'u','symbol':'XRPUSDT','intentId':'i','orderId':'o','status':'NEW'}
 def check(self,row=None,kind='ACK',**kw):return validate(self.base if row is None else row,kind=kind,account='u',symbol='XRPUSDT',intent_id='i',**kw)
 def test_ack_and_scope(self):
  self.assertEqual(self.check()['status'],'VERIFIED_MOCK_ACK')
  for key in ('account','symbol','intentId','source'):
   with self.assertRaises(EvidenceError):self.check({**self.base,key:'other'})
  with self.assertRaises(EvidenceError):self.check(expected_order_id='wrong')
 def test_fill_and_idempotency(self):
  row={**self.base,'executionId':'e1','quantity':'25'}
  self.assertEqual(self.check(row,kind='FILL')['quantity'],25)
  self.assertEqual(self.check(row,kind='FILL',seen_execution_ids=frozenset({'e1'}))['status'],'ALREADY_APPLIED')
 def test_bad_quantities_rejected(self):
  for quantity in ('0','-1','NaN','Infinity','bad'):
   with self.assertRaises(EvidenceError):self.check({**self.base,'executionId':'e','quantity':quantity},kind='FILL')
 def test_cancel_finality(self):
  row={**self.base,'status':'CANCELED','noMoreFills':True,'terminalReadback':True}
  self.assertEqual(self.check(row,kind='CANCEL_TERMINAL')['status'],'VERIFIED_MOCK_CANCEL_TERMINAL')
  for key in ('noMoreFills','terminalReadback'):
   with self.assertRaises(EvidenceError):self.check({**row,key:False},kind='CANCEL_TERMINAL')
 def test_no_order_finality(self):
  row={**self.base,'status':'PROVEN_NOT_SUBMITTED','noMoreFills':True,'terminalReadback':True}
  self.assertEqual(self.check(row,kind='NO_ORDER_TERMINAL')['status'],'VERIFIED_MOCK_NO_ORDER_TERMINAL')
  with self.assertRaises(EvidenceError):self.check({**row,'status':'UNKNOWN'},kind='NO_ORDER_TERMINAL')
 def test_normal_hedge_shadow(self):
  c=TestShadowReconciler();c.setUp();r=c.run_shadow({'XRPUSDT'})
  self.assertEqual(r['ordersSent'],0)
  self.assertEqual([x['symbol'] for x in r['actions']],['BTCUSDT'])
