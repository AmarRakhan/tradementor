"""The existing strict offline transport performs the selector read in its CAS."""
import unittest
from decimal import Decimal
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_order_claim_shadow import canonical_intent_id, submit_once_offline
from short_recovery_standalone_offline import RECOVERY,CLASSIC
from aster_gateway import AsterOrderIntent,PositionSide

class StandaloneSubmitCAS(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.refs={k:Ref(self.db,k) for k in ('selector','claim','control','coord')}
  self.id=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
  self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  self.put('claim',{'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':self.id,'side':'SHORT','action':'CLOSE','step':1,'state':'RESERVED'})
  self.put('coord',{'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':self.id,'state':'RECOVERY_CLAIM_RESERVED'}})
  self.sent=[]
 def put(self,key,row):
  ver,_=self.db.snapshot(key);self.db.commit(key,ver,row)
 def submit(self,transport=None):
  intent=AsterOrderIntent(self.id,'XRPUSDT',PositionSide.SHORT,Decimal(25),'CLOSE')
  return submit_once_offline(db=self.db,transactional=transactional,
   claim_ref=self.refs['claim'],control_ref=self.refs['control'],
   coordination_ref=self.refs['coord'],require_shared_fence=True,
   standalone_selector_ref=self.refs['selector'],account='u',symbol='XRPUSDT',cycle='c',
   intent=intent,account_close_guard=lambda:None,
   submit_mock=transport or (lambda i:self.sent.append(i.intent_id)))
 def test_valid_one_submit_replay_never_resends(self):
  self.assertEqual(self.submit(),'SUBMITTED_RECONCILE_ONLY')
  self.assertEqual(self.submit(),'BLOCKED_CLAIM_NOT_RESERVED')
  self.assertEqual(self.sent,[self.id])
 def test_switch_to_classic_before_submit_blocks(self):
  self.put('selector',{'account':'u','activeStrategy':CLASSIC,'offlineOnly':True})
  self.assertEqual(self.submit(),'BLOCKED_STRATEGY_NOT_ACTIVE')
  self.assertEqual(self.db.snapshot('claim')[1]['state'],'RESERVED')
  self.assertFalse(self.sent)
 def test_missing_selector_fail_closed(self):
  self.put('selector',None)
  self.assertEqual(self.submit(),'BLOCKED_STRATEGY_NOT_ACTIVE')
  self.assertFalse(self.sent)
 def test_stop_and_closeall(self):
  for field in ('emergencyStop','closeAllActive'):
   self.put('control',{'account':'u','enabled':True,'emergencyStop':field=='emergencyStop','closeAllActive':field=='closeAllActive'})
   self.assertEqual(self.submit(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
   self.assertFalse(self.sent)
 def test_transport_unknown_remains_locked_after_restart(self):
  def timeout(i):raise TimeoutError('offline transport uncertainty')
  self.assertEqual(self.submit(transport=timeout),'UNKNOWN_RECONCILE_ONLY')
  self.db=self.db.restart();self.refs={k:Ref(self.db,k) for k in self.refs}
  self.assertEqual(self.submit(),'BLOCKED_CLAIM_NOT_RESERVED')
  self.assertFalse(self.sent)
 def test_concurrent_submission_exactly_once(self):
  from concurrent.futures import ThreadPoolExecutor
  with ThreadPoolExecutor(max_workers=2) as pool:
   outputs=list(pool.map(lambda _:self.submit(),range(2)))
  self.assertEqual(outputs.count('SUBMITTED_RECONCILE_ONLY'),1)
  self.assertEqual(len(self.sent),1)
 def test_claim_unknown_partial_and_stale_fence(self):
  for state in ('UNKNOWN','PARTIAL','SUBMITTING'):
   self.put('claim',{**self.db.snapshot('claim')[1],'state':state})
   self.assertEqual(self.submit(),'BLOCKED_CLAIM_NOT_RESERVED')
  self.put('claim',{**self.db.snapshot('claim')[1],'state':'RESERVED'})
  self.put('coord',{'recoveryFenceReservation':{'intentId':'stale'}})
  self.assertEqual(self.submit(),'BLOCKED_COORDINATION_CLAIM_MISMATCH')
if __name__=='__main__':unittest.main()
