"""Real Firestore emulator race and lease expiry for OFFLINE-only fence."""
import os, unittest, uuid
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_lease_fence_offline import reserve_offline_fence
from short_recovery_firestore_mock import encode
from short_recovery_ledger import Ledger, Allocation
from decimal import Decimal

@unittest.skipUnless(os.getenv('FIRESTORE_EMULATOR_HOST')=='127.0.0.1:18783' and os.getenv('GOOGLE_CLOUD_PROJECT')=='amar-short-recovery-offline-test','isolated emulator required')
class EmulatorFence(unittest.TestCase):
 def setUp(self):
  from google.cloud import firestore
  self.firestore=firestore
  self.db=firestore.Client(project='amar-short-recovery-offline-test')
  base=self.db.collection('offline_fence').document(uuid.uuid4().hex)
  self.refs={x:base.collection('docs').document(x) for x in ('lease','owner','claim','ledger','control')}
  self.now=datetime.now(timezone.utc)
  rows={'lease':{'lease':{'token':'token-1','until':self.now+timedelta(seconds=60)}},'owner':{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'},'claim':{'account':'u','symbol':'XRPUSDT','cycle':'c','side':'SHORT','action':'CLOSE','state':'PARTIAL','step':1,'intentId':canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1),'executedQty':'25'},'ledger':encode(Ledger('u','XRPUSDT',(Allocation('z','c',Decimal(75)),))),'control':{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False}}
  for k,v in rows.items():self.refs[k].set(v)
 def reserve(self,i=0,now=None,token='token-1'):
  return reserve_offline_fence(db=self.db,transactional=self.firestore.transactional,**{k+'_ref':v for k,v in self.refs.items()},account='u',symbol='XRPUSDT',cycle='c',lease_token=token,intent_id=f'intent-{i}',now=now or self.now)
 def test_atomic_single_winner_real_sdk(self):
  with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(self.reserve,range(4)))
  self.assertEqual(results.count('RESERVED_OFFLINE_ONLY'),1,results)
  self.assertTrue(all(x in ('RESERVED_OFFLINE_ONLY','BLOCKED_FENCE_ALREADY_RESERVED','BLOCKED_TRANSACTION_FAILURE') for x in results),results)
 def test_expired_lease_real_sdk(self):
  self.assertEqual(self.reserve(now=self.now+timedelta(seconds=70)),'BLOCKED_LEASE_EXPIRED')
  self.assertFalse('recoveryFenceReservation' in (self.refs['lease'].get().to_dict() or {}))
 def test_revoked_token_real_sdk(self):
  self.refs['lease'].update({'lease':{'token':'replacement','until':self.now+timedelta(seconds=60)}})
  self.assertEqual(self.reserve(),'BLOCKED_LEASE_STALE')
 def test_restarted_client_does_not_rereserve(self):
  self.assertEqual(self.reserve(),'RESERVED_OFFLINE_ONLY')
  self.db=self.firestore.Client(project='amar-short-recovery-offline-test')
  self.assertEqual(self.reserve(2),'BLOCKED_FENCE_ALREADY_RESERVED')
 def test_competing_claim_update_and_fence_reservation(self):
  """A concurrent claim transition cannot make a stale read commit."""
  import threading
  barrier=threading.Barrier(2)
  def reserve_race():
   barrier.wait(timeout=10)
   return self.reserve(i=9)
  def change_claim():
   barrier.wait(timeout=10)
   self.refs['claim'].update({'state':'SUBMITTING'})
   return 'CHANGED'
  with ThreadPoolExecutor(max_workers=2) as pool:
   a=pool.submit(reserve_race);b=pool.submit(change_claim)
   outcome=a.result(timeout=25);b.result(timeout=25)
  self.assertIn(outcome,('RESERVED_OFFLINE_ONLY','BLOCKED_UNRESOLVED_RECOVERY','BLOCKED_TRANSACTION_FAILURE'))
  # If reservation won first, the Recovery writer would also need to check its
  # lease fence. This test does not claim a cross-service mutual exclusion.
  if outcome=='RESERVED_OFFLINE_ONLY':
   self.assertEqual(self.refs['lease'].get().to_dict()['recoveryFenceReservation']['state'],'OFFLINE_ONLY')
 def test_emergency_stop_rejects_reservation_real_sdk(self):
  self.refs['control'].update({'emergencyStop':True})
  self.assertEqual(self.reserve(),'BLOCKED_STOP')
 def test_unreliable_claim_quantity_rejected_real_sdk(self):
  self.refs['claim'].update({'executedQty':'NaN'})
  self.assertEqual(self.reserve(),'BLOCKED_CLAIM')
 def test_two_way_recovery_claim_vs_autohedge_fence(self):
  """Both canonical reservations share the same Firestore coordination read set."""
  from short_recovery_order_claim_shadow import reserve
  from short_recovery_firestore_mock import encode
  from short_recovery_ledger import Ledger, Allocation
  from decimal import Decimal
  import threading
  base=self.refs['lease'].parent
  marker=base.document('marker')
  marker.set({'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  self.refs['ledger'].set(encode(Ledger('u','XRPUSDT',(Allocation('z','c',Decimal(100)),))))
  # This test models a claim that exists after an earlier partial reduction.
  # Both contenders must not acquire a *new* execution right.
  barrier=threading.Barrier(2)
  def recovery():
   barrier.wait(timeout=10)
   return reserve(db=self.db,transactional=self.firestore.transactional,marker_ref=marker,
     owner_ref=self.refs['owner'],ledger_ref=self.refs['ledger'],claim_ref=self.refs['claim'],
     control_ref=self.refs['control'],coordination_ref=self.refs['lease'],account='u',
     symbol='XRPUSDT',cycle='c',intent_id='new-reduction',now=1)
  def topup():
   barrier.wait(timeout=10)
   return self.reserve(i=99)
  with ThreadPoolExecutor(max_workers=2) as pool:
   a=pool.submit(recovery);b=pool.submit(topup)
   outcomes=(a.result(timeout=30),b.result(timeout=30))
  self.assertNotEqual(outcomes[0],'RESERVED_SHADOW',outcomes)
  self.assertIn(outcomes[1],('RESERVED_OFFLINE_ONLY','BLOCKED_FENCE_ALREADY_RESERVED','BLOCKED_TRANSACTION_FAILURE'),outcomes)
 def test_new_reduction_claim_races_with_fence_on_real_emulator(self):
  """A fresh canonical CLOSE claim and a legacy topup must not both win."""
  from short_recovery_order_claim_shadow import reserve, canonical_intent_id
  from short_recovery_firestore_mock import encode
  from short_recovery_ledger import Ledger, Allocation
  from decimal import Decimal
  import threading
  base=self.refs['lease'].parent
  marker=base.document('marker')
  marker.set({'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  self.refs['ledger'].set(encode(Ledger('u','XRPUSDT',(Allocation('z','c',Decimal(100)),))))
  self.refs['claim'].delete()
  self.refs['lease'].set({})  # No active Auto Hedge owner when claiming new Recovery work.
  step_id=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=2)
  barrier=threading.Barrier(2)
  def recovery():
   barrier.wait(timeout=10)
   return reserve(db=self.db,transactional=self.firestore.transactional,marker_ref=marker,
    owner_ref=self.refs['owner'],ledger_ref=self.refs['ledger'],claim_ref=self.refs['claim'],
    control_ref=self.refs['control'],coordination_ref=self.refs['lease'],account='u',
    symbol='XRPUSDT',cycle='c',intent_id=step_id,now=1,side='SHORT',action='CLOSE',step=2)
  def legacy():
   barrier.wait(timeout=10)
   return self.reserve(i=101)
  with ThreadPoolExecutor(max_workers=2) as pool:
   future_a=pool.submit(recovery);future_b=pool.submit(legacy)
   a,b=future_a.result(timeout=30),future_b.result(timeout=30)
  self.assertEqual(a,'RESERVED_SHADOW',(a,b))
  self.assertNotEqual(b,'RESERVED_OFFLINE_ONLY',(a,b))
  self.assertEqual(self.refs['claim'].get().to_dict()['intentId'],step_id)
  self.assertEqual(self.refs['lease'].get().to_dict()['recoveryFenceReservation']['state'],'RECOVERY_CLAIM_RESERVED')
 def test_submit_lock_persists_shared_fence_and_blocks_topup_after_restart(self):
  from short_recovery_order_claim_shadow import reserve, submit_once_offline
  from types import SimpleNamespace
  base=self.refs['lease'].parent
  marker=base.document('marker')
  marker.set({'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  self.refs['claim'].delete()
  self.refs['lease'].set({})
  intent_id=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=2)
  kwargs=dict(db=self.db,transactional=self.firestore.transactional,marker_ref=marker,
   owner_ref=self.refs['owner'],ledger_ref=self.refs['ledger'],claim_ref=self.refs['claim'],
   control_ref=self.refs['control'],coordination_ref=self.refs['lease'],account='u',
   symbol='XRPUSDT',cycle='c',intent_id=intent_id,now=1,side='SHORT',action='CLOSE',step=2)
  self.assertEqual(reserve(**kwargs),'RESERVED_SHADOW')
  posted=[]
  intent=SimpleNamespace(intent_id=intent_id,symbol='XRPUSDT',position_side=SimpleNamespace(value='SHORT'),action='CLOSE')
  def submit(_): posted.append(intent_id)
  call=lambda:submit_once_offline(db=self.db,transactional=self.firestore.transactional,
   claim_ref=self.refs['claim'],control_ref=self.refs['control'],coordination_ref=self.refs['lease'],
   account='u',symbol='XRPUSDT',cycle='c',intent=intent,
   account_close_guard=lambda:None,submit_mock=submit)
  self.assertEqual(call(),'SUBMITTED_RECONCILE_ONLY')
  self.assertEqual(posted,[intent_id])
  self.assertEqual(self.refs['lease'].get().to_dict()['recoveryFenceReservation']['state'],'RECOVERY_SUBMITTING_RECONCILE_ONLY')
  self.db=self.firestore.Client(project='amar-short-recovery-offline-test')
  # A consumed claim deterministically wins over the advanced coordination fence.
  self.assertEqual(call(),'BLOCKED_CLAIM_NOT_RESERVED')
  self.assertEqual(posted,[intent_id])
  self.refs['lease'].update({'lease':{'token':'token-1','until':self.now+timedelta(seconds=60)}})
  self.assertEqual(self.reserve(i=77),'BLOCKED_FENCE_ALREADY_RESERVED')
 def test_competing_topup_and_submit_lock_cannot_both_acquire_right(self):
  """Actual Firestore transactions: no topup while an original CLOSE claim is reserved."""
  from short_recovery_order_claim_shadow import reserve,submit_once_offline
  from types import SimpleNamespace
  from threading import Barrier
  marker=self.refs['lease'].parent.document('marker')
  marker.set({'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  self.refs['claim'].delete(); self.refs['lease'].set({})
  cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=2)
  self.assertEqual(reserve(db=self.db,transactional=self.firestore.transactional,
   marker_ref=marker,owner_ref=self.refs['owner'],ledger_ref=self.refs['ledger'],
   claim_ref=self.refs['claim'],control_ref=self.refs['control'],coordination_ref=self.refs['lease'],
   account='u',symbol='XRPUSDT',cycle='c',intent_id=cid,now=1,side='SHORT',action='CLOSE',step=2),'RESERVED_SHADOW')
  intent=SimpleNamespace(intent_id=cid,symbol='XRPUSDT',position_side=SimpleNamespace(value='SHORT'),action='CLOSE')
  posted=[]; barrier=Barrier(2)
  def recovery_submit():
   barrier.wait(timeout=10)
   return submit_once_offline(db=self.db,transactional=self.firestore.transactional,
    claim_ref=self.refs['claim'],control_ref=self.refs['control'],coordination_ref=self.refs['lease'],
    account='u',symbol='XRPUSDT',cycle='c',intent=intent,
    account_close_guard=lambda:None,submit_mock=lambda _:posted.append(cid))
  def hedge_attempt():
   barrier.wait(timeout=10)
   self.refs['lease'].update({'lease':{'token':'token-1','until':self.now+timedelta(seconds=60)}})
   return self.reserve(i=123)
  with ThreadPoolExecutor(max_workers=2) as pool:
   a=pool.submit(recovery_submit);b=pool.submit(hedge_attempt)
   result_a,result_b=a.result(timeout=30),b.result(timeout=30)
  self.assertNotEqual(result_b,'RESERVED_OFFLINE_ONLY',(result_a,result_b))
  self.assertIn(result_a,('SUBMITTED_RECONCILE_ONLY','BLOCKED_COORDINATION_LEASE_UNRESOLVED','BLOCKED_COORDINATION_CLAIM_MISMATCH'))
  self.assertLessEqual(len(posted),1)
