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
