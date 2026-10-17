"""Real reconciler entrypoint, shadow only: no exchange calls."""
import unittest
from aster_position_loss_auto_hedge import reconcile_auto_hedge
class Client:
 def position_risk(self): raise AssertionError('unexpected exchange read')
 def open_orders(self): raise AssertionError('unexpected exchange read')
 def position_mode(self): raise AssertionError('LIVE must never be called')
 def submit_order(self,*a,**k): raise AssertionError('orders forbidden')
class TestShadowReconciler(unittest.TestCase):
 def setUp(self):
  self.rows=[
   {'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-10','markPrice':'1.8'},
   {'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':'-75','unRealizedProfit':'10','markPrice':'1.8'},
   {'symbol':'BTCUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-10','markPrice':'1.8'},
   {'symbol':'BTCUSDT','positionSide':'SHORT','positionAmt':'-100','unRealizedProfit':'10','markPrice':'1.8'}]
 def run_shadow(self,skip):
  return reconcile_auto_hedge(client=Client(),uid='mock',
      threshold_usd=1,execute=False,
      protected_sides={'XRPUSDT':'LONG','BTCUSDT':'LONG'},
      positions=self.rows,open_orders=[],recovery_shadow_skip_symbols=skip)
 def test_recovery_suppresses_topup(self):
  result=self.run_shadow({'XRPUSDT'})
  self.assertEqual(result['ordersSent'],0)
  self.assertEqual([x['symbol'] for x in result['actions']],['BTCUSDT'])
 def test_legacy_still_topup(self):
  result=self.run_shadow(None)
  self.assertIn('XRPUSDT',[x['symbol'] for x in result['actions']])
 def test_unrelated_coin_unchanged(self):
  a=self.run_shadow(None);b=self.run_shadow({'XRPUSDT'})
  self.assertEqual([x for x in a['actions'] if x['symbol']=='BTCUSDT'],
                   [x for x in b['actions'] if x['symbol']=='BTCUSDT'])
if __name__=='__main__':unittest.main()
