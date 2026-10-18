"""Executable reconciler safety-fence tests; exchange transport forbidden."""
import unittest
from unittest.mock import patch
from decimal import Decimal
import aster_position_loss_auto_hedge as engine

class NoOrders:
    def position_mode(self):return True
    def account_information(self):return {'availableBalance':'100000'}
    def submit_order_once(self,*a,**k):raise AssertionError('order transport forbidden')
    def query_order(self,*a,**k):return None
    def position_risk(self):raise AssertionError('unexpected read')
    def open_orders(self):raise AssertionError('unexpected read')

class FenceTests(unittest.TestCase):
    def test_denied_fence_blocks_order_transport(self):
        rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'},
              {'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':'-75','unRealizedProfit':'10','markPrice':'1.8'}]
        with patch.object(engine,'_exchange_rule',return_value=object()),patch.object(engine,'_exact_market_quantity',return_value=Decimal('25')),patch.object(engine,'_query_existing',return_value=None):
            result=engine.reconcile_auto_hedge(client=NoOrders(),uid='u',threshold_usd=1,execute=True,
                protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[],
                pre_order_fence=lambda symbol,operation,intent:False)
        self.assertEqual(result['ordersSent'],0)
        self.assertEqual(result['actions'][0]['reason'],'PRE_ORDER_FENCE_DENIED')
    def test_throwing_fence_blocks_order_transport(self):
        def broken(*a):raise RuntimeError('transaction lost')
        rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'},
              {'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':'-75','unRealizedProfit':'10','markPrice':'1.8'}]
        with patch.object(engine,'_exchange_rule',return_value=object()),patch.object(engine,'_exact_market_quantity',return_value=Decimal('25')),patch.object(engine,'_query_existing',return_value=None):
            r=engine.reconcile_auto_hedge(client=NoOrders(),uid='u',threshold_usd=1,execute=True,
                protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[],pre_order_fence=broken)
        self.assertEqual(r['ordersSent'],0)
        self.assertEqual(r['actions'][0]['status'],'BLOCKED')
    def test_uncertain_query_blocks_new_fenced_post(self):
        rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'},{'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':'-75','unRealizedProfit':'10','markPrice':'1.8'}]
        c=NoOrders()
        def unavailable(*args):raise TimeoutError('unavailable')
        c.query_order=unavailable
        with patch.object(engine,'_exchange_rule',return_value=object()),patch.object(engine,'_exact_market_quantity',return_value=Decimal('25')):
            r=engine.reconcile_auto_hedge(client=c,uid='u',threshold_usd=1,execute=True,protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[],pre_order_fence=lambda *a:True)
        self.assertEqual(r['ordersSent'],0)
        self.assertIn('FENCED_QUERY_ORDER_UNKNOWN',r['actions'][0]['reason'])
    def test_unknown_query_never_reposts_fenced_action(self):
        rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-20','markPrice':'1.8','leverage':'10'},{'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':'-75','unRealizedProfit':'10','markPrice':'1.8'}]
        c=NoOrders()
        def broken(*args):raise TimeoutError('uncertain readback')
        c.query_order=broken
        with patch.object(engine,'_exchange_rule',return_value=object()),patch.object(engine,'_exact_market_quantity',return_value=Decimal('25')):
            result=engine.reconcile_auto_hedge(client=c,uid='u',threshold_usd=1,execute=True,protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[],pre_order_fence=lambda *a:True)
        self.assertEqual(result['ordersSent'],0)
        self.assertEqual(result['actions'][0]['status'],'FAILED')
        self.assertIn('FENCED_QUERY_ORDER_UNKNOWN',result['actions'][0]['reason'])
