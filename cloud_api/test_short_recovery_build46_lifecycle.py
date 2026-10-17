"""Marker-first offline lifecycle, using real reconciler with execute=False only."""
import unittest,threading
from decimal import Decimal as D
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_firestore_mock import encode,decode
from short_recovery_ledger import Ledger,Allocation,Fill
from short_recovery_marker_lifecycle_shadow import prepare,book_mock_fill
from short_recovery_registry_shadow import discover_registry
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class Lifecycle(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.keys={kind:('u','XRPUSDT',kind) for kind in ('marker','ledger','owner')};self.bind()
  self.db.commit(self.keys['ledger'],0,encode(Ledger('u','XRPUSDT',(Allocation('z','c',D(100)),))))
  self.db.commit(self.keys['owner'],0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'})
 def bind(self):self.refs={k:Ref(self.db,v) for k,v in self.keys.items()}
 def prepare(self):return prepare(db=self.db,transactional=transactional,marker_ref=self.refs['marker'],ledger_ref=self.refs['ledger'],owner_ref=self.refs['owner'],account='u',symbol='XRPUSDT',cycle='c')
 def book(self,id='e1'):
  return book_mock_fill(db=self.db,transactional=transactional,marker_ref=self.refs['marker'],ledger_ref=self.refs['ledger'],owner_ref=self.refs['owner'],fill=Fill('u','XRPUSDT',id,'order-'+id,D(25),D(0),D(0)),splits=(('z','c',D(25)),),account='u',symbol='XRPUSDT',cycle='c')
 def route(self):
  def read(k):return lambda a,s:self.db.snapshot((a,s,k))[1]
  return discover_registry(account='u',symbols={'XRPUSDT','BTCUSDT'},read_marker=read('marker'),read_ledger=read('ledger'),read_owner=read('owner'),settings={'enabled':True,'steps':4,'stepPct':'3'},protected_sides={'XRPUSDT':'LONG','BTCUSDT':'LONG'},existing_skip_symbols=set())
 def test_mark_first_then_fill(self):
  self.assertEqual(self.book(),'BLOCKED_MARKER')
  self.assertEqual(self.prepare()['status'],'SHADOW_READY')
  self.assertEqual(self.book(),'APPLIED')
  self.assertEqual(decode(self.db.snapshot(self.keys['ledger'])[1]).allocations[0].remaining,D(75))
  case=TestShadowReconciler();case.setUp();self.assertEqual([a['symbol'] for a in case.run_shadow(self.route()['routing']['shadow_skip'])['actions']],['BTCUSDT'])
 def test_restart_duplicate_fill(self):
  self.prepare();self.book();self.db=self.db.restart();self.bind()
  self.assertEqual(self.prepare()['status'],'SHADOW_READY')
  self.assertEqual(self.book(),'ALREADY_APPLIED')
 def test_missing_owner_blocks_registration(self):
  self.db.docs.pop(self.keys['owner']);self.assertEqual(self.prepare()['status'],'BLOCKED_MARKER');self.assertEqual(self.book(),'BLOCKED_MARKER')
 def test_ownership_revoked_after_marker_blocks_fill(self):
  self.prepare();v,owner=self.db.snapshot(self.keys['owner']);owner['ownershipVerified']=False;self.db.commit(self.keys['owner'],v,owner)
  self.assertEqual(self.book(),'BLOCKED_OWNERSHIP')
 def test_marker_revoked_after_prepare_blocks_fill(self):
  self.prepare();v,marker=self.db.snapshot(self.keys['marker']);marker['state']='REVOKED';self.db.commit(self.keys['marker'],v,marker)
  self.assertEqual(self.book(),'BLOCKED_MARKER')
  self.assertEqual(decode(self.db.snapshot(self.keys['ledger'])[1]).allocations[0].remaining,D(100))
 def test_marker_read_failure_prevents_fill(self):
  self.prepare();self.db.docs.pop(self.keys['marker'])
  self.assertEqual(self.book(),'BLOCKED_MARKER')
 def test_concurrent_workers_duplicate_fill(self):
  self.prepare();barrier=threading.Barrier(6);lock=threading.Lock();result=[]
  def run():
   barrier.wait();r=self.book()
   with lock:result.append(r)
  ts=[threading.Thread(target=run) for _ in range(6)]
  for t in ts:t.start()
  for t in ts:t.join(5);self.assertFalse(t.is_alive())
  self.assertCountEqual(result,['APPLIED']+['ALREADY_APPLIED']*5)
if __name__=='__main__':unittest.main()
