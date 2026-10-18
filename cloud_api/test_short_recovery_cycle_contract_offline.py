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
