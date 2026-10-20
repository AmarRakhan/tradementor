import unittest
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from short_recovery_offline_fence_bridge import make_denial_fence
from test_short_recovery_lease_fence_offline import LeaseFence
import aster_position_loss_auto_hedge as engine
class Client:
 def position_mode(self):return True
 def account_information(self):return {'availableBalance':'100000'}
 def query_order(self,*a,**k):return None
 def submit_order_once(self,*a,**k):raise AssertionError('NEVER SEND')
class Bridge(unittest.TestCase):
 def test_no_live_bridge(self):
  with self.assertRaises(ValueError):make_denial_fence(mock_only=False,db=None,transactional=None,refs={},account='u',symbol='XRPUSDT',cycle='c',lease_token='t',now=datetime.now(timezone.utc))
 def test_reconciler_denies_real_topup_candidate_offline(self):
  f=LeaseFence();f.setUp()
  fence=make_denial_fence(mock_only=True,db=f.db,transactional=__import__('short_recovery_multidoc_mock').transactional,refs=f.refs,account='u',symbol='XRPUSDT',cycle='c',lease_token='t',now=f.now)
  rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'},{'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':'-75','unRealizedProfit':'10','markPrice':'1.8'}]
  with patch.object(engine,'_exchange_rule',return_value=object()),patch.object(engine,'_exact_market_quantity',return_value=Decimal('25')),patch.object(engine,'_query_existing',return_value=None):
   result=engine.reconcile_auto_hedge(client=Client(),uid='u',threshold_usd=1,execute=True,protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[],pre_order_fence=fence)
  self.assertEqual(result['ordersSent'],0)
  self.assertEqual(result['actions'][0]['reason'],'PRE_ORDER_FENCE_DENIED')
  self.assertEqual(f.db.snapshot('lease')[1]['recoveryFenceReservation']['state'],'OFFLINE_ONLY')

 def test_owned_symbol_never_falls_back_to_unfenced_topup(self):
  rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'},
        {'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':'-75','unRealizedProfit':'10','markPrice':'1.8'}]
  with patch.object(engine,'_exchange_rule',return_value=object()),patch.object(engine,'_exact_market_quantity',return_value=Decimal('25')):
   result=engine.reconcile_auto_hedge(client=Client(),uid='u',threshold_usd=1,execute=True,
    protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[],
    recovery_fence_required_symbols={'XRPUSDT'})
  self.assertEqual(result['ordersSent'],0)
  self.assertEqual(result['actions'][0]['reason'],'RECOVERY_SHARED_FENCE_REQUIRED')
 def test_canonical_owned_short_denies_even_permissive_callback(self):
  rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'},
        {'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':'-75','unRealizedProfit':'10','markPrice':'1.8'}]
  class NoTransport(Client):
   def submit_order_once(self,*args,**kwargs):raise AssertionError('SHOULD_NOT_SUBMIT')
  calls=[]
  def permissive(*args):calls.append(args);return True
  result=engine.reconcile_auto_hedge(client=NoTransport(),uid='u',threshold_usd=1,execute=True,
      protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[],
      recovery_owned_symbols={'XRPUSDT'},pre_order_fence=permissive)
  self.assertEqual(result['ordersSent'],0)
  self.assertEqual(result['actions'][0]['reason'],'RECOVERY_OWNS_SHORT_NO_TOPUP')
  self.assertEqual(calls,[])

 def test_four_ten_partial_inventory_never_topups_recovery_owned_short(self):
  from short_recovery_multidoc_mock import MultiDocDB,Ref
  for steps in (4,10):
   for remaining in (Decimal('100')-Decimal('100')/steps,Decimal('50'),Decimal('0')):
    with self.subTest(steps=steps,remaining=str(remaining)):
     db=MultiDocDB()
     ref=Ref(db,('u','XRPUSDT','recovery'))
     db.commit(ref.key,0,{'account':'u','symbol':'XRPUSDT',
       'cycle':'c','state':'PARTIAL','remainingShort':str(remaining)})
     db=db.restart()
     self.assertEqual(db.snapshot(ref.key)[1]['remainingShort'],str(remaining))
     rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100',
       'unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'},
       {'symbol':'XRPUSDT','positionSide':'SHORT',
       'positionAmt':str(-remaining),'unRealizedProfit':'0','markPrice':'1.8'}]
     result=engine.reconcile_auto_hedge(client=Client(),uid='u',threshold_usd=1,
       execute=True,protected_sides={'XRPUSDT':'LONG'},positions=rows,
       open_orders=[],recovery_owned_symbols={'XRPUSDT'},
       pre_order_fence=lambda *args:True)
     self.assertEqual(result['ordersSent'],0)
     self.assertTrue(all(x.get('reason')!='PRE_ORDER_FENCE_APPROVED' for x in result['actions']))

 def test_malformed_existing_recovery_fence_blocks_normal_hedge(self):
  from short_recovery_lease_fence_offline import reserve_normal_hedge_mock_only
  from short_recovery_multidoc_mock import transactional
  for malformed in ('UNKNOWN', [], {'unverified':'claim'}):
   with self.subTest(malformed=malformed):
    f=LeaseFence();f.setUp()
    for key in ('owner','claim'):
     v,_=f.db.snapshot(key);f.db.commit(key,v,None)
    v,coord=f.db.snapshot('lease')
    f.db.commit('lease',v,{**coord,'recoveryFenceReservation':malformed})
    result=reserve_normal_hedge_mock_only(mock_only=True,db=f.db,transactional=transactional,
     coordination_ref=f.refs['lease'],owner_ref=f.refs['owner'],claim_ref=f.refs['claim'],
     control_ref=f.refs['control'],account='u',symbol='XRPUSDT',lease_token='t',
     intent_id='offline-normal',now=f.now)
    self.assertEqual(result,'BLOCKED_FENCE_ALREADY_RESERVED')
    self.assertEqual(f.db.snapshot('lease')[1]['recoveryFenceReservation'],malformed)

 def test_normal_one_to_one_mock_submit_without_recovery(self):
  class OfflineClient(Client):
   def __init__(self):self.submitted=[]
   def position_risk(self):return []
   def open_orders(self):return []
   def submit_order_once(self,intent,**kwargs):
    self.submitted.append(intent)
    return {'orderId':'mock-order','status':'FILLED','executedQty':str(intent.quantity)},False
  client=OfflineClient()
  rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'}]
  with patch.object(engine,'_exchange_rule',return_value=object()),patch.object(engine,'_exact_market_quantity',return_value=Decimal('100')):
   result=engine.reconcile_auto_hedge(client=client,uid='u',threshold_usd=1,execute=True,
    protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[])
  self.assertEqual(len(client.submitted),1,result)
  self.assertEqual(result['ordersSent'],1)
 def test_normal_hedge_shared_claim_mock_allows_once_and_blocks_recovery(self):
  from short_recovery_offline_fence_bridge import make_normal_hedge_mock_fence
  from short_recovery_multidoc_mock import transactional
  from short_recovery_order_claim_shadow import reserve
  f=LeaseFence();f.setUp()
  for key in ('owner','claim'):
   ver,_=f.db.snapshot(key);f.db.commit(key,ver,None)
  fence=make_normal_hedge_mock_fence(mock_only=True,db=f.db,transactional=transactional,
   refs=f.refs,account='u',symbol='XRPUSDT',lease_token='t',now=f.now)
  class MockClient(Client):
   def __init__(self):self.sent=[]
   def position_risk(self):return []
   def open_orders(self):return []
   def submit_order_once(self,intent,**kwargs):
    self.sent.append(intent.intent_id)
    return {'orderId':'offline-order','status':'FILLED','executedQty':str(intent.quantity)},False
  client=MockClient()
  rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'}]
  with patch.object(engine,'_exchange_rule',return_value=object()),patch.object(engine,'_exact_market_quantity',return_value=Decimal(100)):
   result=engine.reconcile_auto_hedge(client=client,uid='u',threshold_usd=1,execute=True,
     protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[],pre_order_fence=fence,
     recovery_fence_required_symbols={'XRPUSDT'})
  self.assertEqual(result['ordersSent'],1,result)
  self.assertEqual(len(client.sent),1)
  self.assertEqual(fence.last_result,'RESERVED_NORMAL_HEDGE_MOCK_ONLY')
  self.assertEqual(f.db.snapshot('lease')[1]['recoveryFenceReservation']['state'],'NORMAL_HEDGE_MOCK_SUBMITTING')
  self.assertFalse(fence('XRPUSDT','OPEN',client.sent[0]))
  self.assertEqual(fence.last_result,'BLOCKED_FENCE_ALREADY_RESERVED')
  from short_recovery_multidoc_mock import Ref
  marker=Ref(f.db,'marker')
  f.db.commit('marker',0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  self.assertEqual(reserve(db=f.db,transactional=transactional,marker_ref=marker,
    owner_ref=f.refs['owner'],ledger_ref=f.refs['ledger'],claim_ref=f.refs['claim'],
    control_ref=f.refs['control'],coordination_ref=f.refs['lease'],account='u',
    symbol='XRPUSDT',cycle='c',intent_id='x',now=1), 'BLOCKED_ACCOUNT_FENCE_RESERVED')
