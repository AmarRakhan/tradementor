"""Partial terminal claims remain owned and are never silently released."""
import unittest
from short_recovery_order_resolution_shadow import resolve
from short_recovery_order_claim_shadow import reserve
from short_recovery_multidoc_mock import transactional
from short_recovery_firestore_mock import decode
from test_short_recovery_build48_settlement import Tests as Fixture
class PartialTerminal(unittest.TestCase):
 def setUp(self):
  self.h=Fixture('test_unknown_never_release');self.h.setUp()
 def event(self,name,**kw):
  h=self.h
  return resolve(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],ledger_ref=h.refs['ledger'],marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event=name,**kw)
 def reserve_again(self):
  h=self.h;r=h.refs
  return reserve(db=h.db,transactional=transactional,claim_ref=r['claim'],ledger_ref=r['ledger'],marker_ref=r['marker'],owner_ref=r['owner'],control_ref=r['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id='next',now=4)
 def test_partial_fill_then_confirmed_cancel_keeps_claim_and_inventory(self):
  self.assertEqual(self.event('ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED')
  e={'confirmed':True,'orderId':'o','executionId':'x','quantity':'25','readbackVerified':True,'realizedPnl':'1','commission':'.1','funding':'0'}
  self.assertEqual(self.event('FILL',evidence=e,execution_id='x',quantity=25),'FILL_APPLIED')
  self.assertEqual(self.event('CANCEL_TERMINAL',evidence={'confirmed':True,'noMoreFills':True,'intentId':'intent','terminalReadbackVerified':True,'orderId':'o','orderStatus':'CANCELED'}),'PARTIAL_TERMINAL_RECONCILE_REQUIRED')
  self.assertEqual(self.h.db.snapshot(self.h.keys['claim'])[1]['state'],'PARTIAL_TERMINAL')
  self.assertEqual(decode(self.h.db.snapshot(self.h.keys['ledger'])[1]).allocations[0].remaining,75)
  self.assertEqual(self.reserve_again(),'BLOCKED_UNRESOLVED_CLAIM')
  self.assertEqual(self.event('LATE_FILL',evidence=e,execution_id='x',quantity=25),'BLOCKED_TERMINAL_CONFLICT')
 def test_unknown_then_cancel_requires_proof(self):
  self.assertEqual(self.event('UNKNOWN'),'BLOCKED_UNKNOWN')
  self.assertEqual(self.event('CANCEL_TERMINAL',evidence={'confirmed':True}),'BLOCKED_NOT_TERMINAL')
  self.assertEqual(self.reserve_again(),'BLOCKED_UNRESOLVED_CLAIM')
 def test_restart_keeps_terminal_claim(self):
  self.event('ACK',evidence={'confirmed':True,'orderId':'o'})
  self.event('FILL',evidence={'confirmed':True,'readbackVerified':True,'orderId':'o','executionId':'x','quantity':'25','realizedPnl':'1','commission':'.1','funding':'0'},execution_id='x',quantity=25)
  self.event('CANCEL_TERMINAL',evidence={'confirmed':True,'noMoreFills':True,'intentId':'intent','terminalReadbackVerified':True,'orderId':'o','orderStatus':'CANCELED'})
  self.h.db=self.h.db.restart();self.h.bind()
  self.assertEqual(self.reserve_again(),'BLOCKED_UNRESOLVED_CLAIM')

 def test_partial_terminal_wrong_order_is_blocked(self):
  self.event('ACK',evidence={'confirmed':True,'orderId':'o'})
  self.event('FILL',evidence={'confirmed':True,'readbackVerified':True,'orderId':'o','executionId':'x','quantity':'25','realizedPnl':'1','commission':'.1','funding':'0'},execution_id='x',quantity=25)
  evidence={'confirmed':True,'noMoreFills':True,'intentId':'intent','terminalReadbackVerified':True,'orderId':'wrong'}
  self.assertEqual(self.event('CANCEL_TERMINAL',evidence=evidence),'BLOCKED_PARTIAL_TERMINAL_ORDER_PROOF')
  self.assertEqual(self.reserve_again(),'BLOCKED_UNRESOLVED_CLAIM')
 def test_partial_terminal_requires_independent_readback(self):
  self.event('ACK',evidence={'confirmed':True,'orderId':'o'})
  self.event('FILL',evidence={'confirmed':True,'readbackVerified':True,'orderId':'o','executionId':'x','quantity':'25','realizedPnl':'1','commission':'.1','funding':'0'},execution_id='x',quantity=25)
  self.assertEqual(self.event('CANCEL_TERMINAL',evidence={'confirmed':True,'noMoreFills':True,'intentId':'intent','orderId':'o'}),'BLOCKED_PARTIAL_TERMINAL_ORDER_PROOF')

 def test_unknown_late_ack_cannot_rebind_original_order(self):
  self.event('ACK',evidence={'confirmed':True,'orderId':'original'})
  self.event('UNKNOWN')
  self.assertEqual(self.event('LATE_ACK',evidence={'confirmed':True,'orderId':'different'}),'BLOCKED_ORDER_MISMATCH')
  self.assertEqual(self.h.db.snapshot(self.h.keys['claim'])[1]['orderId'],'original')
  self.assertEqual(self.h.db.snapshot(self.h.keys['claim'])[1]['state'],'UNKNOWN')
  self.assertEqual(self.reserve_again(),'BLOCKED_UNRESOLVED_CLAIM')

 def test_unknown_bound_order_cannot_be_reconciled_as_no_order(self):
  self.event('ACK',evidence={'confirmed':True,'orderId':'o'})
  self.event('UNKNOWN')
  result=self.event('NO_ORDER_TERMINAL',evidence={'confirmed':True,'noMoreFills':True,'intentId':'intent'})
  self.assertEqual(result,'BLOCKED_KNOWN_ORDER_EXISTS')
  self.assertEqual(self.h.db.snapshot(self.h.keys['claim'])[1]['state'],'UNKNOWN')
  self.assertEqual(self.reserve_again(),'BLOCKED_UNRESOLVED_CLAIM')

 def test_partial_fill_cannot_finalize_from_filled_or_unknown_status(self):
  self.event('ACK',evidence={'confirmed':True,'orderId':'o'})
  e={'confirmed':True,'orderId':'o','executionId':'x','quantity':'25','readbackVerified':True,'realizedPnl':'1','commission':'.1','funding':'0'}
  self.event('FILL',evidence=e,execution_id='x',quantity=25)
  for status in ('FILLED','NEW','REJECTED',None):
   proof={'confirmed':True,'noMoreFills':True,'intentId':'intent','terminalReadbackVerified':True,'orderId':'o','orderStatus':status}
   self.assertEqual(self.event('CANCEL_TERMINAL',evidence=proof),'BLOCKED_PARTIAL_NOT_CANCELLED')
   self.assertEqual(self.reserve_again(),'BLOCKED_UNRESOLVED_CLAIM')
