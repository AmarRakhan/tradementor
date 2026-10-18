import unittest
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_cycle_contract_offline import advance
class OfflineCycleContract(unittest.TestCase):
 def test_four_atomic_reductions_partial_restart_and_single_new_cycle(self):
  db=MultiDocDB();root=('u','XRPUSDT');cycle_key=root+('cycle','c');next_key=root+('cycle','c2')
  db.commit(cycle_key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','anchor':'2','initialQty':'100','confirmedSteps':0,'state':'ACTIVE'})
  keys=[root+('claim',i) for i in range(1,6)]
  for i,k in enumerate(keys,1):
   db.commit(k,0,{'account':'u','symbol':'XRPUSDT','cycle':'c','side':'SHORT','action':'CLOSE' if i<5 else 'OPEN','step':i,'state':'RESERVED','intentId':f'canonical-{i}','orderId':f'order-{i}','executedQty':'0'})
  def call(event,step=0):
   return advance(db=db,transactional=transactional,cycle_ref=Ref(db,cycle_key),claim_refs=[Ref(db,k) for k in keys],next_ref=Ref(db,next_key),event=event,step=step,next_cycle='c2',next_anchor='1.62')
  for i in range(1,5):
   version,row=db.snapshot(keys[i-1]);db.commit(keys[i-1],version,{**row,'state':'PARTIAL','executedQty':'10'})
   self.assertEqual(call('CONFIRM_REDUCTION',i),'BLOCKED_UNCONFIRMED_REDUCTION')
   self.assertEqual(call('CONFIRM_REHEDGE'),'BLOCKED_REHEDGE_NOT_FINAL')
   db=db.restart()
   version,row=db.snapshot(keys[i-1]);db.commit(keys[i-1],version,{**row,'state':'CLOSED','executedQty':'25'})
   self.assertEqual(call('CONFIRM_REDUCTION',i),'REDUCTION_CONFIRMED')
   self.assertEqual(call('CONFIRM_REDUCTION',i),'BLOCKED_STEP_SEQUENCE')
   self.assertEqual(db.snapshot(cycle_key)[1]['anchor'],'2')
  self.assertEqual(call('CONFIRM_REHEDGE'),'BLOCKED_REHEDGE_NOT_FINAL')
  version,row=db.snapshot(keys[4]);db.commit(keys[4],version,{**row,'state':'CLOSED','executedQty':'100'})
  self.assertEqual(call('CONFIRM_REHEDGE'),'NEW_CYCLE_ATOMICALLY_CREATED')
  self.assertEqual(call('CONFIRM_REHEDGE'),'BLOCKED_REHEDGE_NOT_FINAL')
  self.assertEqual(db.snapshot(cycle_key)[1]['anchor'],'2')
  self.assertEqual(db.snapshot(next_key)[1]['anchor'],'1.62')
  self.assertEqual(db.snapshot(next_key)[1]['cycleId'],'c2')

class CycleCommitTOCTOU(unittest.TestCase):
 def test_stale_validated_claim_and_stop_cannot_create_next_cycle(self):
  from short_recovery_cycle_contract_offline import advance
  db=MultiDocDB();root=('u','XRPUSDT');ck=root+('cycle','c');nk=root+('cycle','c2');control=root+('control',)
  original={'account':'u','symbol':'XRPUSDT','cycleId':'c','anchor':'2','initialQty':'100','confirmedSteps':4,'state':'ACTIVE'}
  db.commit(ck,0,original)
  db.commit(control,0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  keys=[root+('claim',i) for i in range(1,6)]
  for i,k in enumerate(keys,1):db.commit(k,0,{'account':'u','symbol':'XRPUSDT','cycle':'c','side':'SHORT','action':'OPEN' if i==5 else 'CLOSE','step':i,'state':'CLOSED','intentId':f'cid-{i}','orderId':f'oid-{i}','executedQty':'100' if i==5 else '25'})
  evidence=[db.snapshot(k)[1] for k in keys]
  def commit():return advance(db=db,transactional=transactional,cycle_ref=Ref(db,ck),claim_refs=[Ref(db,k) for k in keys],next_ref=Ref(db,nk),control_ref=Ref(db,control),event='CONFIRM_REHEDGE',next_cycle='c2',next_anchor='1.66',validated_cycle=original,validated_claims=evidence)
  version,row=db.snapshot(keys[4]);db.commit(keys[4],version,{**row,'state':'UNKNOWN'})
  self.assertEqual(commit(),'BLOCKED_READBACK_TOCTOU')
  self.assertIsNone(db.snapshot(nk)[1])
  version,row=db.snapshot(keys[4]);db.commit(keys[4],version,evidence[4])
  version,row=db.snapshot(control);db.commit(control,version,{**row,'emergencyStop':True})
  self.assertEqual(commit(),'BLOCKED_CYCLE_EMERGENCY_STOP')
  self.assertIsNone(db.snapshot(nk)[1])
  version,row=db.snapshot(control);db.commit(control,version,{**row,'emergencyStop':False})
  self.assertEqual(commit(),'NEW_CYCLE_ATOMICALLY_CREATED')
  self.assertEqual(commit(),'BLOCKED_READBACK_TOCTOU')
