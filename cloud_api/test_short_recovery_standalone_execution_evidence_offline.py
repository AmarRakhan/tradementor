import unittest
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_standalone_execution_evidence_offline import (
    inspect_terminal_short_close_offline as check)


class OfflineExecutionEvidence(unittest.TestCase):
    def setUp(self):
        self.intent = canonical_intent_id(account='u', symbol='XRPUSDT',
            cycle='c', side='SHORT', action='CLOSE', step=1)
        self.claim = {'account':'u','symbol':'XRPUSDT','cycle':'c',
            'intentId':self.intent,'side':'SHORT','action':'CLOSE',
            'step':1,'state':'PARTIAL','orderId':'order-1'}
        self.client = FakeClient(self.intent)
    def read(self, **changes):
        kwargs = dict(client=self.client, account='u', symbol='XRPUSDT',
            cycle='c', step=1, claim=self.claim, expected_quantity='25')
        kwargs.update(changes)
        return check(**kwargs)
    def test_filled_order_is_not_financial_settlement(self):
        r=self.read()
        self.assertEqual(r['status'],'ORDER_EXECUTION_VERIFIED_UNSETTLED')
        self.assertEqual(r['executedQty'],'25')
        self.assertFalse(r['nextClaimAuthorized'])
        self.assertFalse(r['profitVerified'])
        self.assertEqual(r['fundingStatus'],'UNRECONCILED')
        self.assertEqual(self.client.calls,2)
    def test_partial_order_fail_closed(self):
        self.client.status='PARTIALLY_FILLED'
        self.assertEqual(self.read()['status'],'BLOCKED_NOT_FULLY_FILLED')
    def test_readback_drift_fail_closed(self):
        self.client.drift=True
        self.assertEqual(self.read()['status'],'BLOCKED_READBACK_DRIFT')
    def test_wrong_cycle_or_claim_rejected(self):
        self.assertEqual(self.read(cycle='other')['status'],'BLOCKED_CLAIM_SCOPE')
        self.claim['state']='RESERVED'
        self.assertEqual(self.read()['status'],'BLOCKED_CLAIM_SCOPE')
    def test_offline_only_and_quantity(self):
        self.client.offline_mock_only=False
        self.assertEqual(self.read()['status'],'BLOCKED_OFFLINE_CLIENT')
        self.client.offline_mock_only=True
        self.assertEqual(self.read(expected_quantity='50')['status'],
                         'BLOCKED_EXECUTION_SCOPE_OR_QUANTITY')
    def test_duplicate_and_missing_execution_fail_closed(self):
        self.client.duplicate=True
        self.assertEqual(self.read()['status'],'BLOCKED_DUPLICATE_EXECUTION')


class FakeClient:
    offline_mock_only=True
    def __init__(self,intent):
        self.intent=intent
        self.calls=0
        self.status='FILLED'
        self.drift=False
        self.duplicate=False
    def query_order(self,symbol,intent):
        self.calls+=1
        return {'symbol':symbol,'clientOrderId':intent,'orderId':'order-1',
            'status':self.status,'executedQty':'25'}
    def user_trades(self,symbol,**kwargs):
        qty='24' if self.drift and self.calls>1 else '25'
        row={'id':1,'orderId':'order-1','symbol':symbol,'qty':qty,
             'realizedPnl':'1','commission':'.1'}
        return [row,row.copy()] if self.duplicate else [row]


if __name__=='__main__':
    unittest.main()
