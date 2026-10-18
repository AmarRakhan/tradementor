import unittest
from datetime import datetime, timezone, timedelta
from short_recovery_multidoc_mock import MultiDocDB, Ref, transactional
from short_recovery_firestore_mock import encode
from short_recovery_ledger import Ledger, Allocation
from short_recovery_order_claim_shadow import reserve, canonical_intent_id
from decimal import Decimal
class SharedFence(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.refs={k:Ref(self.db,k) for k in ('marker','owner','ledger','claim','control','coordination')}
  docs={'marker':{'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'},'owner':{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'},'ledger':encode(Ledger('u','XRPUSDT',(Allocation('z','c',Decimal(100)),))),'control':{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False},'coordination':{}}
  for k,v in docs.items():self.db.commit(k,0,v)
 def go(self, coordination=True):
  return reserve(db=self.db,transactional=transactional,**{k+'_ref':v for k,v in self.refs.items() if k!='coordination'},account='u',symbol='XRPUSDT',cycle='c',intent_id=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1),now=1,side='SHORT',action='CLOSE',step=1,coordination_ref=self.refs['coordination'] if coordination else None)
 def test_unreserved_claim_accepted_offline(self):self.assertEqual(self.go(),'RESERVED_SHADOW')
 def test_fence_reserved_blocks_reduction(self):
  ver,coord=self.db.snapshot('coordination');self.db.commit('coordination',ver,{'recoveryFenceReservation':{'state':'OFFLINE_ONLY'}})
  self.assertEqual(self.go(),'BLOCKED_ACCOUNT_FENCE_RESERVED')
  self.assertIsNone(self.db.snapshot('claim')[1])
 def test_missing_coordination_blocks(self):
  v,_=self.db.snapshot('coordination');self.db.commit('coordination',v,None)
  self.assertEqual(self.go(),'BLOCKED_ACCOUNT_FENCE_RESERVED')
  self.assertIsNone(self.db.snapshot('claim')[1])
 def test_legacy_optional_contract_unchanged(self):
  self.assertEqual(self.go(coordination=False),'RESERVED_SHADOW')
 def test_active_account_lease_blocks_recovery_claim(self):
  v,_=self.db.snapshot('coordination')
  self.db.commit('coordination',v,{'lease':{'token':'hedge-active','until':datetime.now(timezone.utc)+timedelta(seconds=45)}})
  self.assertEqual(self.go(),'BLOCKED_ACCOUNT_COORDINATION_BUSY')
  self.assertIsNone(self.db.snapshot('claim')[1])

 def test_expired_lease_remains_reconcile_only(self):
  v,_=self.db.snapshot('coordination');self.db.commit('coordination',v,{'lease':{'token':'stale','until':datetime.now(timezone.utc)-timedelta(seconds=1)}})
  self.assertEqual(self.go(),'BLOCKED_ACCOUNT_LEASE_STALE_RECONCILE')
 def test_unverified_lease_expiry_denied(self):
  v,_=self.db.snapshot('coordination');self.db.commit('coordination',v,{'lease':{'token':'bad','until':'unknown'}})
  self.assertEqual(self.go(),'BLOCKED_ACCOUNT_LEASE_UNVERIFIED')
 def test_preflight_requires_matching_shared_claim_fence(self):
  from short_recovery_order_claim_shadow import pre_submit_check
  intent=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
  self.assertEqual(self.go(),'RESERVED_SHADOW')
  def preflight():
   return pre_submit_check(db=self.db,transactional=transactional,claim_ref=self.refs['claim'],control_ref=self.refs['control'],coordination_ref=self.refs['coordination'],account='u',symbol='XRPUSDT',cycle='c',intent_id=intent,account_close_guard=lambda:None)
  self.assertEqual(preflight(),'PREFLIGHT_SHADOW_ONLY')
  version,doc=self.db.snapshot('coordination')
  doc['recoveryFenceReservation']['intentId']='conflicting-intent'
  self.db.commit('coordination',version,doc)
  self.assertEqual(preflight(),'BLOCKED_COORDINATION_CLAIM_MISMATCH')
 def test_preflight_blocks_lease_after_claim(self):
  from short_recovery_order_claim_shadow import pre_submit_check
  intent=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
  self.assertEqual(self.go(),'RESERVED_SHADOW')
  version,doc=self.db.snapshot('coordination')
  doc['lease']={'token':'other-scan','until':datetime.now(timezone.utc)+timedelta(seconds=30)}
  self.db.commit('coordination',version,doc)
  self.assertEqual(pre_submit_check(db=self.db,transactional=transactional,claim_ref=self.refs['claim'],control_ref=self.refs['control'],coordination_ref=self.refs['coordination'],account='u',symbol='XRPUSDT',cycle='c',intent_id=intent,account_close_guard=lambda:None),'BLOCKED_COORDINATION_LEASE_UNRESOLVED')
 def test_strict_submit_cannot_bypass_missing_coordination(self):
  from short_recovery_order_claim_shadow import submit_once_offline
  from types import SimpleNamespace
  from short_recovery_multidoc_mock import transactional
  from unittest.mock import Mock
  intent_id=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
  self.assertEqual(self.go(coordination=False),'RESERVED_SHADOW')
  intent=SimpleNamespace(intent_id=intent_id,symbol='XRPUSDT',action='CLOSE',position_side=SimpleNamespace(value='SHORT'))
  transport=Mock()
  result=submit_once_offline(db=self.db,transactional=transactional,
    claim_ref=self.refs['claim'],control_ref=self.refs['control'],
    account='u',symbol='XRPUSDT',cycle='c',intent=intent,
    account_close_guard=lambda:None,submit_mock=transport,require_shared_fence=True)
  self.assertEqual(result,'BLOCKED_SHARED_FENCE_REQUIRED')
  self.assertEqual(self.db.snapshot('claim')[1]['state'],'RESERVED')
  transport.assert_not_called()
