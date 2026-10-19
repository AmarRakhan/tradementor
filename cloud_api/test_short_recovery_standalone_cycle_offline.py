import unittest
from decimal import Decimal as D
from short_recovery_standalone_offline import CLASSIC, RECOVERY
from short_recovery_standalone_cycle_offline import preview_cycle

class StandaloneCycle(unittest.TestCase):
 def setUp(self):
  self.position={'account':'u','symbol':'XRPUSDT','offlineOnly':True,'state':'ADOPTED_OFFLINE','anchor':'100','originalShortQty':'100','stepPct':'2','steps':10,'confirmedClosed':'0'}
  self.exchange={'account':'u','symbol':'XRPUSDT','verified':True,'hedgeMode':True,'openOrders':[],'LONG':'100','SHORT':'100'}
 def decide(self,**changes):
  kwargs=dict(active_strategy=RECOVERY,account='u',position=self.position,exchange=self.exchange,mark='98',auto_hedge_loss_usd='.25',open_long_pnl='-1')
  kwargs.update(changes)
  return preview_cycle(**kwargs)
 def test_ten_fixed_anchor_reductions_and_immediate_rehedge(self):
  for step in range(1,11):
   self.position['confirmedClosed']=str((step-1)*10)
   self.exchange['SHORT']=str(100-(step-1)*10)
   result=self.decide(mark=str(100-step*2))
   self.assertEqual(result['status'],'PREVIEW_SHORT_REDUCE')
   self.assertEqual(result['quantity'],D(10))
  self.position['confirmedClosed']='100';self.exchange['SHORT']='0'
  self.assertEqual(self.decide()['status'],'BLOCKED_FINAL_ORDER_UNVERIFIED')
  outcome=self.decide(final_order_verified=True)
  self.assertEqual((outcome['status'],outcome['quantity']),('PREVIEW_IMMEDIATE_REHEDGE',D(100)))
  self.assertTrue(outcome['newCycleRequired'])
 def test_four_steps_three_percent(self):
  self.position.update(steps=4,stepPct='3')
  for i in range(1,5):
   self.position['confirmedClosed']=str((i-1)*25);self.exchange['SHORT']=str(100-(i-1)*25)
   self.assertEqual(self.decide(mark=str(100-i*3))['quantity'],D(25))
 def test_classic_stop_pending_and_open_orders_block(self):
  self.assertEqual(self.decide(active_strategy=CLASSIC)['status'],'BLOCKED_STRATEGY_NOT_ACTIVE')
  self.assertEqual(self.decide(stop=True)['status'],'BLOCKED_STOP')
  self.assertEqual(self.decide(close_all=True)['status'],'BLOCKED_STOP')
  self.assertEqual(self.decide(pending=True)['status'],'WAIT_PENDING')
  self.exchange['openOrders']=[{'id':'unknown'}]
  self.assertEqual(self.decide()['status'],'BLOCKED_INVENTORY_UNVERIFIED')
 def test_partial_fills_and_inventory_drift(self):
  self.position['confirmedClosed']='5';self.exchange['SHORT']='95'
  self.assertEqual(self.decide()['quantity'],D(5))
  self.exchange['SHORT']='100'
  self.assertEqual(self.decide()['status'],'BLOCKED_INVENTORY_MISMATCH')
 def test_initial_hedge_dollar_trigger(self):
  self.position['state']='LONG_UNHEDGED_OFFLINE';self.exchange['SHORT']='0'
  self.assertEqual(self.decide(open_long_pnl='-.24')['status'],'WAIT_HEDGE_TRIGGER')
  self.assertEqual(self.decide(open_long_pnl='-.25')['status'],'PREVIEW_INITIAL_HEDGE')
  self.exchange['SHORT']='20'
  self.assertEqual(self.decide()['status'],'BLOCKED_UNEXPECTED_SHORT')
 def test_invalid_and_foreign_scope(self):
  self.assertEqual(self.decide(account='other')['status'],'BLOCKED_ACCOUNT_OR_SYMBOL')
  self.assertEqual(self.decide(mark='NaN')['status'],'BLOCKED_INVALID_FINANCIAL_OR_POSITION_INPUT')
  self.position['confirmedClosed']='101'
  self.assertEqual(self.decide()['status'],'BLOCKED_CONFIRMED_QUANTITY')
if __name__=='__main__':unittest.main()
