import threading, unittest
from decimal import Decimal as D
from short_recovery_order_resolution_shadow import resolve
from short_recovery_firestore_mock import decode
from test_short_recovery_build48_settlement import Tests as Base
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class Resolution(unittest.TestCase):
 def setUp(self):
  helper=Base(methodName='test_no_order_reconciled_terminal');helper.setUp();self.helper=helper
 def run_event(self,event,**kw):
  if event in ('FILL','LATE_FILL') and isinstance(kw.get('evidence'),dict) and kw['evidence'].get('confirmed') and kw.get('execution_id'):
   kw['evidence']={**kw['evidence'],'readbackVerified':True,'executionId':kw['execution_id'],'quantity':str(kw['quantity']),'realizedPnl':'1.25','commission':'0.05','funding':'0'}
  h=self.helper
  return resolve(db=h.db,transactional=__import__('short_recovery_multidoc_mock').transactional,claim_ref=h.refs['claim'],ledger_ref=h.refs['ledger'],marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event=event,**kw)
 def test_unknown_late_ack_partial(self):
  self.assertEqual(self.run_event('UNKNOWN'),'BLOCKED_UNKNOWN')
  self.assertEqual(self.run_event('LATE_ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED_RECOVERED')
  self.assertEqual(self.run_event('LATE_FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='x',quantity=25),'FILL_APPLIED')
  self.assertEqual(decode(self.helper.db.snapshot(self.helper.keys['ledger'])[1]).allocations[0].remaining,D(75))
 def test_unknown_unverified_terminal_blocked(self):
  self.run_event('UNKNOWN')
  self.assertEqual(self.run_event('NO_ORDER_TERMINAL',evidence={'confirmed':True,'intentId':'intent'}),'BLOCKED_NOT_TERMINAL')
 def test_cancel_race_late_fill_then_terminal(self):
  self.assertEqual(self.run_event('CANCEL_REQUESTED'),'WAIT_TERMINAL')
  self.assertEqual(self.run_event('LATE_FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='x',quantity=25),'FILL_APPLIED')
  self.assertEqual(self.run_event('CANCEL_TERMINAL',evidence={'confirmed':True,'noMoreFills':True,'intentId':'intent'}),'TERMINAL_VERIFIED')
 def test_restart_and_duplicate_fill(self):
  self.run_event('UNKNOWN');self.helper.db=self.helper.db.restart();self.helper.bind()
  self.assertEqual(self.run_event('LATE_FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='x',quantity=25),'FILL_APPLIED')
  self.assertEqual(self.run_event('LATE_FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='x',quantity=25),'ALREADY_APPLIED')
 def test_concurrent_late_fill_once(self):
  self.run_event('UNKNOWN');gate=threading.Barrier(5);out=[];lock=threading.Lock()
  def worker():
   gate.wait();r=self.run_event('LATE_FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='x',quantity=25)
   with lock:out.append(r)
  ts=[threading.Thread(target=worker) for _ in range(5)]
  for t in ts:t.start()
  for t in ts:t.join(5);self.assertFalse(t.is_alive())
  self.assertCountEqual(out,['FILL_APPLIED']+['ALREADY_APPLIED']*4)
 def test_normal_hedge_unchanged(self):
  case=TestShadowReconciler();case.setUp();result=case.run_shadow({'XRPUSDT'})
  self.assertEqual(result['ordersSent'],0);self.assertEqual([x['symbol'] for x in result['actions']],['BTCUSDT'])
