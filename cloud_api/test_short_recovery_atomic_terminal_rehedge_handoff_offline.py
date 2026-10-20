import unittest
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from test_short_recovery_pair_atomic_settlement import PairAtomic
from short_recovery_multidoc_mock import Ref,transactional
from short_recovery_order_claim_shadow import canonical_intent_id,submit_once_offline
from short_recovery_lease_fence_offline import reserve_verified_rehedge_mock_only
from aster_gateway import AsterOrderIntent,PositionSide
from decimal import Decimal as D

class Mock:
 offline_mock_only=True
 def __init__(self):self.orders=[];self.short='0';self.status='FILLED'
 def account_information(self):return {'account':'u','hedgeMode':True}
 def position_risk(self,s):return [{'symbol':s,'positionSide':'LONG','positionAmt':'100'},{'symbol':s,'positionSide':'SHORT','positionAmt':self.short}]
 def open_orders(self,s):return self.orders
 def query_order(self,s,c):return {'symbol':s,'clientOrderId':c,'orderId':'SHORT-order','status':self.status,'executedQty':'25'}
 def user_trades(self,s,**kw):return [{'id':4,'symbol':s,'orderId':'SHORT-order','qty':'25','realizedPnl':'1','commission':'.1'}]

class AtomicTerminalHandoff(unittest.TestCase):
 def setUp(self):
  self.f=PairAtomic('test_complete_two_sided_atomic_settlement');self.f.setUp()
  self.client=Mock();self.now=datetime.now(timezone.utc)
  self.coord=Ref(self.f.db,'rehedge-coord');self.owner=Ref(self.f.db,'rehedge-owner');self.new=Ref(self.f.db,'rehedge-new')
  old_id=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=4)
  self.new_id=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c2',side='SHORT',action='OPEN',step=0)
  claim=self.f.snapshot('SHORTclaim');claim.update(side='SHORT',action='CLOSE',state='CLOSED',step=4,
    intentId=old_id,orderId='SHORT-order',executedQty='25',quantityTerminalOnly=True,
    terminalVerified=True,financialVerified=False,financialSettlement='UNRECONCILED')
  self.f.put('SHORTclaim',claim)
  self.f.db.commit(self.coord.key,0,{'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT','cycle':'c',
    'intentId':old_id,'state':'RECOVERY_SUBMITTING_RECONCILE_ONLY'},'lease':{
    'token':'new-cycle-lease','until':self.now+timedelta(seconds=60)}})
  self.f.db.commit(self.owner.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT',
    'ownershipVerified':True,'cycleConfirmed':True})
 def reserve(self,**kwargs):
  data=dict(mock_only=True,db=self.f.db,transactional=transactional,coordination_ref=self.coord,
    owner_ref=self.owner,final_claim_ref=self.f.refs['SHORTclaim'],control_ref=self.f.refs['control'],
    account='u',symbol='XRPUSDT',old_cycle='c',new_cycle='c2',lease_token='new-cycle-lease',
    intent_id=self.new_id,now=self.now,client=self.client,long_qty=D(100),now_ms=10000,
    new_claim_ref=self.new,allow_quantity_terminal_fence=True,require_financial_finality=False)
  data.update(kwargs)
  return reserve_verified_rehedge_mock_only(**data)
 def test_atomically_transfers_old_fence_to_new_claim_once(self):
  self.assertEqual(self.reserve(),'RESERVED_REHEDGE_MOCK_ONLY')
  self.assertEqual(self.f.db.snapshot(self.new.key)[1]['state'],'RESERVED')
  fence=self.f.db.snapshot(self.coord.key)[1]['recoveryFenceReservation']
  self.assertEqual(fence['cycle'],'c2')
  self.assertEqual(fence['previousCycle'],'c')
  self.assertEqual(self.reserve(),'BLOCKED_REHEDGE_NEW_CLAIM_EXISTS')
  self.assertFalse(self.f.snapshot('SHORTclaim')['financialVerified'])
 def test_two_workers_one_winner_restart_no_second_right(self):
  with ThreadPoolExecutor(max_workers=2) as pool:
   answers=list(pool.map(lambda _:self.reserve(),range(2)))
  self.assertEqual(answers.count('RESERVED_REHEDGE_MOCK_ONLY'),1)
  self.assertEqual(answers.count('BLOCKED_REHEDGE_NEW_CLAIM_EXISTS'),1)
  self.f.db=self.f.db.restart()
  self.coord=Ref(self.f.db,'rehedge-coord');self.owner=Ref(self.f.db,'rehedge-owner');self.new=Ref(self.f.db,'rehedge-new')
  self.f.bind()
  self.assertEqual(self.reserve(),'BLOCKED_REHEDGE_NEW_CLAIM_EXISTS')
 def test_unknown_partial_stop_and_open_orders_fail_closed(self):
  self.client.status='PARTIALLY_FILLED'
  self.assertEqual(self.reserve(),'BLOCKED_REHEDGE_FINAL_READBACK')
  self.client.status='FILLED';self.client.short='1'
  self.assertEqual(self.reserve(),'BLOCKED_REHEDGE_FINAL_READBACK')
  self.client.short='0';self.client.orders=[{'id':'pending'}]
  self.assertEqual(self.reserve(),'BLOCKED_REHEDGE_FINAL_READBACK')
  self.client.orders=[]
  self.f.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  self.assertEqual(self.reserve(),'BLOCKED_STOP')
 def test_no_opt_in_or_stale_lease(self):
  self.assertEqual(self.reserve(allow_quantity_terminal_fence=False),'BLOCKED_FENCE_ALREADY_RESERVED')
  self.assertEqual(self.reserve(require_financial_finality=True),'BLOCKED_FINANCIAL_FINALITY_UNVERIFIED')
  self.assertEqual(self.reserve(lease_token='stale'),'BLOCKED_LEASE_STALE')
if __name__=='__main__':unittest.main()
