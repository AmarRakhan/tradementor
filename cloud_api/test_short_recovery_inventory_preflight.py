import unittest
from decimal import Decimal
from aster_gateway import AsterOrderIntent,PositionSide
from short_recovery_inventory_preflight import check_inventory
class OfflineInventory(unittest.TestCase):
 def intent(self,side,qty,action):return AsterOrderIntent('sr2-mock','XRPUSDT',PositionSide(side),Decimal(str(qty)),action)
 def check(self,intents,**changes):return check_inventory(intents=intents,symbol='XRPUSDT',readback={'symbol':'XRPUSDT','verified':True,'LONG':'100','SHORT':'75',**changes})
 def test_partial_short_close_allowed(self):self.assertEqual(self.check([self.intent('SHORT',25,'CLOSE')]),'INVENTORY_VERIFIED')
 def test_close_cannot_exceed_exchange_side(self):self.assertEqual(self.check([self.intent('SHORT',80,'CLOSE')]),'BLOCKED_INVENTORY_OVER_CLOSE')
 def test_rehedge_only_after_zero_short_and_exact_parity(self):
  self.assertEqual(self.check([self.intent('SHORT',100,'OPEN')],SHORT='0'),'INVENTORY_VERIFIED')
  self.assertEqual(self.check([self.intent('SHORT',100,'OPEN')]),'BLOCKED_REHEDGE_PARITY')
  self.assertEqual(self.check([self.intent('SHORT',90,'OPEN')],SHORT='0'),'BLOCKED_REHEDGE_PARITY')
 def test_unverified_inventory_blocks(self):self.assertEqual(self.check([self.intent('SHORT',25,'CLOSE')],verified=False),'BLOCKED_INVENTORY_UNVERIFIED')
