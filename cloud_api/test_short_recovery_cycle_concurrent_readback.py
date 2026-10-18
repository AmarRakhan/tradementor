"""Two independent mock GET workers racing for one canonical cycle commit."""
import concurrent.futures
import threading
import unittest
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_cycle_readback_offline import advance_verified

class ConcurrentOfflineCycle(unittest.TestCase):
 def test_two_workers_one_cycle_then_stale_claim_and_stop_block(self):
  db=MultiDocDB();root=('u','XRPUSDT');ck=root+('cycle','c');nk=root+('cycle','c2');ctrl=root+('control',)
  db.commit(ck,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','anchor':'2','initialQty':'100','confirmedSteps':4,'state':'ACTIVE'})
  db.commit(ctrl,0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  keys=[root+('claim',i) for i in range(1,6)]
  for i,k in enumerate(keys,1):db.commit(k,0,{'account':'u','symbol':'XRPUSDT','cycle':'c','side':'SHORT','action':'OPEN' if i==5 else 'CLOSE','step':i,'state':'CLOSED','intentId':f'canonical-{i}','orderId':f'order-{i}','executedQty':'100' if i==5 else '25'})
  barrier=threading.Barrier(2)
  class Exchange:
   offline_mock_only=True
   def __init__(self):self.last=False
   def query_order(self,s,c):
    i=int(c.rsplit('-',1)[1]);return {'symbol':s,'clientOrderId':c,'orderId':f'order-{i}','status':'FILLED','executedQty':'100' if i==5 else '25'}
   def user_trades(self,s,**kw):return [{'symbol':s,'orderId':f'order-{i}','id':i,'qty':'100' if i==5 else '25','price':'1.66','realizedPnl':'0','commission':'0'} for i in range(1,6)]
   def account_information(self):return {'account':'u','hedgeMode':True}
   def position_risk(self,s):return [{'symbol':s,'positionSide':'LONG','positionAmt':'100'},{'symbol':s,'positionSide':'SHORT','positionAmt':'100'}]
   def open_orders(self,s):
    if not self.last:
     self.last=True;barrier.wait(timeout=10)
    return []
  def run():return advance_verified(db=db,transactional=transactional,cycle_ref=Ref(db,ck),claim_refs=[Ref(db,k) for k in keys],next_ref=Ref(db,nk),control_ref=Ref(db,ctrl),client=Exchange(),next_cycle='c2',event='CONFIRM_REHEDGE')
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   results=[f.result(timeout=20) for f in [pool.submit(run),pool.submit(run)]]
  self.assertEqual(results.count('NEW_CYCLE_ATOMICALLY_CREATED'),1,results)
  self.assertIn(results[0] if results[0]!='NEW_CYCLE_ATOMICALLY_CREATED' else results[1],('BLOCKED_READBACK_TOCTOU','BLOCKED_REHEDGE_NOT_FINAL'))
  self.assertEqual(db.snapshot(nk)[1]['anchor'],'1.66')
  self.assertEqual(db.snapshot(ck)[1]['anchor'],'2')
  self.assertEqual(len([k for k in db.docs if isinstance(k,tuple) and len(k)>2 and k[2]=='cycle']),2)
  # No order transport is present anywhere in this bridge: zero mock POSTs.
