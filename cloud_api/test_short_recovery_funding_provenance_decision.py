import unittest
from short_recovery_funding_provenance_decision import decide, NO_GO
from short_recovery_independent_funding_gate import inspect_mock_coverage

class FundingProvenanceDecision(unittest.TestCase):
 def test_mock_financial_flags_and_enriched_income_rows_cannot_authorize(self):
  for rows in (None, [], [{'tranId':'t1','symbol':'XRPUSDT','incomeType':'FUNDING_FEE','time':1000,'income':'-0.10','orderId':'o','executionId':'e','positionSide':'SHORT','cycleId':'c'}]):
   self.assertEqual(decide(account='u',symbol='XRPUSDT',cycle='c',income_rows=rows,financial_proof={'incomeHistoryComplete':True,'ownershipVerified':True,'fundingOwnershipVerified':True}),NO_GO)
 def test_order_fills_and_owner_inventory_do_not_identify_symbol_income(self):
  # Two cycle histories can have identical exchange order/fill/inventory data,
  # while an income tranId has no authoritative side or cycle reference.
  reads={'query_order':{'orderId':'close-o','status':'FILLED','executedQty':'25'},
    'user_trades':[{'id':1,'orderId':'close-o','qty':'25',
                    'realizedPnl':'1.2','commission':'0.1'}],
    'position_risk':[{'positionSide':'LONG','positionAmt':'100'},
                     {'positionSide':'SHORT','positionAmt':'0'}]}
  symbol_income=[{'tranId':'fund-1','symbol':'XRPUSDT',
                  'incomeType':'FUNDING_FEE','time':1234,'income':'-0.03'}]
  for cycle in ('c','another-cycle'):
   for proof in ({'financialVerified':True,'fundingOwnershipVerified':True,
                  'canonicalExchangeReadbacks':reads},
                 {'financialVerified':True,'fundingOwnershipVerified':True,
                  'ownershipFence':{'exclusive':True,'cycle':cycle}}):
    with self.subTest(cycle=cycle,proof=proof):
     self.assertEqual(decide(account='u',symbol='XRPUSDT',cycle=cycle,
                             income_rows=symbol_income,financial_proof=proof),NO_GO)
 def test_independently_complete_caller_snapshot_still_cannot_allocate_funding(self):
  from unittest.mock import patch
  class Client:offline_mock_only=True
  snapshot={'account':'u','symbol':'XRPUSDT','startMs':1000,'endMs':2000,'complete':True,'independentlyVerified':True,'rows':({'tranId':'t1','income':'-0.1'},)}
  with patch('short_recovery_funding_shadow.read_bounded_symbol_funding',return_value=snapshot):
   # The reader is imported directly into this module: patch at the consumer.
   with patch('short_recovery_independent_funding_gate.read_bounded_symbol_funding',return_value=snapshot):
    self.assertEqual(inspect_mock_coverage(client=Client(),account='u',symbol='XRPUSDT',cycle='c',start_ms=1000,end_ms=2000),NO_GO)
