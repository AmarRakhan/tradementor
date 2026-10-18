"""Offline _run_uid integration with all exchange, Firestore, account services mocked."""
import os, unittest, sys, types
from unittest.mock import patch, MagicMock
main_stub=types.ModuleType('main')
main_stub.app=__import__('fastapi').FastAPI()
main_stub.authenticated_user=lambda: {'uid':'u'}
main_stub.require_release_feature=lambda *a,**k: True
main_stub.user_reference=lambda *a,**k: MagicMock()
main_stub.db=MagicMock()
main_stub.AsterV3Client=MagicMock
main_stub.load_aster_secret=lambda *a,**k: {}
main_stub.local_eip712_signer=lambda *a,**k: None
main_stub._block_order_during_close_all=lambda *a,**k: None
main_stub._release_feature_enabled_for_uid=lambda *args: True
main_stub._acquire_aster_account_coordination=lambda *args: 'token'
main_stub._release_aster_account_coordination=lambda *args: None
with patch.dict(sys.modules,{'main':main_stub}):
 import aster_position_loss_auto_hedge_extension as module
from test_short_recovery_pair_aster_bridge import VerifiedAsterBridge

class RunUidIntegration(unittest.TestCase):
 def run_case(self, *, enabled=True, ownership=True, force_shadow=True, execution_enabled=False, mock_scope=True, proof=True, action_mode=None, emergency_stop=False, mock_transport=None, readback_mode=None, existing_short_state=None, inventory_readback='fixture', inventory_mock_client=None, restart_readback_mock_client=None, existing_harness=None, rehedge_final_readback="fixture"):
  h=existing_harness or VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement')
  if existing_harness is None:h.setUp()
  if inventory_readback=='fixture':
   inventory_readback={'account':'u','symbol':'XRPUSDT','verified':True,'hedgeMode':True,'openOrders':[],'timestampMs':9999,'LONG':'100','SHORT':'0' if action_mode=='REHEDGE' else '100'}
  ctx={'client':h.client,'claim_refs':{s:h.fixture.refs[s+'claim'] for s in ('LONG','SHORT')},'ledger_refs':{s:h.fixture.refs[s+'ledger'] for s in ('LONG','SHORT')},'control_ref':h.fixture.refs['control'],'pair_ref':h.fixture.refs['pair'],'db':h.fixture.db,'transactional':__import__('short_recovery_multidoc_mock').transactional,'account':'u' if mock_scope else 'other','symbol':'XRPUSDT','cycle':'c','mock_only':True,'financial_proof':h.proof if proof else None,'restart_readback_mock_client':restart_readback_mock_client}
  if action_mode is not None:
   from decimal import Decimal as D
   from short_recovery_contract import Plan
   from short_recovery_reduction import ReductionState
   plan=Plan(D(2),D(100),D(5),4)
   closed=D(100) if action_mode=='REHEDGE' else D(0)
   qty=D(0) if action_mode=='REHEDGE' else D(100)
   state=ReductionState(plan,closed,D('1.6' if action_mode=='REHEDGE' else '1.9'))
   from short_recovery_order_claim_shadow import canonical_intent_id
   ids={key:canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side=key.split('_')[0],action=key.split('_')[1],step=1) for key in ('LONG_CLOSE','SHORT_CLOSE','SHORT_OPEN')}
   if action_mode=='PAIR_EXIT':
    def canonical_query(symbol,cid):
     side='LONG' if cid==ids['LONG_CLOSE'] else 'SHORT' if cid==ids['SHORT_CLOSE'] else 'INVALID'
     return {'symbol':symbol,'clientOrderId':cid,'orderId':side+'-order',
             'status':'FILLED','executedQty':'100' if side=='LONG' else '75'}
    h.client.query_order=canonical_query
   if action_mode=='PAIR_EXIT' and readback_mode:
    original=h.client.user_trades
    def trades(symbol,limit=500,from_id=None):
     rows=original(symbol,limit=limit,from_id=from_id)
     if readback_mode=='DUPLICATE':return rows+[dict(rows[-1])]
     if readback_mode=='PARTIAL':
      return [{**row,'qty':'25'} if row['orderId']=='SHORT-order' else row for row in rows]
     return rows
    h.client.user_trades=trades
    if readback_mode=='PARTIAL':
     previous=h.client.query_order
     def partial_query(symbol,cid):
      row=previous(symbol,cid)
      if row['orderId']=='SHORT-order':row={**row,'status':'PARTIALLY_FILLED','executedQty':'25'}
      return row
     h.client.query_order=partial_query
   if rehedge_final_readback=='fixture' and action_mode=='REHEDGE':
    rehedge_final_readback={'account':'u','symbol':'XRPUSDT','cycle':'c','positionSide':'SHORT','action':'CLOSE','orderStatus':'FILLED','terminalVerified':True,'fillsComplete':True,'shortInventoryZeroVerified':True,'orderId':'previous-short-close','intentId':'previous-short-close-id'}
   ctx['recovery_action']={'rehedge_final_readback':rehedge_final_readback,'state':state,'short_qty':qty,'long_qty':D(100),
       'net_exit_due':action_mode=='PAIR_EXIT','net_evidence_verified':proof,
       'claim_ref':h.fixture.refs['SHORTclaim'],'intent_id':ids['SHORT_OPEN' if action_mode=='REHEDGE' else 'SHORT_CLOSE'],'step':1,
       'account_close_guard':lambda:None,'intent_ids':ids, 'submit_mock':mock_transport, 'offline_mock_confirmed':mock_transport is not None,'inventory_now_ms':10000,'inventory_readback':inventory_readback,'inventory_mock_client':inventory_mock_client}
   h.fixture.put('SHORTclaim',{**h.fixture.snapshot('SHORTclaim'),'state':'RESERVED','intentId':ctx['recovery_action']['intent_id'],'side':'SHORT','action':'OPEN' if action_mode=='REHEDGE' else 'CLOSE','step':1})
   if action_mode=='PAIR_EXIT':
    ctx['recovery_action']['long_claim_ref']=h.fixture.refs['LONGclaim']
    h.fixture.put('LONGclaim',{**h.fixture.snapshot('LONGclaim'),'state':'RESERVED','intentId':ids['LONG_CLOSE'],'side':'LONG','action':'CLOSE','step':1})
   if emergency_stop:h.fixture.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  if existing_short_state is not None:
   h.fixture.put('SHORTclaim',{**h.fixture.snapshot('SHORTclaim'),'state':existing_short_state})
  states={'XRPUSDT':{'ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':ownership,'state':'PARTIAL'}}
  dummy=MagicMock();dummy.position_risk.return_value=[];dummy.open_orders.return_value=[]
  doc=MagicMock();report={'mode':'SHADOW','ordersSent':0,'actions':[]}
  with patch.object(module,'EXECUTION_ENABLED',execution_enabled),patch.dict(os.environ,{'ASTER_SHORT_RECOVERY_SHADOW_ENABLED':'true'}),patch.object(module.main,'_release_feature_enabled_for_uid',return_value=True),patch.object(module,'_pair_states',return_value={}),patch.object(module,'_current',return_value={'enabled':True,'thresholdUsd':1,'shortRecoveryPlan':{'enabled':enabled,'steps':4,'stepPct':'5'}}),patch.object(module,'_client',return_value=dummy),patch.object(module,'_prepare_lifecycle',return_value=({'XRPUSDT':'LONG'},set(),states,[])),patch.object(module,'_dynamic_hedge_enabled',return_value=False),patch.object(module,'_doc',return_value=doc),patch.object(module,'_audit'),patch.object(module,'reconcile_auto_hedge',return_value=report) as recon,patch.object(module.main,'_acquire_aster_account_coordination',return_value='token'),patch.object(module.main,'_release_aster_account_coordination'),patch.object(module,'_sync_pair_views'):
   result=module._run_uid('u',force_shadow=force_shadow,offline_pair_settlement=ctx)
  return result,recon,h
 def test_verified_pair_close_calls_real_atomic_resolver(self):
  r,recon,h=self.run_case()
  self.assertEqual(r['shortRecoveryPairSettlement'],'PAIR_CLOSED_VERIFIED')
  self.assertEqual(h.fixture.snapshot('pair')['state'],'CLOSED')
  self.assertEqual(recon.call_args.kwargs['recovery_shadow_skip_symbols'],{'XRPUSDT'})
 def test_disabled_does_not_settle_or_suppress(self):
  r,recon,h=self.run_case(enabled=False)
  self.assertEqual(r['shortRecoveryPairSettlement'],'BLOCKED_RECOVERY_DISABLED')
  self.assertIsNone(recon.call_args.kwargs['recovery_shadow_skip_symbols']) if recon.call_args.kwargs['recovery_shadow_skip_symbols'] is None else self.assertEqual(recon.call_args.kwargs['recovery_shadow_skip_symbols'],set())
  self.assertEqual(h.fixture.snapshot('pair')['state'],'OPEN')
 def test_wrong_scope_not_settled(self):
  r,_,h=self.run_case(mock_scope=False)
  self.assertEqual(r['shortRecoveryPairSettlement'],'BLOCKED_MOCK_SCOPE');self.assertEqual(h.fixture.snapshot('pair')['state'],'OPEN')
 def test_missing_funding_not_settled(self):
  r,_,h=self.run_case(proof=False)
  self.assertEqual(r['shortRecoveryPairSettlement'],'BLOCKED_FUNDING_CYCLE_PROOF');self.assertEqual(h.fixture.snapshot('pair')['state'],'OPEN')
 def test_execute_true_never_calls_recovery_pair_executor(self):
  r,recon,h=self.run_case(execution_enabled=True,force_shadow=False)
  self.assertEqual(r['shortRecoveryPairSettlement'],'BLOCKED_OFFLINE_ONLY')
  self.assertIsNone(recon.call_args.kwargs['recovery_shadow_skip_symbols'])
  self.assertEqual(h.fixture.snapshot('pair')['state'],'OPEN')
 def test_unverified_ownership_not_suppressed(self):
  r,recon,h=self.run_case(ownership=False)
  self.assertEqual(recon.call_args.kwargs['recovery_shadow_skip_symbols'],set())
  self.assertEqual(r['shortRecoveryPairSettlement'],'BLOCKED_RECOVERY_OWNERSHIP')
  self.assertEqual(h.fixture.snapshot('pair')['state'],'OPEN')

class ThreeActionsRunUid(unittest.TestCase):
 def test_reduce_mapped_through_pre_submit(self):
  r,_,_=RunUidIntegration().run_case(action_mode='REDUCE')
  self.assertEqual(r['shortRecoveryAction']['status'],'PREVIEW_SHORT_REDUCE')
  self.assertEqual(r['shortRecoveryAction']['ordersSent'],0)
 def test_rehedge_mapped_through_pre_submit(self):
  r,_,_=RunUidIntegration().run_case(action_mode='REHEDGE')
  self.assertEqual(r['shortRecoveryAction']['status'],'PREVIEW_REHEDGE_REQUIRES_FINAL_READBACK')
 def test_pair_exit_requires_financial_proof(self):
  r,_,_=RunUidIntegration().run_case(action_mode='PAIR_EXIT',proof=False)
  self.assertEqual(r['shortRecoveryAction']['status'],'BLOCKED_NET_EVIDENCE')
 def test_stop_blocks_all_action_intents(self):
  r,_,_=RunUidIntegration().run_case(action_mode='REDUCE',emergency_stop=True)
  self.assertEqual(r['shortRecoveryAction']['status'],'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
 def test_execute_true_does_not_prepare_action(self):
  r,_,_=RunUidIntegration().run_case(action_mode='REDUCE',execution_enabled=True,force_shadow=False)
  self.assertNotIn('shortRecoveryAction',r)

class SubmittedRunUid(unittest.TestCase):
 def test_short_reduction_atomic_submit_and_mock_transport(self):
  mock=MagicMock(return_value=({'orderId':123},False))
  r,_,h=RunUidIntegration().run_case(action_mode='REDUCE',mock_transport=mock)
  self.assertEqual(r['shortRecoverySubmit'],('SUBMITTED_RECONCILE_ONLY',))
  self.assertEqual(mock.call_count,1)
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')
  self.assertEqual(r['shortRecoveryPairSettlement'],'PAIR_RECONCILE_REQUIRED_NO_TERMINAL_ACK')
 def test_rehedge_atomic_submit_and_mock_transport(self):
  mock=MagicMock(return_value=({'orderId':123},False))
  r,_,h=RunUidIntegration().run_case(action_mode='REHEDGE',mock_transport=mock)
  self.assertEqual(r['shortRecoveryAction']['status'],'BLOCKED_REHEDGE_FINAL_READBACK')
  mock.assert_not_called()
 def test_timeout_retains_submitting(self):
  mock=MagicMock(side_effect=TimeoutError('mock timeout'))
  r,_,h=RunUidIntegration().run_case(action_mode='REDUCE',mock_transport=mock)
  self.assertEqual(r['shortRecoverySubmit'],('UNKNOWN_RECONCILE_ONLY',))
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')
 def test_emergency_stop_sends_no_transport(self):
  mock=MagicMock()
  r,_,_=RunUidIntegration().run_case(action_mode='REDUCE',emergency_stop=True,mock_transport=mock)
  self.assertNotIn('shortRecoverySubmit',r)
  mock.assert_not_called()
 def test_live_execution_never_calls_offline_submit(self):
  mock=MagicMock()
  r,_,_=RunUidIntegration().run_case(action_mode='REDUCE',execution_enabled=True,force_shadow=False,mock_transport=mock)
  self.assertNotIn('shortRecoverySubmit',r)
  mock.assert_not_called()

class WholePairLifecycle(unittest.TestCase):
 def test_atomic_submit_then_readback_settlement_with_injected_cycle_proof(self):
  h=RunUidIntegration()
  calls=[]
  def submit(intent):
   calls.append(intent.intent_id)
   return {'clientOrderId':intent.intent_id,'orderId':intent.position_side.value+'-order'}
  result,_,fixture=h.run_case(action_mode='PAIR_EXIT',mock_transport=submit)
  self.assertEqual(result['shortRecoverySubmit'],('SUBMITTED_RECONCILE_ONLY','SUBMITTED_RECONCILE_ONLY'))
  self.assertEqual(result['shortRecoveryPairSettlement'],'PAIR_CLOSED_VERIFIED')
  self.assertEqual(fixture.fixture.snapshot('pair')['state'],'CLOSED')
  self.assertEqual(len(calls),2)
 def test_unknown_short_no_second_post_or_pair_close(self):
  def submit(intent):
   if intent.position_side.value=='SHORT':raise TimeoutError('mock short uncertain')
   return {'clientOrderId':intent.intent_id,'orderId':'LONG-order'}
  result,_,fixture=RunUidIntegration().run_case(action_mode='PAIR_EXIT',mock_transport=submit)
  self.assertEqual(result['shortRecoverySubmit'],('SUBMITTED_RECONCILE_ONLY','UNKNOWN_RECONCILE_ONLY'))
  self.assertEqual(result['shortRecoveryPairSettlement'],'PAIR_RECONCILE_REQUIRED_NO_TERMINAL_ACK')
  self.assertNotEqual(fixture.fixture.snapshot('pair')['state'],'CLOSED')
 def test_no_income_proof_prevents_pair_closing(self):
  r,_,h=RunUidIntegration().run_case(action_mode='PAIR_EXIT',proof=False)
  self.assertNotEqual(h.fixture.snapshot('pair')['state'],'CLOSED')

 def test_partial_readback_never_closes_pair(self):
  def submit(intent):return {'clientOrderId':intent.intent_id,'orderId':intent.position_side.value+'-order'}
  r,_,h=RunUidIntegration().run_case(action_mode='PAIR_EXIT',mock_transport=submit,readback_mode='PARTIAL')
  self.assertNotEqual(r['shortRecoveryPairSettlement'],'PAIR_CLOSED_VERIFIED')
  self.assertNotEqual(h.fixture.snapshot('pair')['state'],'CLOSED')
 def test_duplicate_execution_never_closes_pair(self):
  def submit(intent):return {'clientOrderId':intent.intent_id,'orderId':intent.position_side.value+'-order'}
  r,_,h=RunUidIntegration().run_case(action_mode='PAIR_EXIT',mock_transport=submit,readback_mode='DUPLICATE')
  self.assertNotEqual(r['shortRecoveryPairSettlement'],'PAIR_CLOSED_VERIFIED')
  self.assertNotEqual(h.fixture.snapshot('pair')['state'],'CLOSED')
 def test_long_timeout_blocks_short_and_pair_close(self):
  calls=[]
  def submit(intent):
   calls.append(intent.intent_id)
   raise TimeoutError('mock LONG timeout')
  r,_,h=RunUidIntegration().run_case(action_mode='PAIR_EXIT',mock_transport=submit)
  self.assertEqual(r['shortRecoverySubmit'],('UNKNOWN_RECONCILE_ONLY',))
  self.assertEqual(len(calls),1)
  self.assertEqual(h.fixture.snapshot('LONGclaim')['state'],'SUBMITTING')
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')
  self.assertNotEqual(h.fixture.snapshot('pair')['state'],'CLOSED')
 def test_short_timeout_replay_after_restart_is_not_resent(self):
  calls=[]
  def submit(intent):
   calls.append(intent.intent_id)
   if intent.position_side.value=='SHORT':raise TimeoutError('uncertain')
   return {'clientOrderId':intent.intent_id,'orderId':'LONG-order'}
  r,_,h=RunUidIntegration().run_case(action_mode='PAIR_EXIT',mock_transport=submit)
  self.assertEqual(r['shortRecoverySubmit'],('SUBMITTED_RECONCILE_ONLY','UNKNOWN_RECONCILE_ONLY'))
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')
  from short_recovery_order_claim_shadow import submit_locked_pair_mock_offline,canonical_intent_id
  from aster_gateway import AsterOrderIntent,PositionSide
  from decimal import Decimal
  from short_recovery_multidoc_mock import transactional
  h.fixture.db=h.fixture.db.restart();h.fixture.bind();refs=h.fixture.refs
  ids={s:canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side=s,action='CLOSE',step=1) for s in ('LONG','SHORT')}
  intents={s:AsterOrderIntent(ids[s],'XRPUSDT',PositionSide(s),Decimal(100 if s=='LONG' else 75),'CLOSE') for s in ids}
  outcome=submit_locked_pair_mock_offline(db=h.fixture.db,transactional=transactional,long_claim_ref=refs['LONGclaim'],short_claim_ref=refs['SHORTclaim'],control_ref=refs['control'],account='u',symbol='XRPUSDT',cycle='c',long_intent=intents['LONG'],short_intent=intents['SHORT'],account_close_guard=lambda:None,submit_mock=submit)
  self.assertEqual(outcome,('BLOCKED_PAIR_SIDE_CLAIMS',))
  self.assertEqual(len(calls),2)
  self.assertNotEqual(h.fixture.snapshot('pair')['state'],'CLOSED')

class RestartedPairReconciliation(unittest.TestCase):
 def test_unknown_with_known_order_may_reconcile_terminal_without_resubmit(self):
  r,_,h=RunUidIntegration().run_case(existing_short_state='UNKNOWN')
  self.assertEqual(r['shortRecoveryPairSettlement'],'PAIR_CLOSED_VERIFIED')
  self.assertEqual(h.fixture.snapshot('pair')['state'],'CLOSED')
  self.assertNotIn('shortRecoverySubmit',r)
 def test_unacknowledged_submitting_cannot_reconcile(self):
  r,_,h=RunUidIntegration().run_case(existing_short_state='SUBMITTING')
  self.assertEqual(r['shortRecoveryPairSettlement'],'PAIR_RECONCILE_REQUIRED_NO_TERMINAL_ACK')
  self.assertEqual(h.fixture.snapshot('pair')['state'],'OPEN')
 def test_unknown_with_missing_cycle_funding_proof_still_blocked(self):
  r,_,h=RunUidIntegration().run_case(existing_short_state='UNKNOWN',proof=False)
  self.assertEqual(r['shortRecoveryPairSettlement'],'BLOCKED_FUNDING_CYCLE_PROOF')
  self.assertNotEqual(h.fixture.snapshot('pair')['state'],'CLOSED')

class ConservativeExitIsNotLiveAuthorization(unittest.TestCase):
 def test_offline_pair_tp_without_independent_financial_proof_never_submits(self):
  calls=[]
  def submit(intent):calls.append(intent);raise AssertionError('unproven pair must not POST')
  result,_,h=RunUidIntegration().run_case(action_mode='PAIR_EXIT',proof=False,mock_transport=submit)
  self.assertNotEqual(result.get('shortRecoveryPairSettlement'),'PAIR_CLOSED_VERIFIED')
  self.assertEqual(h.fixture.snapshot('pair')['state'],'OPEN')
  self.assertEqual(calls,[])
 def test_legacy_execution_flag_never_uses_offline_transport(self):
  calls=[]
  def submit(intent):calls.append(intent);raise AssertionError('offline transport called')
  result,_,_=RunUidIntegration().run_case(action_mode='PAIR_EXIT',execution_enabled=True,force_shadow=False,mock_transport=submit)
  self.assertNotIn('shortRecoverySubmit',result)
  self.assertEqual(calls,[])

class MandatoryOfflineInventory(unittest.TestCase):
 def test_missing_fresh_inventory_blocks_mock_short_reduction(self):
  m=MagicMock()
  r,_,_=RunUidIntegration().run_case(action_mode='REDUCE',mock_transport=m,inventory_readback=None)
  self.assertEqual(r['shortRecoveryAction']['status'],'BLOCKED_INVENTORY_UNVERIFIED')
  m.assert_not_called()
 def test_verified_exchange_shaped_inventory_allows_mock_reduction(self):
  m=MagicMock(return_value=({'orderId':123},False))
  inventory={'account':'u','symbol':'XRPUSDT','verified':True,'hedgeMode':True,'openOrders':[],'timestampMs':9999,'LONG':'100','SHORT':'100'}
  r,_,_=RunUidIntegration().run_case(action_mode='REDUCE',mock_transport=m,inventory_readback=inventory)
  self.assertEqual(r['shortRecoverySubmit'],('SUBMITTED_RECONCILE_ONLY',));m.assert_called_once()
 def test_stale_inventory_blocks_mock_reduction(self):
  m=MagicMock()
  inventory={'account':'u','symbol':'XRPUSDT','verified':True,'hedgeMode':True,'openOrders':[],'timestampMs':1,'LONG':'100','SHORT':'100'}
  r,_,_=RunUidIntegration().run_case(action_mode='REDUCE',mock_transport=m,inventory_readback=inventory)
  self.assertEqual(r['shortRecoveryAction']['status'],'BLOCKED_INVENTORY_STALE_OR_SCOPE');m.assert_not_called()

class TwoLegFreshInventory(unittest.TestCase):
 def test_short_second_leg_blocks_after_inventory_changes(self):
  from test_short_recovery_mock_aster_inventory import Client
  c=Client();c.qty='75';calls=[]
  def submit(intent):
   calls.append(intent.position_side.value)
   if intent.position_side.value=='LONG':c.qty='0'
   return {'clientOrderId':intent.intent_id,'orderId':intent.position_side.value+'-order'}
  r,_,h=RunUidIntegration().run_case(action_mode='PAIR_EXIT',mock_transport=submit,inventory_mock_client=c)
  self.assertEqual(calls,['LONG'])
  self.assertEqual(r['shortRecoverySubmit'],('SUBMITTED_RECONCILE_ONLY','BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY'))
  self.assertNotEqual(h.fixture.snapshot('pair')['state'],'CLOSED')
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')

class PersistedTransportOrigin(unittest.TestCase):
 def test_midpair_pretransport_block_is_persisted_without_retry(self):
  from test_short_recovery_mock_aster_inventory import Client
  c=Client();calls=[]
  def submit(intent):
   calls.append(intent.position_side.value)
   if intent.position_side.value=='LONG':c.qty='0'
   return {'clientOrderId':intent.intent_id,'orderId':intent.position_side.value+'-order'}
  result,_,h=RunUidIntegration().run_case(action_mode='PAIR_EXIT',mock_transport=submit,inventory_mock_client=c)
  self.assertEqual(calls,['LONG'])
  self.assertEqual(result['shortRecoverySubmit'][1],'BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY')
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['offlineTransportOrigin'],'BEFORE_TRANSPORT_BLOCKED')
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')
  h.fixture.db=h.fixture.db.restart();h.fixture.bind()
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['offlineTransportOrigin'],'BEFORE_TRANSPORT_BLOCKED')
 def test_true_timeout_persists_different_origin(self):
  m=MagicMock(side_effect=TimeoutError('uncertain mock network'))
  r,_,h=RunUidIntegration().run_case(action_mode='REDUCE',mock_transport=m)
  self.assertEqual(r['shortRecoverySubmit'],('UNKNOWN_RECONCILE_ONLY',))
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['offlineTransportOrigin'],'TRANSPORT_OUTCOME_UNKNOWN')

class RestartOriginClassification(unittest.TestCase):
 def test_blocked_and_unknown_classified_after_restart_without_post(self):
  from short_recovery_order_claim_shadow import classify_locked_mock_claim
  for timeout in (False,True):
   calls=[]
   def submit(intent):
    calls.append(intent.intent_id)
    if timeout:raise TimeoutError('uncertain')
    return {'orderId':'mock'}
   if timeout:
    _,_,h=RunUidIntegration().run_case(action_mode='REDUCE',mock_transport=submit)
   else:
    from test_short_recovery_mock_aster_inventory import Client
    c=Client();c.qty='0'
    _,_,h=RunUidIntegration().run_case(action_mode='REDUCE',mock_transport=submit,inventory_mock_client=c)
   before=len(calls)
   h.fixture.db=h.fixture.db.restart();h.fixture.bind()
   row=h.fixture.snapshot('SHORTclaim')
   outcome=classify_locked_mock_claim(db=h.fixture.db,transactional=__import__('short_recovery_multidoc_mock').transactional,claim_ref=h.fixture.refs['SHORTclaim'],account='u',symbol='XRPUSDT',cycle='c',intent_id=row['intentId'])
   self.assertEqual(outcome,'UNKNOWN_EXCHANGE_READBACK_REQUIRED' if timeout else 'PRETRANSPORT_BLOCKED_NO_RETRY')
   self.assertEqual(len(calls),before)
   self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')

class InRunUidRestartReadback(unittest.TestCase):
 def test_locked_short_no_order_remains_unresolved_and_no_post(self):
  class Client:
   offline_mock_only=True
   def query_order(self,*args):return None
  m=MagicMock()
  result,_,h=RunUidIntegration().run_case(action_mode='REDUCE',existing_short_state='SUBMITTING',mock_transport=m,restart_readback_mock_client=Client())
  self.assertEqual(result['shortRecoveryRestartReadback'],'NO_ORDER_UNPROVEN_CLAIM_LOCKED')
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')
  m.assert_not_called()

class InRunUidLateAck(unittest.TestCase):
 def test_late_ack_only_after_restart_no_second_post(self):
  class MockExchange:
   offline_mock_only=True
   def query_order(self,symbol,cid):
    return {'symbol':symbol,'clientOrderId':cid,'orderId':'SHORT-order','status':'NEW','executedQty':'0'}
   def user_trades(self,symbol,**kwargs):return []
  submit=MagicMock()
  r,_,h=RunUidIntegration().run_case(action_mode='REDUCE',existing_short_state='SUBMITTING',mock_transport=submit,restart_readback_mock_client=MockExchange())
  self.assertEqual(r['shortRecoveryRestartReadback'],'LATE_ACK_READBACK_ONLY')
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'ACKED')
  self.assertNotEqual(h.fixture.snapshot('pair')['state'],'CLOSED')
  submit.assert_not_called()

class RecoveredFinancialEvidenceGate(unittest.TestCase):
 def test_recovered_partial_readback_cannot_settle_without_funding_evidence(self):
  class Client:
   offline_mock_only=True
   def query_order(self,symbol,cid):
    return {'symbol':symbol,'clientOrderId':cid,'orderId':'SHORT-order','status':'PARTIALLY_FILLED','executedQty':'25'}
   def user_trades(self,symbol,**kw):
    return [{'id':1,'symbol':symbol,'orderId':'SHORT-order','qty':'25','realizedPnl':'1','commission':'.1'}]
  mock=MagicMock()
  r,_,h=RunUidIntegration().run_case(action_mode='REDUCE',existing_short_state='SUBMITTING',mock_transport=mock,proof=False,restart_readback_mock_client=Client())
  self.assertEqual(r['shortRecoveryRestartReadback'],'PARTIAL_FILLS_NEED_FINANCIAL_PROOF')
  self.assertEqual(r['shortRecoveryPairSettlement'],'BLOCKED_RECOVERED_FILL_FINANCIAL_PROOF')
  self.assertEqual(h.fixture.snapshot('pair')['state'],'OPEN')
  mock.assert_not_called()

class PhasedRecoveredPairLifecycle(unittest.TestCase):
 def test_partial_then_terminal_using_same_firestore_ledger_and_run_uid(self):
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  short=h.fixture.snapshot('SHORTclaim');short.update(state='SUBMITTING',offlineTransportOrigin='TRANSPORT_OUTCOME_UNKNOWN',positionSide='SHORT');h.fixture.put('SHORTclaim',short)
  class RestartClient:
   offline_mock_only=True
   def __init__(self):self.status='PARTIALLY_FILLED';self.qty='25'
   def query_order(self,symbol,cid):return {'symbol':symbol,'clientOrderId':cid,'orderId':'SHORT-order','status':self.status,'executedQty':self.qty}
   def user_trades(self,symbol,**kw):
    rows=[{'id':12,'symbol':symbol,'orderId':'SHORT-order','qty':'25','realizedPnl':'1','commission':'.1'}]
    if self.status=='FILLED':rows.append({'id':13,'symbol':symbol,'orderId':'SHORT-order','qty':'50','realizedPnl':'2','commission':'.2'})
    return rows
  exchange=RestartClient()
  h.client.query_order=lambda sym,cid: exchange.query_order(sym,cid) if cid==short['intentId'] else {'symbol':sym,'clientOrderId':cid,'orderId':'LONG-order','status':'FILLED','executedQty':'100'}
  h.client.user_trades=lambda sym,**kw: [{'id':11,'symbol':sym,'orderId':'LONG-order','qty':'100','realizedPnl':'1','commission':'.1'}]+exchange.user_trades(sym,**kw)
  h.proof['SHORT']['orderStatus']='PARTIALLY_FILLED';h.proof['SHORT']['executedQty']='25';h.proof['SHORT']['terminalVerified']=False
  h.fixture.db=h.fixture.db.restart();h.fixture.bind()
  first,_,h=RunUidIntegration().run_case(existing_harness=h,restart_readback_mock_client=exchange)
  self.assertEqual(first['shortRecoveryRestartReadback'],'PARTIAL_FILLS_NEED_FINANCIAL_PROOF')
  self.assertEqual(first['shortRecoveryPairSettlement'],'PAIR_RECONCILE_REQUIRED')
  from short_recovery_firestore_mock import decode
  self.assertEqual(decode(h.fixture.snapshot('SHORTledger')).allocations[0].remaining,50)
  self.assertNotEqual(h.fixture.snapshot('pair')['state'],'CLOSED')
  exchange.status='FILLED';exchange.qty='75'
  h.proof['SHORT'].update(orderStatus='FILLED',executedQty='75',terminalVerified=True)
  h.proof['SHORT']['executions']['13']={'funding':'-.02','fundingOwnershipVerified':True,'financialVerified':True}
  h.fixture.db=h.fixture.db.restart();h.fixture.bind()
  partial_claim=h.fixture.snapshot('SHORTclaim');partial_ledger=h.fixture.snapshot('SHORTledger')
  h.proof['SHORT']['executions']['12']['funding']='-.99'
  tampered,_,h=RunUidIntegration().run_case(existing_harness=h)
  self.assertIn(tampered['shortRecoveryPairSettlement'],('BLOCKED_FINANCIAL_REPLAY_PROVENANCE','BLOCKED_FINANCIAL_REPLAY_MISMATCH'))
  self.assertEqual(h.fixture.snapshot('SHORTclaim'),partial_claim)
  self.assertEqual(h.fixture.snapshot('SHORTledger'),partial_ledger)
  h.proof['SHORT']['executions']['12']['funding']='-.05'
  second,_,h=RunUidIntegration().run_case(existing_harness=h)
  self.assertEqual(second['shortRecoveryPairSettlement'],'PAIR_CLOSED_VERIFIED',repr((h.fixture.snapshot('SHORTclaim'),h.fixture.snapshot('LONGclaim'))))
  self.assertEqual(decode(h.fixture.snapshot('SHORTledger')).allocations[0].remaining,0)
  self.assertEqual(h.fixture.snapshot('pair')['state'],'CLOSED')
  self.assertNotIn('shortRecoverySubmit',second)
  closed_snapshot=(h.fixture.snapshot('SHORTclaim'),h.fixture.snapshot('SHORTledger'),h.fixture.snapshot('pair'))
  h.fixture.db=h.fixture.db.restart();h.fixture.bind()
  replay,_,h=RunUidIntegration().run_case(existing_harness=h)
  self.assertEqual(replay['shortRecoveryPairSettlement'],'ALREADY_PAIR_CLOSED')
  self.assertEqual((h.fixture.snapshot('SHORTclaim'),h.fixture.snapshot('SHORTledger'),h.fixture.snapshot('pair')),closed_snapshot)

class RehedgeFinalityGate(unittest.TestCase):
 def test_zero_short_without_proven_terminal_order_never_submits(self):
  mock=MagicMock()
  r,_,h=RunUidIntegration().run_case(action_mode='REHEDGE',mock_transport=mock,rehedge_final_readback=None)
  self.assertEqual(r['shortRecoveryAction']['status'],'BLOCKED_REHEDGE_FINAL_READBACK')
  self.assertNotIn('shortRecoverySubmit',r)
  mock.assert_not_called()
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'RESERVED')
