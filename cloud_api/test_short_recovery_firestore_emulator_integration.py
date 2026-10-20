"""Opt-in official Firestore emulator integration; never accesses production."""
import os
import unittest
import uuid
from decimal import Decimal as D
from short_recovery_firestore_mock import encode, decode
from short_recovery_ledger import Ledger, Allocation
from short_recovery_order_claim_shadow import reserve
from short_recovery_order_resolution_shadow import resolve

@unittest.skipUnless(os.getenv('FIRESTORE_EMULATOR_HOST')=='127.0.0.1:18783' and os.getenv('GOOGLE_CLOUD_PROJECT')=='amar-short-recovery-offline-test', 'isolated emulator not explicitly configured')
class EmulatorIntegration(unittest.TestCase):
 def setUp(self):
  from google.cloud import firestore
  self.firestore=firestore;self.client=firestore.Client(project='amar-short-recovery-offline-test')
  base=self.client.collection('offline_recovery').document(uuid.uuid4().hex)
  self.refs={k:base.collection('docs').document(k) for k in ('marker','owner','ledger','claim','control')}
  self.refs['marker'].set({'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  self.refs['owner'].set({'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'})
  self.refs['ledger'].set(encode(Ledger('u','XRPUSDT',(Allocation('z','c',D(100)),))))
  self.refs['control'].set({'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
 def claim(self,intent='intent'):
  r=self.refs
  return reserve(db=self.client,transactional=self.firestore.transactional,marker_ref=r['marker'],owner_ref=r['owner'],ledger_ref=r['ledger'],claim_ref=r['claim'],control_ref=r['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id=intent,now=1)
 def resolve(self,event,**kw):
  r=self.refs
  return resolve(db=self.client,transactional=self.firestore.transactional,claim_ref=r['claim'],ledger_ref=r['ledger'],marker_ref=r['marker'],owner_ref=r['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event=event,**kw)
 def test_claim_and_duplicate_with_real_sdk(self):
  self.assertEqual(self.claim(),'RESERVED_SHADOW');self.assertEqual(self.claim(),'ALREADY_RESERVED')
  self.assertEqual(self.refs['claim'].get().to_dict()['state'],'RESERVED')
 def test_emergency_stop_blocks_real_transaction(self):
  self.refs['control'].update({'emergencyStop':True})
  self.assertEqual(self.claim(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
  self.assertFalse(self.refs['claim'].get().exists)
 def test_restart_client_unknown_reconcile(self):
  self.assertEqual(self.claim(),'RESERVED_SHADOW')
  self.client=self.firestore.Client(project='amar-short-recovery-offline-test')
  self.assertEqual(self.resolve('UNKNOWN'),'BLOCKED_UNKNOWN')
  self.refs['control'].update({'enabled':False})
  self.assertEqual(self.claim('new'),'BLOCKED_UNRESOLVED_CLAIM')
  self.assertEqual(self.resolve('LATE_ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED_RECOVERED')
 def test_confirmed_financial_settlement(self):
  self.assertEqual(self.claim(),'RESERVED_SHADOW')
  self.assertEqual(self.resolve('ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED')
  evidence={'confirmed':True,'orderId':'o','readbackVerified':True,'executionId':'ex1','quantity':'25','realizedPnl':'2','commission':'0.1','funding':'-0.05'}
  self.assertEqual(self.resolve('FILL',evidence=evidence,execution_id='ex1',quantity=25),'FILL_APPLIED')
  self.assertEqual(self.resolve('FILL',evidence=evidence,execution_id='ex1',quantity=25),'ALREADY_APPLIED')
  ledger=decode(self.refs['ledger'].get().to_dict())
  self.assertEqual(ledger.allocations[0].remaining,D(75))
  self.assertEqual(ledger.cycle_realized('c'),D('1.85'))
 def test_real_firestore_owner_to_autohedge_no_topup_after_client_restart(self):
  from unittest.mock import patch
  from short_recovery_gate import partition_reconciliation
  from aster_position_loss_auto_hedge import reconcile_auto_hedge
  class NoTransport:
   def position_mode(self):return True
   def account_information(self):return {'availableBalance':'100000'}
   def query_order(self,*args,**kwargs):return None
   def submit_order_once(self,*args,**kwargs):raise AssertionError('NO_SHORT_TOPUP_ALLOWED')
  for steps in (4,10):
   with self.subTest(steps=steps):
    self.refs['owner'].update({'remainingShort':str(D(100)-D(100)/steps)})
    self.client=self.firestore.Client(project='amar-short-recovery-offline-test')
    stored=self.refs['owner'].get().to_dict()
    partition=partition_reconciliation(settings={'enabled':True,'steps':steps,'stepPct':'5'},
       protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),
       recovery_cycles={'XRPUSDT':stored})
    owned=partition['shadow_skip']-partition['legacy_skip']
    self.assertEqual(owned,{'XRPUSDT'})
    rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100',
       'unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'},
       {'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':str(-(D(100)-D(100)/steps)),
       'unRealizedProfit':'0','markPrice':'1.8'}]
    with patch('aster_position_loss_auto_hedge._exchange_rule',return_value=object()),patch('aster_position_loss_auto_hedge._exact_market_quantity',return_value=D(100)/steps):
     result=reconcile_auto_hedge(client=NoTransport(),uid='u',threshold_usd=1,
       execute=True,protected_sides={'XRPUSDT':'LONG'},positions=rows,
       open_orders=[],recovery_owned_symbols=owned,pre_order_fence=lambda *args:True)
    self.assertEqual(result['ordersSent'],0)
    self.assertIn('RECOVERY_OWNS_SHORT_NO_TOPUP',[a.get('reason') for a in result['actions']])

 def test_real_firestore_four_ten_step_restart_partial_unknown_no_topup(self):
  from short_recovery_gate import partition_reconciliation
  from short_recovery_funding_provenance_decision import decide,NO_GO
  from aster_position_loss_auto_hedge import reconcile_auto_hedge
  from unittest.mock import patch
  class DenyTransport:
   def position_mode(self):return True
   def account_information(self):return {'availableBalance':'100000'}
   def query_order(self,*args,**kwargs):return None
   def submit_order_once(self,*args,**kwargs):raise AssertionError('NO TOPUP')
  selector=self.refs['control'].parent.document('selector')
  coordination=self.refs['control'].parent.document('coordination')
  selector.set({'account':'u','activeStrategy':'AUTO_HEDGE_SHORT_RECOVERY_2','offlineOnly':True})
  coordination.set({'account':'u','recoveryFenceReservation':{'state':'RECOVERY_CLAIM_RESERVED'}})
  for steps in (4,10):
   for step in range(1,steps+1):
    remaining=D(100)-D(100)*D(step)/D(steps)
    status='UNKNOWN' if step==2 else ('PARTIAL' if remaining else 'FINAL_PENDING')
    self.refs['owner'].update({'state':status,'remainingShort':str(remaining)})
    self.refs['claim'].set({'account':'u','symbol':'XRPUSDT','cycle':'c',
      'state':status,'side':'SHORT','action':'CLOSE','step':step})
    self.client=self.firestore.Client(project='amar-short-recovery-offline-test')
    self.assertEqual(selector.get().to_dict()['activeStrategy'],'AUTO_HEDGE_SHORT_RECOVERY_2')
    self.assertIsNotNone(coordination.get().to_dict().get('recoveryFenceReservation'))
    owner=self.refs['owner'].get().to_dict()
    # Never transform persisted UNKNOWN into PARTIAL merely to pass a test.
    # The partition intentionally cannot certify UNKNOWN ownership; the
    # account-level denial remains a separate, required authorization gate.
    partition=partition_reconciliation(settings={'enabled':True,'steps':steps,'stepPct':'5'},
      protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),recovery_cycles={'XRPUSDT':owner})
    owned=partition['shadow_skip']-partition['legacy_skip']
    if status=='UNKNOWN':
     self.assertEqual(owned,set())
     self.assertEqual(partition['pairs']['XRPUSDT'],'BLOCKED_UNVERIFIED')
     self.assertEqual(decide(account='u',symbol='XRPUSDT',cycle='c',income_rows=[]),NO_GO)
    else:
     self.assertEqual(owned,{'XRPUSDT'})
    rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100',
      'unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'},
      {'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':str(-remaining),
      'unRealizedProfit':'0','markPrice':'1.8'}]
    with patch('aster_position_loss_auto_hedge._exchange_rule',return_value=object()),patch('aster_position_loss_auto_hedge._exact_market_quantity',return_value=D(100)/steps):
     report=reconcile_auto_hedge(client=DenyTransport(),uid='u',threshold_usd=1,execute=True,
       protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[],
       recovery_owned_symbols={'XRPUSDT'},pre_order_fence=lambda *args:True)
    self.assertEqual(report['ordersSent'],0)
    self.assertIn('RECOVERY_OWNS_SHORT_NO_TOPUP',[a.get('reason') for a in report['actions']])
    self.assertEqual(decide(account='u',symbol='XRPUSDT',cycle='c',income_rows=[]),NO_GO)

 def test_shared_account_fence_blocks_concurrent_recovery_claim_and_restart(self):
  import concurrent.futures,threading
  coord=self.refs['control'].parent.document('coordination')
  coord.set({'account':'u'})
  barrier=threading.Barrier(3)
  def attempt(_):
   barrier.wait(timeout=10)
   return reserve(db=self.client,transactional=self.firestore.transactional,
    marker_ref=self.refs['marker'],owner_ref=self.refs['owner'],
    ledger_ref=self.refs['ledger'],claim_ref=self.refs['claim'],
    control_ref=self.refs['control'],coordination_ref=coord,
    account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',now=1)
  with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
   answers=list(pool.map(attempt,range(3)))
  self.assertEqual(answers.count('RESERVED_SHADOW'),1,answers)
  self.assertTrue(all(x in ('RESERVED_SHADOW','BLOCKED_ACCOUNT_FENCE_RESERVED',
    'BLOCKED_TRANSACTION_FAILURE') for x in answers),answers)
  self.client=self.firestore.Client(project='amar-short-recovery-offline-test')
  self.assertIsNotNone(coord.get().to_dict()['recoveryFenceReservation'])
  self.assertEqual(self.claim('other'),'BLOCKED_UNRESOLVED_CLAIM')
  self.assertEqual(reserve(db=self.client,transactional=self.firestore.transactional,
    marker_ref=self.refs['marker'],owner_ref=self.refs['owner'],
    ledger_ref=self.refs['ledger'],claim_ref=self.refs['claim'],
    control_ref=self.refs['control'],coordination_ref=coord,
    account='u',symbol='XRPUSDT',cycle='c',intent_id='other',now=2),
    'BLOCKED_ACCOUNT_FENCE_RESERVED')

 def test_concurrent_claims_single_winner(self):
  import concurrent.futures
  import threading
  barrier=threading.Barrier(4)
  def work(i):
   barrier.wait()
   return self.claim('concurrent-'+str(i))
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
   futures=[executor.submit(work,i) for i in range(4)]
   results=[f.result(timeout=15) for f in futures]
  self.assertEqual(results.count('RESERVED_SHADOW'),1)
  self.assertEqual(results.count('BLOCKED_UNRESOLVED_CLAIM'),3)

@unittest.skipUnless(os.getenv('FIRESTORE_EMULATOR_HOST')=='127.0.0.1:18783' and os.getenv('GOOGLE_CLOUD_PROJECT')=='amar-short-recovery-offline-test', 'isolated emulator not explicitly configured')
class PairCloseEmulator(unittest.TestCase):
 def test_side_scoped_atomic_pair_and_partial_replay(self):
  from google.cloud import firestore
  from short_recovery_order_resolution_shadow import reconcile_pair_close
  client=firestore.Client(project='amar-short-recovery-offline-test')
  base=client.collection('offline_recovery_pair').document(uuid.uuid4().hex)
  refs={k:base.collection('docs').document(k) for k in ('control','pair','LONGclaim','SHORTclaim','LONGledger','SHORTledger')}
  refs['control'].set({'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  refs['pair'].set({'account':'u','symbol':'XRPUSDT','cycle':'c','state':'OPEN','fundingCycleVerified':True})
  for side in ('LONG','SHORT'):
   refs[side+'claim'].set({'account':'u','symbol':'XRPUSDT','cycle':'c','positionSide':side,'intentId':side+'-intent','orderId':side+'-order','state':'ACKED'})
   refs[side+'ledger'].set(encode(Ledger('u','XRPUSDT',(Allocation(side,'c',D(100 if side=='LONG' else 75)),))))
  def row(side,quantity,status):
   return {'symbol':'XRPUSDT','positionSide':side,'orderId':side+'-order','readbackVerified':True,'fillsComplete':True,'incomeHistoryComplete':True,'terminalVerified':status=='FILLED','status':status,'executedQty':str(quantity),'fills':[{'orderId':side+'-order','executionId':side+'-ex','quantity':str(quantity),'realizedPnl':'1','commission':'.1','funding':'-.05','financialVerified':True,'fundingOwnershipVerified':True}]}
  rows={'LONG':row('LONG',100,'FILLED'),'SHORT':row('SHORT',25,'UNKNOWN')}
  def run():
   return reconcile_pair_close(db=client,transactional=firestore.transactional,claim_refs={s:refs[s+'claim'] for s in ('LONG','SHORT')},ledger_refs={s:refs[s+'ledger'] for s in ('LONG','SHORT')},control_ref=refs['control'],pair_ref=refs['pair'],account='u',symbol='XRPUSDT',cycle='c',readbacks=rows)
  # Two genuinely concurrent SDK transactions race on the same canonical refs.
  import concurrent.futures,threading
  barrier=threading.Barrier(2)
  def raced():
   barrier.wait(timeout=10)
   return run()
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
   futures=[executor.submit(raced) for _ in range(2)]
   outcomes=[f.result(timeout=30) for f in futures]
  self.assertEqual(outcomes,['PAIR_RECONCILE_REQUIRED']*2)
  self.assertEqual(run(),'PAIR_RECONCILE_REQUIRED')
  self.assertEqual(refs['SHORTclaim'].get().to_dict()['state'],'UNKNOWN')
  self.assertEqual(decode(refs['SHORTledger'].get().to_dict()).allocations[0].remaining,D(50))
  refs['control'].update({'emergencyStop':True})
  self.assertEqual(run(),'PAIR_RECONCILE_REQUIRED')
  self.assertNotEqual(refs['pair'].get().to_dict()['state'],'CLOSED')

@unittest.skipUnless(os.getenv('FIRESTORE_EMULATOR_HOST')=='127.0.0.1:18783' and os.getenv('GOOGLE_CLOUD_PROJECT')=='amar-short-recovery-offline-test', 'isolated emulator not explicitly configured')
class PairSubmitLockEmulator(unittest.TestCase):
 def test_pair_submit_lock_is_atomic_replay_safe(self):
  from google.cloud import firestore
  from aster_gateway import AsterOrderIntent,PositionSide
  from short_recovery_order_claim_shadow import canonical_intent_id,lock_pair_submit_offline
  client=firestore.Client(project='amar-short-recovery-offline-test')
  base=client.collection('offline_pair_submit').document(uuid.uuid4().hex)
  refs={key:base.collection('docs').document(key) for key in ('LONG','SHORT','control')}
  refs['control'].set({'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  intents={}
  for side in ('LONG','SHORT'):
   intent_id=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side=side,action='CLOSE',step=1)
   refs[side].set({'account':'u','symbol':'XRPUSDT','cycle':'c','side':side,'action':'CLOSE','step':1,'intentId':intent_id,'state':'RESERVED'})
   intents[side]=AsterOrderIntent(intent_id,'XRPUSDT',PositionSide(side),D(10),'CLOSE')
  def lock():
   return lock_pair_submit_offline(db=client,transactional=firestore.transactional,long_claim_ref=refs['LONG'],short_claim_ref=refs['SHORT'],control_ref=refs['control'],account='u',symbol='XRPUSDT',cycle='c',long_intent=intents['LONG'],short_intent=intents['SHORT'],account_close_guard=lambda:None)
  self.assertEqual(lock(),'PAIR_SUBMITTING_LOCKED')
  self.assertEqual(refs['LONG'].get().to_dict()['state'],'SUBMITTING')
  self.assertEqual(refs['SHORT'].get().to_dict()['state'],'SUBMITTING')
  self.assertEqual(lock(),'BLOCKED_PAIR_SIDE_CLAIMS')
  client=firestore.Client(project='amar-short-recovery-offline-test')
  self.assertEqual(lock(),'BLOCKED_PAIR_SIDE_CLAIMS')
