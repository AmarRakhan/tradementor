import unittest,threading
from decimal import Decimal as D
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_firestore_mock import encode
from short_recovery_ledger import Ledger,Allocation
from short_recovery_registry_shadow import register,discover_registry
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class Tests(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.account='u';self.sym='XRPUSDT';self.refs={k:Ref(self.db,('u','XRPUSDT',k)) for k in ('marker','ledger','owner')}
  self.db.commit(self.refs['ledger'].key,0,encode(Ledger('u','XRPUSDT',(Allocation('z','c',D(100)),))))
  self.db.commit(self.refs['owner'].key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownershipVerified':True,'cycleConfirmed':True,'ownerSide':'SHORT','state':'PARTIAL'})
 def reg(self):return register(db=self.db,transactional=transactional,marker_ref=self.refs['marker'],ledger_ref=self.refs['ledger'],owner_ref=self.refs['owner'],account='u',symbol='XRPUSDT',cycle='c')
 def read(self,k):return lambda a,s:self.db.snapshot((a,s,k))[1]
 def discover(self,marker=None):
  return discover_registry(account='u',symbols={'XRPUSDT','BTCUSDT'},read_marker=marker or self.read('marker'),read_ledger=self.read('ledger'),read_owner=self.read('owner'),settings={'enabled':True,'steps':4,'stepPct':'3'},protected_sides={'XRPUSDT':'LONG','BTCUSDT':'LONG'},existing_skip_symbols=set())
 def test_atomic_registration_and_restart(self):
  self.assertEqual(self.reg(),'REGISTERED');self.db=self.db.restart()
  self.assertEqual(self.reg(),'ALREADY_REGISTERED')
 def test_both_documents_missing_marker_survives(self):
  self.reg();self.db.docs.pop(self.refs['owner'].key);self.db.docs.pop(self.refs['ledger'].key)
  r=self.discover();self.assertIn('XRPUSDT',r['routing']['shadow_skip'])
  case=TestShadowReconciler();case.setUp();self.assertEqual([a['symbol'] for a in case.run_shadow(r['routing']['shadow_skip'])['actions']],['BTCUSDT'])
 def test_concurrent_registration_idempotent(self):
  barrier=threading.Barrier(6);out=[];lock=threading.Lock()
  def worker():
   barrier.wait();result=self.reg()
   with lock:out.append(result)
  ts=[threading.Thread(target=worker) for _ in range(6)]
  for t in ts:t.start()
  for t in ts:t.join(5);self.assertFalse(t.is_alive())
  self.assertCountEqual(out,['REGISTERED']+['ALREADY_REGISTERED']*5)
 def test_account_scoped(self):
  self.reg();self.assertIsNone(self.db.snapshot(('v','XRPUSDT','marker'))[1])
 def test_partial_marker_failure_fails_closed(self):
  self.reg()
  def unavailable(a,s):
   if s=='XRPUSDT':raise OSError('read failed')
   return None
  r=self.discover(unavailable);self.assertIn('XRPUSDT',r['routing']['shadow_skip'])
 def test_revoked_ownership_prevents_registration(self):
  key=self.refs['owner'].key
  version,owner=self.db.snapshot(key);owner['ownershipVerified']=False
  self.db.commit(key,version,owner)
  self.assertEqual(self.reg(),'BLOCKED_OWNER')
  self.assertIsNone(self.db.snapshot(self.refs['marker'].key)[1])
 def test_normal_pair_untouched(self):
  self.reg();r=self.discover();self.assertNotIn('BTCUSDT',r['routing']['shadow_skip'])
if __name__=='__main__':unittest.main()
