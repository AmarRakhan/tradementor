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
 def run_case(self, *, enabled=True, ownership=True, force_shadow=True, execution_enabled=False, mock_scope=True, proof=True, action_mode=None, emergency_stop=False, mock_transport=None, readback_mode=None, existing_short_state=None, inventory_readback='fixture', inventory_mock_client=None, restart_readback_mock_client=None, existing_harness=None, rehedge_final_readback="fixture", final_short_close_claim_ref=None, require_independent_funding_mock=False, funding_window_mock=None, authorization_mode="LEGACY_MOCK_TEST", reduction_step=1, reduction_mark=None, confirmed_closed=None, initialize_action_claim=True):
  h=existing_harness or VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement')
  if existing_harness is None:h.setUp()
  if inventory_readback=='fixture':
   inventory_readback={'account':'u','symbol':'XRPUSDT','verified':True,'hedgeMode':True,'openOrders':[],'timestampMs':9999,'LONG':'100','SHORT':'0' if action_mode=='REHEDGE' else '100'}
  ctx={'client':h.client,'claim_refs':{s:h.fixture.refs[s+'claim'] for s in ('LONG','SHORT')},'ledger_refs':{s:h.fixture.refs[s+'ledger'] for s in ('LONG','SHORT')},'control_ref':h.fixture.refs['control'],'pair_ref':h.fixture.refs['pair'],'db':h.fixture.db,'transactional':__import__('short_recovery_multidoc_mock').transactional,'account':'u' if mock_scope else 'other','symbol':'XRPUSDT','cycle':'c','mock_only':True,'financial_proof':h.proof if proof else None,'restart_readback_mock_client':restart_readback_mock_client,'authorization_mode':authorization_mode,'require_independent_funding_mock':require_independent_funding_mock,'funding_window_mock':funding_window_mock}
  if action_mode is not None:
   from decimal import Decimal as D
   from short_recovery_contract import Plan
   from short_recovery_reduction import ReductionState
   plan=Plan(D(2),D(100),D(5),4)
   closed=D(confirmed_closed) if confirmed_closed is not None else (D(100) if action_mode=='REHEDGE' else D(0))
   qty=D(0) if action_mode=='REHEDGE' else D(100)
   state=ReductionState(plan,closed,D(reduction_mark if reduction_mark is not None else ('1.6' if action_mode=='REHEDGE' else '1.9')))
   from short_recovery_order_claim_shadow import canonical_intent_id
   ids={key:canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side=key.split('_')[0],action=key.split('_')[1],step=reduction_step) for key in ('LONG_CLOSE','SHORT_CLOSE','SHORT_OPEN')}
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
   ctx['recovery_action']={'final_short_close_claim_ref':final_short_close_claim_ref,'rehedge_final_readback':rehedge_final_readback,'state':state,'short_qty':qty,'long_qty':D(100),
       'net_exit_due':action_mode=='PAIR_EXIT','net_evidence_verified':proof,
       'claim_ref':h.fixture.refs['SHORTclaim'],'intent_id':ids['SHORT_OPEN' if action_mode=='REHEDGE' else 'SHORT_CLOSE'],'step':reduction_step,
       'account_close_guard':lambda:None,'intent_ids':ids, 'submit_mock':mock_transport, 'offline_mock_confirmed':mock_transport is not None,'inventory_now_ms':10000,'inventory_readback':inventory_readback,'inventory_mock_client':inventory_mock_client}
   if initialize_action_claim:h.fixture.put('SHORTclaim',{**(h.fixture.snapshot('SHORTclaim') or {'account':'u','symbol':'XRPUSDT','cycle':'c','positionSide':'SHORT'}),'state':'RESERVED','intentId':ctx['recovery_action']['intent_id'],'side':'SHORT','action':'OPEN' if action_mode=='REHEDGE' else 'CLOSE','step':reduction_step})
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

class PositiveCanonicalRehedge(unittest.TestCase):
 def test_separate_final_close_claim_and_fresh_mock_aster_inventory(self):
  from test_short_recovery_rehedge_readback_offline import RehedgeReadback
  from unittest.mock import MagicMock
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  class Client:
   offline_mock_only=True
   def account_information(self):return {'account':'u','hedgeMode':True}
   def position_risk(self,s):return [{'symbol':s,'positionSide':'LONG','positionAmt':'100'},{'symbol':s,'positionSide':'SHORT','positionAmt':'0'}]
   def open_orders(self,s):return []
   def query_order(self,s,c):return {'symbol':s,'clientOrderId':c,'orderId':'SHORT-order','status':'FILLED','executedQty':'75'}
   def user_trades(self,s,**kw):return [{'symbol':s,'orderId':'SHORT-order','id':12,'qty':'75','realizedPnl':'1','commission':'.1'}]
  final_ref=h.fixture.refs['SHORTclaim']
  final=h.fixture.snapshot('SHORTclaim');final.update(side='SHORT',action='CLOSE',state='CLOSED',executedQty='75')
  h.fixture.put('SHORTclaim',final)
  # Distinct canonical claim: the new OPEN must not overwrite the prior CLOSE.
  from short_recovery_multidoc_mock import Ref
  open_ref=Ref(h.fixture.db,'SHORT_OPEN_claim')
  h.fixture.refs['SHORTclaim']=open_ref
  h.fixture.put('SHORTclaim',dict(final,state='RESERVED',action='OPEN',intentId='placeholder'))
  transport=MagicMock(return_value={'orderId':'mock-open'})
  r,_,h=RunUidIntegration().run_case(action_mode='REHEDGE',existing_harness=h,
      final_short_close_claim_ref=final_ref,inventory_mock_client=Client(),mock_transport=transport)
  self.assertEqual(r['shortRecoverySubmit'],('SUBMITTED_RECONCILE_ONLY',),repr((transport.call_args_list,h.fixture.snapshot('SHORTclaim'),r.get('shortRecoveryAction'))))
  transport.assert_called_once()

class FourStepRunUidCycle(unittest.TestCase):
 def test_all_four_run_uid_reductions_confirmed_before_next_step(self):
  from decimal import Decimal as D
  from short_recovery_ledger import Ledger,Allocation,Fill
  from short_recovery_firestore_mock import encode,decode
  from short_recovery_multidoc_mock import Ref
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  h.fixture.put('SHORTledger',encode(Ledger('u','XRPUSDT',(Allocation('SHORT','c',D(100)),))))
  class Exchange:
   offline_mock_only=True
   def __init__(self):self.short=D(100);self.orders=[];self.fills=[]
   def account_information(self):return {'account':'u','hedgeMode':True}
   def position_risk(self,s):return [{'symbol':s,'positionSide':'LONG','positionAmt':'100'},{'symbol':s,'positionSide':'SHORT','positionAmt':str(self.short)}]
   def open_orders(self,s):return self.orders
   def query_order(self,s,c):return {'symbol':s,'clientOrderId':c,'orderId':'close-final','status':'FILLED','executedQty':'25'}
   def user_trades(self,s,**kw):return [{'symbol':s,'orderId':'close-final','id':4,'qty':'25','realizedPnl':'1','commission':'.1'}]
  exchange=Exchange();posts=[];last_close_ref=None
  from short_recovery_multidoc_mock import Ref
  marker_ref=Ref(h.fixture.db,('u','XRPUSDT','marker'))
  owner_ref=Ref(h.fixture.db,('u','XRPUSDT','owner'))
  h.fixture.db.commit(marker_ref.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  h.fixture.db.commit(owner_ref.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'})
  for step,mark in enumerate(('1.90','1.80','1.70','1.60'),1):
   ref=Ref(h.fixture.db,('u','XRPUSDT','short-close-'+str(step)))
   h.fixture.refs['SHORTclaim']=ref
   def post(intent):posts.append((step,intent.quantity,intent.action));return {'clientOrderId':intent.intent_id,'orderId':'close-'+str(step)}
   r,_,h=RunUidIntegration().run_case(action_mode='REDUCE',existing_harness=h,
      reduction_step=step,reduction_mark=mark,confirmed_closed=D(25*(step-1)),
      mock_transport=post,inventory_mock_client=exchange,
      inventory_readback={'account':'u','symbol':'XRPUSDT','verified':True,'hedgeMode':True,'openOrders':[],'timestampMs':10000,'LONG':'100','SHORT':str(exchange.short)})
   self.assertEqual(r['shortRecoverySubmit'],('SUBMITTED_RECONCILE_ONLY',),repr(r.get('shortRecoveryAction')))
   self.assertEqual(posts[-1],(step,D(25),'CLOSE'))
   self.assertEqual(len(posts),step)
   # Replay of the same canonical claim is never a second order right.
   from short_recovery_order_claim_shadow import submit_once_offline
   from aster_gateway import AsterOrderIntent,PositionSide
   from short_recovery_multidoc_mock import transactional
   claim=h.fixture.snapshot('SHORTclaim')
   replay=submit_once_offline(db=h.fixture.db,transactional=transactional,claim_ref=ref,
      control_ref=h.fixture.refs['control'],account='u',symbol='XRPUSDT',cycle='c',
      intent=AsterOrderIntent(claim['intentId'],'XRPUSDT',PositionSide.SHORT,D(25),'CLOSE'),
      account_close_guard=lambda:None,submit_mock=post)
   self.assertEqual(replay,'BLOCKED_CLAIM_NOT_RESERVED')
   self.assertEqual(len(posts),step)
   # Independent mock exchange GETs feed the existing transactional resolver.
   from short_recovery_aster_readback_mock_adapter import inspect
   from short_recovery_order_resolution_shadow import resolve
   from short_recovery_multidoc_mock import transactional
   order_id='close-'+str(step)
   exchange.query_order=lambda symbol,cid:{'symbol':symbol,'clientOrderId':cid,'orderId':order_id,'status':'FILLED','executedQty':'25'}
   exchange.user_trades=lambda symbol,**kw:[{'symbol':symbol,'orderId':order_id,'id':step,'qty':'25','realizedPnl':'1','commission':'.1'}]
   readback=inspect(exchange,symbol='XRPUSDT',client_order_id=claim['intentId'])
   self.assertEqual(readback['status'],'READBACK_PREVIEW')
   self.assertEqual(readback['orderStatus'],'FILLED')
   self.assertEqual(len(readback['fills']),1)
   f=readback['fills'][0]
   self.assertEqual(f['quantity'],D(25))
   def settle(event,evidence=None,execution_id=None,quantity=None):
    return resolve(db=h.fixture.db,transactional=transactional,
       claim_ref=ref,ledger_ref=h.fixture.refs['SHORTledger'],
       marker_ref=marker_ref,owner_ref=owner_ref,account='u',symbol='XRPUSDT',cycle='c',
       intent_id=claim['intentId'],event=event,evidence=evidence,
       execution_id=execution_id,quantity=quantity)
   self.assertEqual(settle('LATE_ACK',{'confirmed':True,'orderId':order_id}),'ACKED_RECOVERED')
   proof={'confirmed':True,'readbackVerified':True,'orderId':order_id,
       'executionId':f['executionId'],'quantity':str(f['quantity']),
       'realizedPnl':str(f['realizedPnl']),'commission':str(f['fee']),'funding':'-.05',
       'fundingOwnershipVerified':True,'financialVerified':True}
   self.assertEqual(settle('FILL',proof,f['executionId'],f['quantity']),'FILL_APPLIED')
   self.assertEqual(settle('FILL',proof,f['executionId'],f['quantity']),'ALREADY_APPLIED' if step<4 else 'ALREADY_TERMINAL')
   exchange.short-=D(25)
   self.assertEqual(decode(h.fixture.snapshot('SHORTledger')).allocations[0].remaining,exchange.short)
   self.assertEqual(h.fixture.snapshot('SHORTclaim')['executedQty'],'25')
   self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'CLOSED' if step==4 else 'PARTIAL')
   last_close_ref=ref
  self.assertEqual(exchange.short,D(0))
  # The new 1:1 opening is distinct from all four prior close claims.
  exchange.query_order=lambda s,c:{'symbol':s,'clientOrderId':c,'orderId':'close-4','status':'FILLED','executedQty':'25'}
  exchange.user_trades=lambda s,**kw:[{'symbol':s,'orderId':'close-4','id':4,'qty':'25','realizedPnl':'1','commission':'.1'}]
  h.fixture.refs['SHORTclaim']=Ref(h.fixture.db,('u','XRPUSDT','short-open-cycle-2'))
  def open_post(intent):posts.append(('open',intent.quantity,intent.action));return {'orderId':'mock-rehedge'}
  r,_,h=RunUidIntegration().run_case(action_mode='REHEDGE',existing_harness=h,
     final_short_close_claim_ref=last_close_ref,inventory_mock_client=exchange,
     mock_transport=open_post)
  self.assertEqual(r['shortRecoverySubmit'],('SUBMITTED_RECONCILE_ONLY',))
  self.assertEqual(posts[-1],('open',D(100),'OPEN'))
  self.assertEqual(len(posts),5)
  # Restart after the OPEN submit: the persisted canonical claim has no
  # replacement submit right, while the final CLOSE claim stays CLOSED.
  open_claim_key=h.fixture.refs['SHORTclaim'].key
  h.fixture.db=h.fixture.db.restart();h.fixture.bind()
  h.fixture.refs['SHORTclaim']=Ref(h.fixture.db,open_claim_key)
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')
  self.assertEqual(Ref(h.fixture.db,last_close_ref.key).get(transaction=h.fixture.db.transaction()).to_dict()['state'],'CLOSED')
  rerun,_,h=RunUidIntegration().run_case(action_mode='REHEDGE',existing_harness=h,
      initialize_action_claim=False,final_short_close_claim_ref=Ref(h.fixture.db,last_close_ref.key),
      inventory_mock_client=exchange,mock_transport=open_post)
  self.assertNotIn(('SUBMITTED_RECONCILE_ONLY',),[rerun.get('shortRecoverySubmit')])
  self.assertEqual(len(posts),5)

  # Four canonical mock CLOSE claims and the separate OPEN claim do not
  # establish exchange funding provenance or authorize pair net TP.
  from short_recovery_funding_provenance_decision import decide, NO_GO
  self.assertEqual(decide(account='u',symbol='XRPUSDT',cycle='c',
      financial_proof={'incomeHistoryComplete':True,'ownershipVerified':True}),NO_GO)
  self.assertNotEqual(r.get('shortRecoveryPairSettlement'),'PAIR_CLOSED_VERIFIED')

class Build66RecoverySafety(unittest.TestCase):
 def test_two_workers_one_canonical_mock_post_and_stop(self):
  import concurrent.futures,threading
  from decimal import Decimal as D
  from short_recovery_order_claim_shadow import submit_once_offline,canonical_intent_id
  from short_recovery_multidoc_mock import transactional
  from aster_gateway import AsterOrderIntent,PositionSide
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  ref=h.fixture.refs['SHORTclaim'];ident=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
  claim=h.fixture.snapshot('SHORTclaim');claim.update(intentId=ident,state='RESERVED',side='SHORT',action='CLOSE',step=1);h.fixture.put('SHORTclaim',claim)
  intent=AsterOrderIntent(ident,'XRPUSDT',PositionSide.SHORT,D(25),'CLOSE')
  barrier=threading.Barrier(2);sent=[];guard=threading.Lock()
  def transport(i):
   with guard:sent.append(i.intent_id)
  def work():
   barrier.wait(timeout=10)
   return submit_once_offline(db=h.fixture.db,transactional=transactional,claim_ref=ref,control_ref=h.fixture.refs['control'],account='u',symbol='XRPUSDT',cycle='c',intent=intent,account_close_guard=lambda:None,submit_mock=transport)
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   results=[f.result(timeout=20) for f in [pool.submit(work) for _ in range(2)]]
  self.assertCountEqual(results,['SUBMITTED_RECONCILE_ONLY','BLOCKED_CLAIM_NOT_RESERVED'])
  self.assertEqual(sent,[ident])
  h.fixture.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  self.assertEqual(submit_once_offline(db=h.fixture.db,transactional=transactional,claim_ref=ref,control_ref=h.fixture.refs['control'],account='u',symbol='XRPUSDT',cycle='c',intent=intent,account_close_guard=lambda:None,submit_mock=transport),'BLOCKED_CLAIM_NOT_RESERVED')
  self.assertEqual(len(sent),1)
 def test_partial_funding_and_legacy_claim_guard(self):
  from decimal import Decimal as D
  from short_recovery_multidoc_mock import Ref,transactional
  from short_recovery_order_resolution_shadow import resolve
  from short_recovery_ledger import Ledger,Allocation
  from short_recovery_firestore_mock import encode,decode
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  f=h.fixture;f.put('SHORTledger',encode(Ledger('u','XRPUSDT',(Allocation('SHORT','c',D(100)),))))
  marker=Ref(f.db,'build66-marker');owner=Ref(f.db,'build66-owner')
  f.db.commit(marker.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  f.db.commit(owner.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'})
  claim=f.snapshot('SHORTclaim');claim.update(state='ACKED',side='SHORT',action='CLOSE');f.put('SHORTclaim',claim)
  def apply(execution,qty,evidence):
   return resolve(db=f.db,transactional=transactional,claim_ref=f.refs['SHORTclaim'],ledger_ref=f.refs['SHORTledger'],marker_ref=marker,owner_ref=owner,account='u',symbol='XRPUSDT',cycle='c',intent_id=claim['intentId'],event='FILL',execution_id=execution,quantity=qty,evidence=evidence)
  evidence={'confirmed':True,'readbackVerified':True,'orderId':'SHORT-order','executionId':'ex1','quantity':'25','realizedPnl':'1','commission':'.1','funding':'-.05'}
  self.assertEqual(apply('ex1',25,{k:v for k,v in evidence.items() if k!='funding'}),'BLOCKED_FINANCIAL_EVIDENCE')
  self.assertEqual(apply('ex1',25,evidence),'FILL_APPLIED')
  self.assertEqual(f.snapshot('SHORTclaim')['executedQty'],'25')
  self.assertEqual(apply('ex1',25,evidence),'ALREADY_APPLIED')
  follow={**evidence,'executionId':'ex2','quantity':'10'}
  self.assertEqual(apply('ex2',10,follow),'FILL_APPLIED')
  self.assertEqual(f.snapshot('SHORTclaim')['executedQty'],'35')
  self.assertEqual(decode(f.snapshot('SHORTledger')).allocations[0].remaining,D(65))

class Build67LegacyPartialGuard(unittest.TestCase):
 def test_legacy_partial_claim_without_cumulative_qty_blocks_new_fill(self):
  from short_recovery_order_resolution_shadow import resolve
  from short_recovery_multidoc_mock import Ref,transactional
  from short_recovery_ledger import Ledger,Allocation
  from short_recovery_firestore_mock import encode
  from decimal import Decimal as D
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp();f=h.fixture
  claim=f.snapshot('SHORTclaim');claim.update(state='PARTIAL');claim.pop('executedQty',None);f.put('SHORTclaim',claim)
  marker=Ref(f.db,'build67-marker');owner=Ref(f.db,'build67-owner')
  f.db.commit(marker.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  f.db.commit(owner.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'})
  evidence={'confirmed':True,'readbackVerified':True,'orderId':'SHORT-order','executionId':'new','quantity':'10','realizedPnl':'1','commission':'.1','funding':'-.05'}
  before=f.snapshot('SHORTledger')
  outcome=resolve(db=f.db,transactional=transactional,claim_ref=f.refs['SHORTclaim'],ledger_ref=f.refs['SHORTledger'],marker_ref=marker,owner_ref=owner,account='u',symbol='XRPUSDT',cycle='c',intent_id=claim['intentId'],event='FILL',evidence=evidence,execution_id='new',quantity=D(10))
  self.assertEqual(outcome,'BLOCKED_LEGACY_EXECUTED_QTY_UNVERIFIED')
  self.assertEqual(f.snapshot('SHORTledger'),before)

class Build68ConcurrentRunUid(unittest.TestCase):
 def test_two_complete_offline_run_uid_calls_share_one_submit_right(self):
  import concurrent.futures,threading
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  RunUidIntegration().run_case(action_mode='REDUCE',existing_harness=h)
  barrier=threading.Barrier(2);calls=[];lock=threading.Lock()
  def submit(intent):
   with lock:calls.append(intent.intent_id)
   return {'orderId':'mock-short-close'}
  def worker():
   barrier.wait(timeout=10)
   result,_,_=RunUidIntegration().run_case(action_mode='REDUCE',existing_harness=h,
       initialize_action_claim=False,mock_transport=submit)
   return result.get('shortRecoverySubmit')
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   output=[f.result(timeout=20) for f in [pool.submit(worker) for _ in range(2)]]
  self.assertEqual(output.count(('SUBMITTED_RECONCILE_ONLY',)),1)
  self.assertTrue(all(x in (('SUBMITTED_RECONCILE_ONLY',),('BLOCKED_CLAIM_NOT_RESERVED',),None) for x in output))
  self.assertEqual(len(calls),1)
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')
