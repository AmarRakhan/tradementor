import unittest
from concurrent.futures import ThreadPoolExecutor
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_standalone_offline import RECOVERY
from short_recovery_rehedge_fill_activation_offline import activate_verified_rehedge_offline as activate

class Client:
 offline_mock_only=True
 def __init__(self,cid):self.cid=cid;self.short='100';self.status='FILLED';self.price='2.5';self.orders=[]
 def query_order(self,s,c):return {'symbol':s,'clientOrderId':c,'orderId':'open-2','status':self.status,'executedQty':'100'}
 def user_trades(self,s,**kw):return [{'symbol':s,'orderId':'open-2','id':99,'qty':'100','price':self.price}]
 def account_information(self):return {'account':'u','hedgeMode':True}
 def position_risk(self,s):return [{'symbol':s,'positionSide':'LONG','positionAmt':'100'},{'symbol':s,'positionSide':'SHORT','positionAmt':self.short}]
 def open_orders(self,s):return self.orders

class Activation(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.r={k:Ref(self.db,k) for k in ('selector','position','claim','coord','control')}
  self.cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c2',side='SHORT',action='OPEN',step=0)
  self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  self.put('position',{'account':'u','symbol':'XRPUSDT','cycle':'c','offlineOnly':True,'state':'FINAL_SHORT_FILLED_OFFLINE','financialSettlement':'UNRECONCILED'})
  self.put('claim',{'account':'u','symbol':'XRPUSDT','cycle':'c2','intentId':self.cid,'side':'SHORT','action':'OPEN','step':0,'state':'SUBMITTING','orderId':'open-2'})
  self.put('coord',{'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT','cycle':'c2','previousCycle':'c','intentId':self.cid,'state':'REHEDGE_SUBMITTING_RECONCILE_ONLY'}})
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  self.client=Client(self.cid)
 def put(self,k,v):
  version,_=self.db.snapshot(k);self.db.commit(k,version,v)
 def call(self):
  return activate(db=self.db,transactional=transactional,client=self.client,
    selector_ref=self.r['selector'],position_ref=self.r['position'],open_claim_ref=self.r['claim'],
    coordination_ref=self.r['coord'],control_ref=self.r['control'],
    account='u',symbol='XRPUSDT',old_cycle='c',new_cycle='c2',steps=4,step_pct='5')
 def test_new_anchor_and_locked_fence(self):
  self.assertEqual(self.call(),'NEW_CYCLE_FILL_VERIFIED_FENCE_LOCKED')
  p=self.db.snapshot('position')[1];self.assertEqual(p['anchor'],'2.5')
  self.assertEqual(p['cycle'],'c2');self.assertEqual(p['originalShortQty'],'100')
  self.assertEqual(p['confirmedClosed'],'0');self.assertEqual(p['financialSettlement'],'UNRECONCILED')
  self.assertEqual(self.db.snapshot('claim')[1]['state'],'FILLED_QUANTITY_OFFLINE')
  self.assertEqual(self.db.snapshot('coord')[1]['recoveryFenceReservation']['state'],'REHEDGE_SUBMITTING_RECONCILE_ONLY')
  self.assertEqual(self.call(),'BLOCKED_OPEN_CLAIM')
 def test_new_anchor_is_weighted_by_independent_fill_quantities(self):
  self.client.user_trades=lambda s,**kw:[
   {'symbol':s,'orderId':'open-2','id':99,'qty':'40','price':'2'},
   {'symbol':s,'orderId':'open-2','id':100,'qty':'60','price':'3'}]
  self.assertEqual(self.call(),'NEW_CYCLE_FILL_VERIFIED_FENCE_LOCKED')
  self.assertEqual(self.db.snapshot('position')[1]['anchor'],'2.6')
  self.assertEqual(self.db.snapshot('claim')[1]['executedQty'],'100')
 def test_incomplete_or_duplicate_fills_never_activate_cycle(self):
  self.client.user_trades=lambda s,**kw:[
   {'symbol':s,'orderId':'open-2','id':99,'qty':'50','price':'2.5'}]
  self.assertEqual(self.call(),'BLOCKED_INDEPENDENT_REHEDGE_FILL')
  self.assertEqual(self.db.snapshot('position')[1]['cycle'],'c')
  self.client.user_trades=lambda s,**kw:[
   {'symbol':s,'orderId':'open-2','id':99,'qty':'50','price':'2.5'},
   {'symbol':s,'orderId':'open-2','id':99,'qty':'50','price':'2.5'}]
  self.assertEqual(self.call(),'BLOCKED_INDEPENDENT_REHEDGE_FILL')
  self.assertEqual(self.db.snapshot('position')[1]['cycle'],'c')
 def test_partial_unknown_dust_and_open_orders(self):
  self.client.status='PARTIALLY_FILLED';self.assertEqual(self.call(),'BLOCKED_INDEPENDENT_REHEDGE_FILL')
  self.client.status='FILLED';self.client.short='99';self.assertEqual(self.call(),'BLOCKED_INDEPENDENT_REHEDGE_FILL')
  self.client.short='100';self.client.orders=[{'id':'pending'}]
  self.assertEqual(self.call(),'BLOCKED_INDEPENDENT_REHEDGE_FILL')
 def test_stop_or_strategy(self):
  self.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  self.assertEqual(self.call(),'BLOCKED_STOP')
 def test_two_workers_restart_one_activation(self):
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.call(),range(2)))
  self.assertEqual(results.count('NEW_CYCLE_FILL_VERIFIED_FENCE_LOCKED'),1)
  self.assertEqual(len(results),2)
  self.db=self.db.restart();self.r={k:Ref(self.db,k) for k in self.r}
  self.assertEqual(self.call(),'BLOCKED_OPEN_CLAIM')
if __name__=='__main__':unittest.main()
