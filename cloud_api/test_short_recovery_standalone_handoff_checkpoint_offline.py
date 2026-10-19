import unittest
from concurrent.futures import ThreadPoolExecutor
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_order_claim_shadow import canonical_intent_id,pre_submit_check
from short_recovery_standalone_offline import RECOVERY,CLASSIC
from short_recovery_standalone_handoff_checkpoint_offline import stage_next_short_step_offline as stage


class Checkpoint(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB()
  self.refs={k:Ref(self.db,k) for k in ('selector','position','previous','next','coord','control')}
  self.step=2
  self.configure(4)
 def put(self,key,value):
  v,_=self.db.snapshot(key);self.db.commit(key,v,value)
 def configure(self,steps,prior_step=1):
  self.step=prior_step+1
  old=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=prior_step)
  self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  self.put('position',{'account':'u','symbol':'XRPUSDT','cycle':'c','offlineOnly':True,
    'steps':steps,'originalShortQty':'100','confirmedClosed':str(100*prior_step//steps)})
  self.put('previous',{'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':old,
    'side':'SHORT','action':'CLOSE','step':prior_step,'orderId':'o-'+str(prior_step),
    'offlineOrderTerminalVerified':True,'offlineFundingStatus':'UNRECONCILED',
    'offlineFinancialSettlement':'PENDING','offlineNextClaimAuthorized':False,
    'offlineTerminalQty':str(100//steps),
    'offlineTerminalExecutions':[['execution-'+str(prior_step),str(100//steps),'1','.1']]})
  self.put('coord',{'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT',
     'cycle':'c','intentId':old,'state':'RECOVERY_SUBMITTING_RECONCILE_ONLY'}})
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  self.put('next',None)
 def stage(self,**updates):
  k=dict(db=self.db,transactional=transactional,
    selector_ref=self.refs['selector'],position_ref=self.refs['position'],
    prior_claim_ref=self.refs['previous'],next_claim_ref=self.refs['next'],
    coordination_ref=self.refs['coord'],control_ref=self.refs['control'],
    account='u',symbol='XRPUSDT',cycle='c',next_step=self.step)
  k.update(updates);return stage(**k)
 def test_four_step_checkpoint_never_reserves_or_moves_fence(self):
  for prior in (1,2,3):
   self.configure(4,prior)
   self.assertEqual(self.stage(),'STAGED_WAITING_NO_SUBMIT_RIGHT')
   nxt=self.db.snapshot('next')[1]
   self.assertEqual(nxt['state'],'WAIT_FINANCIAL_AUTHORIZATION')
   self.assertFalse(nxt['nextClaimAuthorized'])
   self.assertEqual(self.db.snapshot('coord')[1]['recoveryFenceReservation']['intentId'],
     self.db.snapshot('previous')[1]['intentId'])
   self.assertEqual(self.stage(),'ALREADY_STAGED_NO_SUBMIT_RIGHT')
 def test_ten_step_checkpoint(self):
  for prior in (1,5,9):
   self.configure(10,prior)
   self.assertEqual(self.stage(),'STAGED_WAITING_NO_SUBMIT_RIGHT')
 def test_claim_cannot_pass_existing_pre_submit_gate(self):
  self.assertEqual(self.stage(),'STAGED_WAITING_NO_SUBMIT_RIGHT')
  cid=self.db.snapshot('next')[1]['intentId']
  r=pre_submit_check(db=self.db,transactional=transactional,claim_ref=self.refs['next'],
   control_ref=self.refs['control'],coordination_ref=self.refs['coord'],
   account='u',symbol='XRPUSDT',cycle='c',intent_id=cid,account_close_guard=lambda:None)
  self.assertEqual(r,'BLOCKED_CLAIM_NOT_RESERVED')
 def test_concurrent_and_restart_are_idempotent(self):
  with ThreadPoolExecutor(max_workers=2) as pool:
   results=list(pool.map(lambda _:self.stage(),(1,2)))
  self.assertEqual(results.count('STAGED_WAITING_NO_SUBMIT_RIGHT'),1)
  self.assertEqual(results.count('ALREADY_STAGED_NO_SUBMIT_RIGHT'),1)
  self.db=self.db.restart()
  self.refs={k:Ref(self.db,k) for k in self.refs}
  self.assertEqual(self.stage(),'ALREADY_STAGED_NO_SUBMIT_RIGHT')
 def test_stop_classic_unknown_stale_lease_and_overlap_block(self):
  self.put('selector',{'account':'u','activeStrategy':CLASSIC,'offlineOnly':True})
  self.assertEqual(self.stage(),'BLOCKED_STRATEGY')
  self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  self.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  self.assertEqual(self.stage(),'BLOCKED_STOP')
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  self.put('coord',{**self.db.snapshot('coord')[1],'lease':{'token':'stale'}})
  self.assertEqual(self.stage(),'BLOCKED_COORDINATION')
  self.put('coord',{'recoveryFenceReservation':{'intentId':'wrong'}})
  self.assertEqual(self.stage(),'BLOCKED_COORDINATION')
  self.configure(4)
  self.put('next',{'state':'SUBMITTING','cycle':'other'})
  self.assertEqual(self.stage(),'BLOCKED_NEXT_CLAIM_EXISTS')
 def test_partial_and_unverified_execution_block(self):
  self.put('previous',{**self.db.snapshot('previous')[1],
    'offlineOrderTerminalVerified':False})
  self.assertEqual(self.stage(),'BLOCKED_PRIOR_EXECUTION')
  self.configure(4)
  self.put('position',{**self.db.snapshot('position')[1],'confirmedClosed':'10'})
  self.assertEqual(self.stage(),'BLOCKED_CUMULATIVE_QUANTITY')
  self.configure(4)
  self.put('previous',{**self.db.snapshot('previous')[1],'offlineTerminalQty':'10'})
  self.assertEqual(self.stage(),'BLOCKED_CUMULATIVE_QUANTITY')
 def test_cycle_isolation_and_final_step_not_allowed(self):
  self.assertEqual(self.stage(cycle='c2'),'BLOCKED_POSITION')
  self.assertEqual(self.stage(next_step=5),'BLOCKED_STEP')


if __name__=='__main__':unittest.main()
