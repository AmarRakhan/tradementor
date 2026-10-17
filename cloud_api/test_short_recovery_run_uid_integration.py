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
 def run_case(self, *, enabled=True, ownership=True, force_shadow=True, execution_enabled=False, mock_scope=True, proof=True, action_mode=None, emergency_stop=False, mock_transport=None):
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  ctx={'client':h.client,'claim_refs':{s:h.fixture.refs[s+'claim'] for s in ('LONG','SHORT')},'ledger_refs':{s:h.fixture.refs[s+'ledger'] for s in ('LONG','SHORT')},'control_ref':h.fixture.refs['control'],'pair_ref':h.fixture.refs['pair'],'db':h.fixture.db,'transactional':__import__('short_recovery_multidoc_mock').transactional,'account':'u' if mock_scope else 'other','symbol':'XRPUSDT','cycle':'c','mock_only':True,'financial_proof':h.proof if proof else None}
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
   ctx['recovery_action']={'state':state,'short_qty':qty,'long_qty':D(100),
       'net_exit_due':action_mode=='PAIR_EXIT','net_evidence_verified':proof,
       'claim_ref':h.fixture.refs['SHORTclaim'],'intent_id':ids['SHORT_OPEN' if action_mode=='REHEDGE' else 'SHORT_CLOSE'],'step':1,
       'account_close_guard':lambda:None,'intent_ids':ids, 'submit_mock':mock_transport, 'offline_mock_confirmed':mock_transport is not None}
   h.fixture.put('SHORTclaim',{**h.fixture.snapshot('SHORTclaim'),'state':'RESERVED','intentId':ctx['recovery_action']['intent_id'],'side':'SHORT','action':'OPEN' if action_mode=='REHEDGE' else 'CLOSE','step':1})
   if emergency_stop:h.fixture.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
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
 def test_rehedge_atomic_submit_and_mock_transport(self):
  mock=MagicMock(return_value=({'orderId':123},False))
  r,_,h=RunUidIntegration().run_case(action_mode='REHEDGE',mock_transport=mock)
  self.assertEqual(r['shortRecoverySubmit'],('SUBMITTED_RECONCILE_ONLY',))
  self.assertEqual(mock.call_count,1)
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
