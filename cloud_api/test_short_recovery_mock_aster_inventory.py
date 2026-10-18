import unittest
from decimal import Decimal
from aster_gateway import AsterOrderIntent,PositionSide
from short_recovery_inventory_preflight import refresh_mock_aster_inventory,check_inventory
class Client:
 offline_mock_only=True
 def __init__(self):self.qty='75';self.orders=[];self.count=0
 def account_information(self):return {'account':'u','hedgeMode':True}
 def position_risk(self,symbol):
  self.count+=1
  return [{'symbol':symbol,'positionSide':'LONG','positionAmt':'100'}, {'symbol':symbol,'positionSide':'SHORT','positionAmt':self.qty}]
 def open_orders(self,symbol):return self.orders
class TestMockAster(unittest.TestCase):
 def test_fresh_client_readback_blocks_changed_inventory(self):
  c=Client();i=AsterOrderIntent('test','XRPUSDT',PositionSide.SHORT,Decimal(25),'CLOSE')
  first=refresh_mock_aster_inventory(client=c,account='u',symbol='XRPUSDT',now_ms=10000)
  self.assertEqual(check_inventory(intents=(i,),symbol='XRPUSDT',readback=first,account='u',now_ms=10000),'INVENTORY_VERIFIED')
  c.qty='10'
  second=refresh_mock_aster_inventory(client=c,account='u',symbol='XRPUSDT',now_ms=10001)
  self.assertEqual(check_inventory(intents=(i,),symbol='XRPUSDT',readback=second,account='u',now_ms=10001),'BLOCKED_INVENTORY_OVER_CLOSE')
  self.assertEqual(c.count,2)
 def test_open_orders_and_wrong_account_block(self):
  c=Client();c.orders=[{'orderId':'pending'}]
  x=refresh_mock_aster_inventory(client=c,account='u',symbol='XRPUSDT',now_ms=10000)
  i=AsterOrderIntent('test','XRPUSDT',PositionSide.SHORT,Decimal(25),'CLOSE')
  self.assertEqual(check_inventory(intents=(i,),symbol='XRPUSDT',readback=x,account='u',now_ms=10000),'BLOCKED_INVENTORY_STALE_OR_SCOPE')
  self.assertIsNone(refresh_mock_aster_inventory(client=c,account='other',symbol='XRPUSDT',now_ms=10000))
