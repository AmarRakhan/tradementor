"""Combined offline final SHORT -> canonical rehedge submit -> confirmed anchor.

Uses the existing fence reservation, submit_once_offline and activation CAS.
No new order router or financial settlement assertions.
"""
import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from concurrent.futures import ThreadPoolExecutor
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_order_claim_shadow import canonical_intent_id,submit_once_offline
from short_recovery_lease_fence_offline import reserve_verified_rehedge_mock_only
from short_recovery_rehedge_fill_activation_offline import activate_verified_rehedge_offline
from short_recovery_standalone_offline import RECOVERY
from aster_gateway import AsterOrderIntent,PositionSide


class Exchange:
 offline_mock_only=True
 def __init__(self):
  self.short='0';self.open_status='NEW';self.order_id='close-4'
  self.fills=[{'id':4,'symbol':'XRPUSDT','orderId':'close-4','qty':'25',
               'realizedPnl':'1','commission':'.1'}]
  self.orders=[];self.posts=0;self.price='2.5'
 def account_information(self):return {'account':'u','hedgeMode':True}
 def position_risk(self,s):return [{'symbol':s,'positionSide':'LONG','positionAmt':'100'},
  {'symbol':s,'positionSide':'SHORT','positionAmt':self.short}]
 def open_orders(self,s):return self.orders
 def query_order(self,s,c):
  if self.order_id=='close-4':
   return {'symbol':s,'clientOrderId':c,'orderId':'close-4','status':'FILLED','executedQty':'25'}
  return {'symbol':s,'clientOrderId':c,'orderId':'open-2','status':self.open_status,'executedQty':'100' if self.open_status=='FILLED' else '0'}
 def user_trades(self,s,**k):return list(self.fills)
 def post(self,intent):
  self.posts+=1;self.order_id='open-2'
  return {'clientOrderId':intent.intent_id,'orderId':'open-2'}
 def mock_fill(self):
  self.open_status='FILLED';self.short='100'
  self.fills=[{'id':99,'symbol':'XRPUSDT','orderId':'open-2','qty':'100','price':self.price}]


class CombinedRehedge(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.r={k:Ref(self.db,k) for k in ('selector','position','prior','open','coord','owner','control')}
  self.old=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=4)
  self.new=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c2',side='SHORT',action='OPEN',step=0)
  self.now=datetime.now(timezone.utc);self.client=Exchange()
  self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  self.put('position',{'account':'u','symbol':'XRPUSDT','cycle':'c',
     'state':'FINAL_SHORT_FILLED_OFFLINE','financialSettlement':'UNRECONCILED',
     'offlineOnly':True})
  self.put('prior',{'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':self.old,
     'side':'SHORT','action':'CLOSE','step':4,'state':'CLOSED','orderId':'close-4',
     'executedQty':'25','quantityTerminalOnly':True,'terminalVerified':True,
     'financialVerified':False,'financialSettlement':'UNRECONCILED'})
  self.put('coord',{'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT',
      'cycle':'c','intentId':self.old,'state':'RECOVERY_SUBMITTING_RECONCILE_ONLY'},
      'lease':{'token':'lease-2','until':self.now+timedelta(minutes=1)}})
  self.put('owner',{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT',
    'ownershipVerified':True,'cycleConfirmed':True})
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
 def put(self,key,data):
  version,_=self.db.snapshot(key);self.db.commit(key,version,data)
 def reserve(self):
  return reserve_verified_rehedge_mock_only(mock_only=True,db=self.db,transactional=transactional,
   coordination_ref=self.r['coord'],owner_ref=self.r['owner'],final_claim_ref=self.r['prior'],
   control_ref=self.r['control'],account='u',symbol='XRPUSDT',old_cycle='c',
   new_cycle='c2',lease_token='lease-2',intent_id=self.new,now=self.now,
   client=self.client,long_qty=D(100),now_ms=10000,new_claim_ref=self.r['open'],
   allow_quantity_terminal_fence=True)
 def submit(self):
  return submit_once_offline(db=self.db,transactional=transactional,
   claim_ref=self.r['open'],control_ref=self.r['control'],coordination_ref=self.r['coord'],
   require_shared_fence=True,standalone_selector_ref=self.r['selector'],
   account='u',symbol='XRPUSDT',cycle='c2',
   intent=AsterOrderIntent(self.new,'XRPUSDT',PositionSide.SHORT,D(100),'OPEN'),
   account_close_guard=lambda:None,submit_mock=self.client.post)
 def activate(self):
  return activate_verified_rehedge_offline(db=self.db,transactional=transactional,
   client=self.client,selector_ref=self.r['selector'],position_ref=self.r['position'],
   open_claim_ref=self.r['open'],coordination_ref=self.r['coord'],control_ref=self.r['control'],
   account='u',symbol='XRPUSDT',old_cycle='c',new_cycle='c2',steps=4,step_pct='5')
 def test_real_existing_reserve_submit_reconcile_activate(self):
  self.assertEqual(self.reserve(),'RESERVED_REHEDGE_MOCK_ONLY')
  self.assertEqual(self.submit(),'SUBMITTED_RECONCILE_ONLY')
  self.assertEqual(self.client.posts,1)
  self.assertEqual(self.submit(),'BLOCKED_CLAIM_NOT_RESERVED')
  self.assertEqual(self.activate(),'BLOCKED_OPEN_ORDER_ID')
  self.assertEqual(self.db.snapshot('position')[1]['cycle'],'c')
  # A fresh mock Aster order GET ties this orderId to this exact clientOrderId.
  self.put('open',{**self.db.snapshot('open')[1],'orderId':'open-2'})
  self.client.mock_fill()
  self.assertEqual(self.activate(),'NEW_CYCLE_FILL_VERIFIED_FENCE_LOCKED')
  p=self.db.snapshot('position')[1]
  self.assertEqual((p['cycle'],p['anchor'],p['originalShortQty']),('c2','2.5','100'))
  self.assertEqual(self.db.snapshot('prior')[1]['financialSettlement'],'UNRECONCILED')
  self.assertEqual(self.client.posts,1)
  self.assertEqual(self.reserve(),'BLOCKED_REHEDGE_FINAL_READBACK')
  self.assertEqual(self.client.posts,1)
 def test_concurrent_worker_orders_and_restart(self):
  with ThreadPoolExecutor(max_workers=2) as pool:
   status=list(pool.map(lambda _:self.reserve(),(1,2)))
  self.assertEqual(status.count('RESERVED_REHEDGE_MOCK_ONLY'),1)
  with ThreadPoolExecutor(max_workers=2) as pool:
   status=list(pool.map(lambda _:self.submit(),(1,2)))
  self.assertEqual(status.count('SUBMITTED_RECONCILE_ONLY'),1)
  self.assertEqual(self.client.posts,1)
  self.db=self.db.restart();self.r={k:Ref(self.db,k) for k in self.r}
  self.assertEqual(self.submit(),'BLOCKED_CLAIM_NOT_RESERVED')
 def test_partial_unknown_stop_stale_fence(self):
  self.assertEqual(self.reserve(),'RESERVED_REHEDGE_MOCK_ONLY')
  self.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  self.assertEqual(self.submit(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  self.assertEqual(self.submit(),'SUBMITTED_RECONCILE_ONLY')
  self.put('open',{**self.db.snapshot('open')[1],'orderId':'open-2'})
  self.client.open_status='PARTIALLY_FILLED';self.client.short='25'
  self.assertEqual(self.activate(),'BLOCKED_INDEPENDENT_REHEDGE_FILL')
  self.client.open_status='FILLED';self.client.short='100';self.client.mock_fill()
  self.put('coord',{'recoveryFenceReservation':{'state':'stale'}})
  self.assertEqual(self.activate(),'BLOCKED_REHEDGE_FENCE')
if __name__=='__main__':unittest.main()
