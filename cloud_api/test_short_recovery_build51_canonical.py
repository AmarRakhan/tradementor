"""Both legacy and resolution event APIs share canonical offline transition engine."""
import unittest
from short_recovery_order_resolution_shadow import resolve
from test_short_recovery_build48_settlement import Tests as Fixture
from short_recovery_multidoc_mock import transactional
class Canonical(unittest.TestCase):
 def setUp(self):
  self.h=Fixture('test_ack_then_partial_and_duplicate');self.h.setUp()
 def call(self,event,**kwargs):
  h=self.h
  return resolve(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],ledger_ref=h.refs['ledger'],marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event=event,**kwargs)
 def test_unknown_no_unverified_release(self):
  self.assertEqual(self.h.event('UNKNOWN'),'BLOCKED_UNKNOWN')
  self.assertEqual(self.h.event('RECONCILED_NO_ORDER'),'BLOCKED_TERMINAL_EVIDENCE_REQUIRED')
  self.assertEqual(self.call('NO_ORDER_TERMINAL'),'BLOCKED_NOT_TERMINAL')
 def test_late_fill_after_unknown(self):
  self.h.event('UNKNOWN')
  self.assertEqual(self.call('LATE_FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='x',quantity=25),'FILL_APPLIED')
  self.assertEqual(self.call('LATE_FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='x',quantity=25),'ALREADY_APPLIED')
 def test_terminal_requires_finality(self):
  self.assertEqual(self.call('CANCEL_REQUESTED'),'WAIT_TERMINAL')
  self.assertEqual(self.call('CANCEL_TERMINAL',evidence={'confirmed':True,'intentId':'intent'}),'BLOCKED_NOT_TERMINAL')
  self.assertEqual(self.call('CANCEL_TERMINAL',evidence={'confirmed':True,'noMoreFills':True,'intentId':'intent'}),'TERMINAL_VERIFIED')
 def test_invalid_ack_without_evidence(self):
  self.assertEqual(self.call('ACK'),'BLOCKED_NO_EVIDENCE')
if __name__=='__main__':unittest.main()
