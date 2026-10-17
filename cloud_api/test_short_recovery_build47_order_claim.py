import threading,unittest
from decimal import Decimal as D
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_firestore_mock import encode
from short_recovery_ledger import Ledger,Allocation
from short_recovery_order_claim_shadow import reserve
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class Tests(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.keys={k:('u','XRPUSDT',k) for k in ('marker','owner','ledger','claim','control')};self.bind()
  self.db.commit(self.keys['marker'],0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  self.db.commit(self.keys['owner'],0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'})
  self.db.commit(self.keys['ledger'],0,encode(Ledger('u','XRPUSDT',(Allocation('z','c',D(100)),))))
  self.db.commit(self.keys['control'],0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
 def bind(self):self.refs={k:Ref(self.db,v) for k,v in self.keys.items()}
 def reserve(self,intent='id1',now=100):return reserve(db=self.db,transactional=transactional,marker_ref=self.refs['marker'],owner_ref=self.refs['owner'],ledger_ref=self.refs['ledger'],claim_ref=self.refs['claim'],control_ref=self.refs['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id=intent,now=now)
 def test_same_intent_idempotent(self):
  self.assertEqual(self.reserve(),'RESERVED_SHADOW');self.assertEqual(self.reserve(),'ALREADY_RESERVED')
 def test_different_intent_and_expired_lease_block(self):
  self.reserve();self.assertEqual(self.reserve('id2',now=10000),'BLOCKED_UNRESOLVED_CLAIM')
 def test_restart_unknown_order_outcome_block(self):
  self.reserve();self.db=self.db.restart();self.bind()
  self.assertEqual(self.reserve('new',now=9999),'BLOCKED_UNRESOLVED_CLAIM')
 def test_missing_marker_no_claim(self):
  self.db.docs.pop(self.keys['marker']);self.assertEqual(self.reserve(),'BLOCKED_MARKER')
  self.assertIsNone(self.db.snapshot(self.keys['claim'])[1])
 def test_revoked_owner_no_claim(self):
  version,owner=self.db.snapshot(self.keys['owner']);owner['ownershipVerified']=False;self.db.commit(self.keys['owner'],version,owner)
  self.assertEqual(self.reserve(),'BLOCKED_OWNER')
 def test_concurrent_intents_only_one_reservation(self):
  barrier=threading.Barrier(8);results=[];lock=threading.Lock()
  def worker(i):
   barrier.wait();outcome=self.reserve('id'+str(i))
   with lock:results.append(outcome)
  threads=[threading.Thread(target=worker,args=(i,)) for i in range(8)]
  for t in threads:t.start()
  for t in threads:t.join(5);self.assertFalse(t.is_alive())
  self.assertEqual(results.count('RESERVED_SHADOW'),1)
  self.assertEqual(results.count('BLOCKED_UNRESOLVED_CLAIM'),7)
 def test_shadow_legacy_no_orders_and_other_pair(self):
  case=TestShadowReconciler();case.setUp();result=case.run_shadow({'XRPUSDT'})
  self.assertEqual(result['ordersSent'],0)
  self.assertEqual([a['symbol'] for a in result['actions']],['BTCUSDT'])
if __name__=='__main__':unittest.main()
