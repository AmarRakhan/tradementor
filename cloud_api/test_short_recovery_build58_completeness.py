"""Build 58: mocked GET-only Aster completeness adversarial tests."""
import unittest
from short_recovery_readback_completeness_shadow import inspect_completeness


class Client:
    def __init__(self):
        self.order = {'symbol': 'XRPUSDT', 'clientOrderId': 'intent', 'orderId': 7, 'status': 'FILLED', 'executedQty': '2'}
        self.rows = [{'symbol': 'XRPUSDT', 'orderId': 7, 'id': i, 'qty': '1', 'realizedPnl': '0.4', 'commission': '0.1'} for i in (1, 2)]
        self.income = []
        self.calls = []
    def query_order(self, symbol, client_order_id):
        self.calls.append('query_order')
        return self.order
    def user_trades(self, symbol, *, limit, from_id=None):
        self.calls.append('user_trades')
        return [row for row in self.rows if from_id is None or row['id'] >= from_id][:limit]
    def income_history(self, *, symbol, limit):
        self.calls.append('income_history')
        return self.income[:limit]
    def submit_order(self, *args, **kwargs):
        raise AssertionError('live orders forbidden')


class Tests(unittest.TestCase):
    def scan(self, client, **kwargs):
        result = inspect_completeness(client, symbol='XRPUSDT', client_order_id='intent', **kwargs)
        self.assertFalse(result['ledgerSafe'])
        self.assertEqual(result['ordersSent'], 0)
        self.assertNotIn('submit_order', client.calls)
        return result
    def test_complete_two_pages_still_not_funding_proof(self):
        c = Client()
        r = self.scan(c, page_size=1)
        self.assertEqual(r['status'], 'READBACK_SHADOW_UNPROVEN_FUNDING')
        self.assertTrue(r['terminalVerified'])
        self.assertEqual(c.calls.count('user_trades'), 3)
    def test_nonterminal_never_claimed_final(self):
        c = Client(); c.order['status'] = 'PARTIALLY_FILLED'
        self.assertEqual(self.scan(c)['status'], 'BLOCKED_ORDER_NOT_FINAL')
    def test_missing_executions_block(self):
        c = Client(); c.rows.pop()
        self.assertEqual(self.scan(c)['status'], 'BLOCKED_EXECUTION_INCOMPLETE')
    def test_bad_realized_pnl_block(self):
        c = Client(); c.rows[0].pop('realizedPnl')
        self.assertEqual(self.scan(c)['status'], 'BLOCKED_FILL_EVIDENCE')
    def test_bad_commission_block(self):
        c = Client(); c.rows[0]['commission'] = 'NaN'
        self.assertEqual(self.scan(c)['status'], 'BLOCKED_FILL_EVIDENCE')
    def test_duplicate_executions_block(self):
        c = Client(); c.rows[1]['id'] = 1
        self.assertEqual(self.scan(c)['status'], 'BLOCKED_DUPLICATE_FILL')
    def test_full_income_page_unsafe(self):
        c = Client(); c.income = [{'tranId': 1}]
        self.assertEqual(self.scan(c, page_size=1)['status'], 'BLOCKED_INCOME_PAGINATION')
    def test_symbol_funding_unattributable(self):
        c = Client(); c.income = [{'incomeType': 'FUNDING_FEE', 'income': '-0.1'}]
        self.assertEqual(self.scan(c)['status'], 'BLOCKED_FUNDING_ATTRIBUTION')
    def test_order_identity_mismatch(self):
        c = Client(); c.order['clientOrderId'] = 'different'
        self.assertEqual(self.scan(c)['status'], 'BLOCKED_ORDER_IDENTITY')
    def test_pagination_cap(self):
        c = Client()
        self.assertEqual(self.scan(c, page_size=1, max_pages=1)['status'], 'BLOCKED_FILL_PAGINATION')
    def test_api_error(self):
        c = Client()
        def timeout(*args, **kwargs): raise TimeoutError('offline')
        c.user_trades = timeout
        self.assertEqual(self.scan(c)['status'], 'BLOCKED_READBACK_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
