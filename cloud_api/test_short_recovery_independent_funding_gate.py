"""Offline integration: independent funding cannot be inferred from mock flags."""
import unittest
from short_recovery_independent_funding_gate import inspect_mock_coverage
from test_short_recovery_run_uid_integration import RunUidIntegration

class IndependentFundingGate(unittest.TestCase):
 def test_incomplete_income_or_full_page_cannot_settle_pair_or_erase_partial(self):
  class MockAster:
   offline_mock_only=True
   def __init__(self):self.rows=[];self.calls=[]
   def income_history(self,**kw):self.calls.append(kw);return self.rows
  from test_short_recovery_pair_aster_bridge import VerifiedAsterBridge
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  client=MockAster();h.client.offline_mock_only=True
  h.client.income_history=client.income_history
  previous_pair=h.fixture.snapshot('pair')
  previous_ledger=h.fixture.snapshot('SHORTledger')
  def run():
   return RunUidIntegration().run_case(existing_harness=h,require_independent_funding_mock=True,funding_window_mock={'startMs':1000,'endMs':2000})[0]
  report=run()
  self.assertEqual(report['shortRecoveryPairSettlement'],'BLOCKED_INDEPENDENT_FUNDING_COMPLETENESS')
  self.assertEqual(h.fixture.snapshot('pair'),previous_pair)
  self.assertEqual(h.fixture.snapshot('SHORTledger'),previous_ledger)
  self.assertEqual(report['ordersSent'],0)
  self.assertTrue(client.calls)
  # Aster can return a full page without a reliable tie-breaking cursor.
  client.rows=[{'tranId':i,'symbol':'XRPUSDT','incomeType':'FUNDING_FEE','time':1000,'income':'-0.01'} for i in range(1000)]
  self.assertEqual(run()['shortRecoveryPairSettlement'],'BLOCKED_INCOME_READBACK_INCOMPLETE')
  self.assertEqual(h.fixture.snapshot('pair'),previous_pair)
  self.assertEqual(h.fixture.snapshot('SHORTledger'),previous_ledger)
  self.assertEqual(inspect_mock_coverage(client=object(),account='u',symbol='XRPUSDT',cycle='c',start_ms=1000,end_ms=2000),'BLOCKED_INDEPENDENT_FUNDING_CLIENT_OR_CYCLE')

 def test_forged_financial_proof_and_disabled_flag_do_not_bypass_strict_window(self):
  from test_short_recovery_pair_aster_bridge import VerifiedAsterBridge
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  class Client:
   offline_mock_only=True
   def income_history(self,**kwargs):return []
  h.client.offline_mock_only=True
  h.client.income_history=Client().income_history
  pair=h.fixture.snapshot('pair');long_ledger=h.fixture.snapshot('LONGledger');short_ledger=h.fixture.snapshot('SHORTledger')
  # The legacy financial_proof fixture reports all flags True. It cannot
  # override a strict income window, including on restart and late ACK paths.
  for state in ('ACKED','UNKNOWN'):
   row=h.fixture.snapshot('SHORTclaim');row['state']=state;h.fixture.put('SHORTclaim',row)
   r,_,_=RunUidIntegration().run_case(existing_harness=h,
     require_independent_funding_mock=False,
     funding_window_mock={'startMs':1000,'endMs':2000})
   self.assertEqual(r['shortRecoveryPairSettlement'],'BLOCKED_INDEPENDENT_FUNDING_COMPLETENESS')
   self.assertEqual(h.fixture.snapshot('pair'),pair)
   self.assertEqual(h.fixture.snapshot('LONGledger'),long_ledger)
   self.assertEqual(h.fixture.snapshot('SHORTledger'),short_ledger)
   self.assertNotIn('shortRecoverySubmit',r)

 def test_future_authorization_cannot_use_legacy_forged_proof(self):
  from test_short_recovery_pair_aster_bridge import VerifiedAsterBridge
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  pair=h.fixture.snapshot('pair');ledger=h.fixture.snapshot('SHORTledger')
  report,_,_=RunUidIntegration().run_case(existing_harness=h,authorization_mode='AUTHORIZED_EXECUTOR')
  self.assertEqual(report['shortRecoveryAuthorization'],'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION')
  self.assertEqual(report['shortRecoveryPairSettlement'],'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION')
  self.assertEqual(h.fixture.snapshot('pair'),pair)
  self.assertEqual(h.fixture.snapshot('SHORTledger'),ledger)
  self.assertNotIn('shortRecoverySubmit',report)

class Build77UnstableFundingReadback(unittest.TestCase):
 def test_partial_restart_income_drift_cannot_authorize_pair(self):
  from test_short_recovery_pair_aster_bridge import VerifiedAsterBridge
  from short_recovery_funding_shadow import read_bounded_symbol_funding,reconcile_bounded_income_snapshots
  from short_recovery_firestore_mock import decode
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  claim=h.fixture.snapshot('SHORTclaim');claim['state']='UNKNOWN';h.fixture.put('SHORTclaim',claim)
  before=h.fixture.snapshot('SHORTledger');pair=h.fixture.snapshot('pair')
  class Exchange:
   offline_mock_only=True
   def __init__(self):self.amount='-.1'
   def income_history(self,**kw):return [{'symbol':'XRPUSDT','incomeType':'FUNDING_FEE','time':1000,'tranId':'t1','income':self.amount}]
  exchange=Exchange();h.client.offline_mock_only=True;h.client.income_history=exchange.income_history
  initial=read_bounded_symbol_funding(exchange,symbol='XRPUSDT',account='u',start_ms=1000,end_ms=2000)
  exchange.amount='-.2'
  changed=read_bounded_symbol_funding(exchange,symbol='XRPUSDT',account='u',start_ms=1000,end_ms=2000)
  with self.assertRaisesRegex(ValueError,'BLOCKED_INCOME_SNAPSHOT_DRIFT'):
   reconcile_bounded_income_snapshots(initial,changed)
  h.fixture.db=h.fixture.db.restart();h.fixture.bind()
  result,_,_=RunUidIntegration().run_case(existing_harness=h,
    funding_window_mock={'startMs':1000,'endMs':2000})
  self.assertEqual(result['shortRecoveryPairSettlement'],'BLOCKED_INDEPENDENT_FUNDING_COMPLETENESS')
  self.assertEqual(h.fixture.snapshot('pair'),pair)
  self.assertEqual(h.fixture.snapshot('SHORTledger'),before)
  self.assertNotIn('shortRecoverySubmit',result)
