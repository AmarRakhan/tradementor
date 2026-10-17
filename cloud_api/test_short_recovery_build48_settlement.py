import unittest,threading
from decimal import Decimal as D
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_firestore_mock import encode,decode
from short_recovery_ledger import Ledger,Allocation
from short_recovery_order_claim_shadow import reserve
from short_recovery_order_settlement_shadow import settle
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class Tests(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.keys={k:('u','XRPUSDT',k) for k in ('claim','ledger','marker','owner')};self.bind()
  self.db.commit(self.keys['ledger'],0,encode(Ledger('u','XRPUSDT',(Allocation('z','c',D(100)),))))
  self.db.commit(self.keys['marker'],0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  self.db.commit(self.keys['owner'],0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownershipVerified':True,'ownerSide':'SHORT','cycleConfirmed':True,'state':'PARTIAL'})
  self.assertEqual(reserve(db=self.db,transactional=transactional,marker_ref=self.refs['marker'],owner_ref=self.refs['owner'],ledger_ref=self.refs['ledger'],claim_ref=self.refs['claim'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',now=1),'RESERVED_SHADOW')
 def bind(self):self.refs={k:Ref(self.db,v) for k,v in self.keys.items()}
 def event(self,name,**kw):return settle(db=self.db,transactional=transactional,claim_ref=self.refs['claim'],ledger_ref=self.refs['ledger'],owner_ref=self.refs['owner'],marker_ref=self.refs['marker'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event=name,**kw)
 def test_ack_then_partial_and_duplicate(self):
  self.assertEqual(self.event('ACK'),'ACKED')
  self.assertEqual(self.event('FILL',execution_id='x1',order_id='o',qty=25),'FILL_APPLIED')
  self.assertEqual(self.event('FILL',execution_id='x1',order_id='o',qty=25),'ALREADY_APPLIED')
  self.assertEqual(decode(self.db.snapshot(self.keys['ledger'])[1]).allocations[0].remaining,D(75))
 def test_full_final_and_no_repeat(self):
  self.event('ACK');self.assertEqual(self.event('FILL',execution_id='x',order_id='o',qty=100),'FILL_APPLIED')
  self.assertEqual(self.event('FILL',execution_id='y',order_id='o',qty=1),'ALREADY_TERMINAL')
 def test_unknown_never_release(self):
  self.assertEqual(self.event('UNKNOWN'),'BLOCKED_UNKNOWN')
  self.assertEqual(self.event('CANCEL_CONFIRMED'),'BLOCKED_TERMINAL_EVIDENCE_REQUIRED')
 def test_no_order_reconciled_terminal(self):
  self.assertEqual(self.event('RECONCILED_NO_ORDER'),'BLOCKED_TERMINAL_EVIDENCE_REQUIRED')
 def test_crash_restart_duplicate(self):
  self.event('ACK');self.event('FILL',execution_id='x',order_id='o',qty=25)
  self.db=self.db.restart();self.bind()
  self.assertEqual(self.event('FILL',execution_id='x',order_id='o',qty=25),'ALREADY_APPLIED')
 def test_concurrent_fill_workers(self):
  self.event('ACK');gate=threading.Barrier(5);out=[];lock=threading.Lock()
  def work():
   gate.wait();v=self.event('FILL',execution_id='x',order_id='o',qty=25)
   with lock:out.append(v)
  ts=[threading.Thread(target=work) for _ in range(5)]
  for t in ts:t.start()
  for t in ts:t.join(5);self.assertFalse(t.is_alive())
  self.assertCountEqual(out,['FILL_APPLIED']+['ALREADY_APPLIED']*4)
 def test_shadow_unrelated_pair_preserved(self):
  case=TestShadowReconciler();case.setUp();r=case.run_shadow({'XRPUSDT'})
  self.assertEqual(r['ordersSent'],0);self.assertEqual([a['symbol'] for a in r['actions']],['BTCUSDT'])
if __name__=='__main__':unittest.main()
