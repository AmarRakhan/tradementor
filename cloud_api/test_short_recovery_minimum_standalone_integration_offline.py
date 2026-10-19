import unittest
from decimal import Decimal as D
from short_recovery_standalone_cycle_offline import preview_cycle
from short_recovery_standalone_offline import RECOVERY,CLASSIC

class MinimumStandaloneIntegration(unittest.TestCase):
 def setUp(self):
  self.position={'account':'u','symbol':'XRPUSDT','offlineOnly':True,
    'state':'ADOPTED_OFFLINE','anchor':'100','originalShortQty':'1',
    'stepPct':'5','steps':4,'confirmedClosed':'0'}
  self.exchange={'account':'u','symbol':'XRPUSDT','verified':True,
    'hedgeMode':True,'openOrders':[],'LONG':'1','SHORT':'1'}
  self.filters={'minimum_qty':'.01','quantity_step':'.01',
    'minimum_notional':'30','executable_price':'100'}
 def decide(self,mark='95',**kw):
  values=dict(active_strategy=RECOVERY,account='u',position=self.position,
    exchange=self.exchange,mark=mark,auto_hedge_loss_usd='.25',
    open_long_pnl='-1',exchange_filters=self.filters)
  values.update(kw)
  return preview_cycle(**values)
 def test_four_step_carries_to_half(self):
  self.assertEqual(self.decide()['status'],'WAIT_MINIMUM_CARRY_FORWARD')
  second=self.decide('90')
  self.assertEqual(second['status'],'PREVIEW_SHORT_REDUCE')
  self.assertEqual(second['quantity'],D('.50'))
  self.position['confirmedClosed']='.5';self.exchange['SHORT']='.5'
  self.assertEqual(self.decide('85')['status'],'WAIT_MINIMUM_CARRY_FORWARD')
  self.assertEqual(self.decide('80')['quantity'],D('.5'))
 def test_ten_step_carries_to_thirty(self):
  self.position['steps']=10;self.position['stepPct']='5'
  self.assertEqual(self.decide('95')['status'],'WAIT_MINIMUM_CARRY_FORWARD')
  self.assertEqual(self.decide('90')['status'],'WAIT_MINIMUM_CARRY_FORWARD')
  self.assertEqual(self.decide('85')['quantity'],D('.3'))
 def test_final_dust_is_not_topped_up(self):
  self.position['confirmedClosed']='.9';self.exchange['SHORT']='.1'
  r=self.decide('80')
  self.assertEqual(r['status'],'BLOCKED_FINAL_REMAINDER_UNDER_MINIMUM')
  self.assertFalse(r['mayTopUp'])
  self.assertFalse(r['newCycleAuthorized'])
 def test_stop_classic_pending_open_orders(self):
  self.assertEqual(self.decide(stop=True)['status'],'BLOCKED_STOP')
  self.assertEqual(self.decide(active_strategy=CLASSIC)['status'],'BLOCKED_STRATEGY_NOT_ACTIVE')
  self.assertEqual(self.decide(pending=True)['status'],'WAIT_PENDING')
  self.exchange['openOrders']=[{'orderId':'unknown'}]
  self.assertEqual(self.decide()['status'],'BLOCKED_INVENTORY_UNVERIFIED')
 def test_missing_filters_fail_closed(self):
  self.assertEqual(self.decide(exchange_filters={})['status'],'BLOCKED_EXCHANGE_FILTER')

if __name__=='__main__':unittest.main()
