import unittest
from test_short_recovery_pair_atomic_settlement import PairAtomic
from short_recovery_rehedge_readback_offline import verify
from short_recovery_multidoc_mock import transactional
class RehedgeReadback(unittest.TestCase):
 def test_verified_terminal_exchange_reads_and_matching_claim(self):
  f=PairAtomic('test_complete_two_sided_atomic_settlement');f.setUp()
  claim=f.snapshot('SHORTclaim');claim.update({'side':'SHORT','action':'CLOSE','state':'CLOSED','executedQty':'75'});f.put('SHORTclaim',claim)
  class Mock:
   offline_mock_only=True
   def account_information(self):return {'account':'u','hedgeMode':True}
   def position_risk(self,s):return [{'symbol':s,'positionSide':'LONG','positionAmt':'100'},{'symbol':s,'positionSide':'SHORT','positionAmt':'0'}]
   def open_orders(self,s):return []
   def query_order(self,s,cid):return {'symbol':s,'clientOrderId':cid,'orderId':'SHORT-order','status':'FILLED','executedQty':'75'}
   def user_trades(self,s,**kwargs):return [{'symbol':s,'orderId':'SHORT-order','id':12,'qty':'75','realizedPnl':'1','commission':'.1'}]
  client=Mock()
  def check():return verify(db=f.db,transactional=transactional,claim_ref=f.refs['SHORTclaim'],client=client,account='u',symbol='XRPUSDT',cycle='c',long_qty='100',now_ms=10000)
  self.assertTrue(check())
  client.open_orders=lambda s:[{'orderId':'pending'}]
  self.assertFalse(check())
  client.open_orders=lambda s:[]
  client.position_risk=lambda s:[{'symbol':s,'positionSide':'LONG','positionAmt':'99'},{'symbol':s,'positionSide':'SHORT','positionAmt':'0'}]
  self.assertFalse(check())
