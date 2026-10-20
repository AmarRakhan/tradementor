import unittest
from datetime import datetime,timedelta,timezone
from short_recovery_multidoc_mock import MultiDocDB, Ref, transactional
from short_recovery_lease_fence_offline import check_fence

class Fence(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.refs={key:Ref(self.db,key) for key in ('lease','owner','claim','ledger','control')}
  self.now=datetime(2026,10,18,tzinfo=timezone.utc)
  docs={'lease':{'lease':{'token':'t','until':self.now+timedelta(seconds=45)}},
   'owner':{'account':'u','symbol':'XRPUSDT','cycleId':'c','cycleConfirmed':True,'ownershipVerified':True,'ownerSide':'SHORT','state':'PARTIAL'},
   'claim':{'account':'u','symbol':'XRPUSDT','cycle':'c','side':'SHORT','action':'CLOSE','state':'PARTIAL'},
   'ledger':{'account':'u','symbol':'XRPUSDT'},
   'control':{'account':'u','emergencyStop':False,'closeAllActive':False}}
  for k,v in docs.items():self.db.commit(k,0,v)
 def run_fence(self,**kw):return check_fence(db=self.db,transactional=transactional,**{key+'_ref':ref for key,ref in self.refs.items()},account='u',symbol='XRPUSDT',cycle='c',lease_token=kw.get('token','t'),now=kw.get('now',self.now))
 def update(self,k,**changes):
  v,row=self.db.snapshot(k);self.db.commit(k,v,{**row,**changes})
 def test_partial_blocks_topup(self):self.assertEqual(self.run_fence(),'BLOCKED_RECOVERY_SHORT_TOPUP')
 def test_expired(self):self.assertEqual(self.run_fence(now=self.now+timedelta(seconds=46)),'BLOCKED_LEASE_EXPIRED')
 def test_stale_token(self):self.assertEqual(self.run_fence(token='older'),'BLOCKED_LEASE_STALE')
 def test_unresolved_claim(self):self.update('claim',state='SUBMITTING');self.assertEqual(self.run_fence(),'BLOCKED_RECOVERY_UNRESOLVED')
 def test_unknown_cycle(self):self.update('owner',cycleId='old');self.assertEqual(self.run_fence(),'BLOCKED_RECOVERY_UNKNOWN')
 def test_emergency_stop(self):self.update('control',emergencyStop=True);self.assertEqual(self.run_fence(),'BLOCKED_CONTROL')
 def test_concurrent_reads(self):
  from concurrent.futures import ThreadPoolExecutor
  with ThreadPoolExecutor(max_workers=8) as ex:self.assertEqual(list(ex.map(lambda _:self.run_fence(),range(24))),['BLOCKED_RECOVERY_SHORT_TOPUP']*24)

class LeaseFence(Fence):
 def setUp(self):
  super().setUp()
  from short_recovery_order_claim_shadow import canonical_intent_id
  key="claim";version,doc=self.db.snapshot(key)
  self.db.commit(key,version,{**doc,"step":1,"intentId":canonical_intent_id(account="u",symbol="XRPUSDT",cycle="c",side="SHORT",action="CLOSE",step=1),"executedQty":"25"})
  version,doc=self.db.snapshot("control");self.db.commit("control",version,{**doc,"enabled":True})
  from short_recovery_firestore_mock import encode
  from short_recovery_ledger import Ledger, Allocation
  from decimal import Decimal
  version,_=self.db.snapshot("ledger");self.db.commit("ledger",version,encode(Ledger("u","XRPUSDT",(Allocation("z","c",Decimal(75)),))))

class RehedgeReservation(unittest.TestCase):
 def test_rehedge_requires_final_readback_fresh_cycle_and_single_right(self):
  from short_recovery_lease_fence_offline import reserve_rehedge_mock_only
  f=LeaseFence();f.setUp()
  v,c=f.db.snapshot('claim');f.db.commit('claim',v,{**c,'state':'CLOSED','orderId':'mock-close-order'})
  def reserve(**changes):
   args=dict(mock_only=True,db=f.db,transactional=transactional,
    coordination_ref=f.refs['lease'],owner_ref=f.refs['owner'],final_claim_ref=f.refs['claim'],
    control_ref=f.refs['control'],account='u',symbol='XRPUSDT',old_cycle='c',
    new_cycle='c2',lease_token='t',intent_id=__import__('short_recovery_order_claim_shadow').canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c2',side='SHORT',action='OPEN',step=0),now=f.now,
    final_readback_verified=True)
   return reserve_rehedge_mock_only(**{**args,**changes})
  self.assertEqual(reserve(final_readback_verified=False),'BLOCKED_REHEDGE_FINAL_READBACK')
  self.assertEqual(reserve(new_cycle='c'),'BLOCKED_REHEDGE_CYCLE_REUSE')
  self.assertEqual(reserve(require_financial_finality=True),'BLOCKED_FINANCIAL_FINALITY_UNVERIFIED')
  self.assertEqual(reserve(),'RESERVED_REHEDGE_MOCK_ONLY')
  self.assertEqual(reserve(),'BLOCKED_FENCE_ALREADY_RESERVED')
  self.assertEqual(f.db.snapshot('lease')[1]['recoveryFenceReservation']['state'],'REHEDGE_MOCK_SUBMITTING')


class StrictFinancialRehedgeProof(unittest.TestCase):
 def test_full_evidence_required_not_a_caller_boolean(self):
  from short_recovery_lease_fence_offline import verified_financial_finality_offline as proof
  ready=dict(financialVerified=True,terminalVerified=True,fillsComplete=True,
   incomeHistoryComplete=True,financialSettlement='RECONCILED',
   executedQty='25',executionFinancials={'trade-1':['25','1','0.1','0']})
  self.assertTrue(proof(ready))
  for key,value in (('financialSettlement','UNRECONCILED'),('financialVerified',False),
                    ('incomeHistoryComplete',False),('executionFinancials',{}),
                    ('executionFinancials',{'trade-1':['25','1','0.1']}),
                    ('executionFinancials',{'trade-1':['25','1','0.1','NaN']}),
                    ('executedQty','24')):
   with self.subTest(field=key):
    self.assertFalse(proof({**ready,key:value}))
