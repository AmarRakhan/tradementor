import unittest,threading
from short_recovery_executor_adapter import pair_exit_recovery_gate
class PairGate(unittest.TestCase):
 def row(self,side,**kw):
  d={'positionSide':side,'action':'CLOSE','orderId':side,'status':'FILLED','terminalVerified':True,
     'executedQty':'100' if side=='LONG' else '75','fillsComplete':True,'financialVerified':True,
     'fundingOwnershipVerified':True,'incomeHistoryComplete':True}
  d.update(kw);return d
 def check(self,**kw):
  args=dict(long_order=self.row('LONG'),short_order=self.row('SHORT'),required_long=100,required_short=75,
            claim_states={'LONG':'CLOSED','SHORT':'CLOSED'},funding_proof=True,stop_active=False)
  args.update(kw);return pair_exit_recovery_gate(**args)
 def test_complete_pair_requires_both_claims(self):
  self.assertTrue(self.check()['pairClosed'])
  self.assertFalse(self.check(claim_states={'LONG':'CLOSED','SHORT':'UNKNOWN'})['pairClosed'])
 def test_partial_or_rejected_side_cannot_retry(self):
  for row in (self.row('SHORT',status='PARTIALLY_FILLED',executedQty='25'),self.row('SHORT',status='REJECTED',executedQty='0')):
   with self.subTest(row=row):
    result=self.check(short_order=row)
    self.assertFalse(result['pairClosed']);self.assertFalse(result['retryAllowed']);self.assertEqual(result['ordersSent'],0)
 def test_unknown_preserved_after_restart_style_readback(self):
  result=self.check(short_order=self.row('SHORT',status='UNKNOWN'),claim_states={'LONG':'CLOSED','SHORT':'UNKNOWN'})
  self.assertEqual(result['status'],'RECONCILE_ONLY_UNCERTAIN')
 def test_funding_missing_holds(self):
  self.assertFalse(self.check(funding_proof=False)['pairClosed'])
  self.assertFalse(self.check(short_order=self.row('SHORT',fundingOwnershipVerified=False))['pairClosed'])
 def test_emergency_still_allows_readback_but_no_retry(self):
  r=self.check(stop_active=True,claim_states={'LONG':'CLOSED','SHORT':'UNKNOWN'})
  self.assertEqual(r['status'],'RECONCILE_ONLY_STOPPED');self.assertFalse(r['retryAllowed'])
 def test_concurrent_checks_never_emit_orders(self):
  barrier=threading.Barrier(6);out=[];lock=threading.Lock()
  def worker():
   barrier.wait();v=self.check(short_order=self.row('SHORT',status='UNKNOWN'),claim_states={'LONG':'CLOSED','SHORT':'UNKNOWN'})
   with lock:out.append(v)
  ts=[threading.Thread(target=worker) for _ in range(6)]
  for t in ts:t.start()
  for t in ts:t.join(5);self.assertFalse(t.is_alive())
  self.assertEqual(len(out),6);self.assertTrue(all(v['ordersSent']==0 and not v['retryAllowed'] for v in out))
