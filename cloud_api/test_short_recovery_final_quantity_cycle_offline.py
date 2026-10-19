import unittest
from short_recovery_multidoc_mock import MultiDocDB, Ref, transactional
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_standalone_offline import RECOVERY
from short_recovery_final_quantity_cycle_offline import finalize_short_quantity_cycle_offline as finish

class Client:
 offline_mock_only=True
 def __init__(self):self.short='0';self.orders=[];self.drift=False;self.calls=0
 def account_information(self):return {'account':'u','hedgeMode':True}
 def position_risk(self,s):
  self.calls+=1
  short='1' if self.drift and self.calls>1 else self.short
  return [{'symbol':s,'positionSide':'LONG','positionAmt':'100'},
          {'symbol':s,'positionSide':'SHORT','positionAmt':short}]
 def open_orders(self,s):return self.orders
 def query_order(self,s,c):return {'symbol':s,'clientOrderId':c,'orderId':'close-final','status':'FILLED','executedQty':'25'}
 def user_trades(self,s,**kw):return [{'id':4,'symbol':s,'orderId':'close-final','qty':'25','realizedPnl':'1','commission':'.1'}]

class FinalQuantity(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB()
  self.refs={key:Ref(self.db,key) for key in ('selector','position','claim','coord','control')}
  self.cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=4)
  self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  self.put('position',{'account':'u','symbol':'XRPUSDT','cycle':'c',
    'offlineOnly':True,'pending':True,'state':'ADOPTED_OFFLINE',
    'originalShortQty':'100','confirmedClosed':'100','steps':4})
  self.put('claim',{'account':'u','symbol':'XRPUSDT','cycle':'c',
    'intentId':self.cid,'side':'SHORT','action':'CLOSE','step':4,
    'state':'SUBMITTING','orderId':'close-final','offlineTerminalQty':'25',
    'offlineOrderTerminalVerified':True,'offlineFundingStatus':'UNRECONCILED',
    'offlineFinancialSettlement':'PENDING','offlineNextClaimAuthorized':False,
    'offlineTerminalExecutions':[['4','25','1','0.1']]})
  self.put('coord',{'recoveryFenceReservation':{'account':'u',
    'symbol':'XRPUSDT','cycle':'c','intentId':self.cid,
    'state':'RECOVERY_SUBMITTING_RECONCILE_ONLY'}})
  self.put('control',{'account':'u','enabled':True,
    'emergencyStop':False,'closeAllActive':False})
  self.client=Client()
 def put(self,k,value):
  v,_=self.db.snapshot(k);self.db.commit(k,v,value)
 def finalize(self):
  return finish(mock_only=True,db=self.db,transactional=transactional,
   client=self.client,selector_ref=self.refs['selector'],
   position_ref=self.refs['position'],claim_ref=self.refs['claim'],
   coordination_ref=self.refs['coord'],control_ref=self.refs['control'],
   account='u',symbol='XRPUSDT',cycle='c',step=4,long_qty='100')
 def test_terminal_quantity_preserves_fence_and_funding_block(self):
  self.assertEqual(self.finalize(),'QUANTITY_CYCLE_TERMINAL_UNSETTLED_FENCE_LOCKED')
  claim=self.db.snapshot('claim')[1]
  self.assertEqual(claim['state'],'CLOSED')
  self.assertFalse(claim['financialVerified'])
  self.assertEqual(claim['financialSettlement'],'UNRECONCILED')
  self.assertFalse(claim['offlineNextClaimAuthorized'])
  self.assertIsNotNone(self.db.snapshot('coord')[1]['recoveryFenceReservation'])
  self.assertEqual(self.db.snapshot('position')[1]['state'],'FINAL_SHORT_FILLED_OFFLINE')
  self.assertEqual(self.finalize(),'BLOCKED_POSITION')
 def test_no_residual_short_or_unknown_open_orders(self):
  self.client.short='1'
  self.assertEqual(self.finalize(),'BLOCKED_FINAL_INVENTORY')
  self.client.short='0';self.client.orders=[{'id':'pending'}]
  self.assertEqual(self.finalize(),'BLOCKED_FINAL_INVENTORY')
 def test_inventory_drift_fail_closed(self):
  self.client.drift=True
  self.assertEqual(self.finalize(),'BLOCKED_FINAL_INVENTORY')
 def test_stop_and_wrong_strategy_fail_closed(self):
  self.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  self.assertEqual(self.finalize(),'BLOCKED_STOP')
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  self.put('selector',{'account':'u','activeStrategy':'ASTER_CLASSIC','offlineOnly':True})
  self.assertEqual(self.finalize(),'BLOCKED_STRATEGY')
 def test_concurrency_and_restart_no_double_completion(self):
  from concurrent.futures import ThreadPoolExecutor
  with ThreadPoolExecutor(max_workers=2) as pool:
   results=list(pool.map(lambda _:self.finalize(),range(2)))
  self.assertEqual(results.count('QUANTITY_CYCLE_TERMINAL_UNSETTLED_FENCE_LOCKED'),1)
  self.assertEqual(results.count('BLOCKED_CONCURRENT_CHANGE')+results.count('BLOCKED_POSITION'),1)
  self.db=self.db.restart();self.refs={k:Ref(self.db,k) for k in self.refs}
  self.assertEqual(self.finalize(),'BLOCKED_POSITION')
if __name__=='__main__':unittest.main()
