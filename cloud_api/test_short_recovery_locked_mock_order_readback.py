import unittest
from test_short_recovery_pair_atomic_settlement import PairAtomic
from short_recovery_order_claim_shadow import reconcile_locked_mock_order_readback
from short_recovery_multidoc_mock import transactional
class Readback(unittest.TestCase):
 def fixture(self):
  x=PairAtomic('test_complete_two_sided_atomic_settlement');x.setUp()
  s=x.snapshot('SHORTclaim');s.update(state='SUBMITTING',offlineTransportOrigin='BEFORE_TRANSPORT_BLOCKED');x.put('SHORTclaim',s)
  x.db=x.db.restart();x.bind();return x
 def read(self,x,c):return reconcile_locked_mock_order_readback(db=x.db,transactional=transactional,claim_ref=x.refs['SHORTclaim'],account='u',symbol='XRPUSDT',cycle='c',intent_id='SHORT-intent',client=c)
 def test_missing_order_never_proves_no_order(self):
  x=self.fixture()
  class C:
   offline_mock_only=True
   def query_order(self,*args):return None
  self.assertEqual(self.read(x,C()),'NO_ORDER_UNPROVEN_CLAIM_LOCKED')
  self.assertEqual(x.snapshot('SHORTclaim')['state'],'SUBMITTING')
 def test_late_ack_readback_only(self):
  x=self.fixture()
  class C:
   offline_mock_only=True
   def query_order(self,*args):return {'symbol':'XRPUSDT','clientOrderId':'SHORT-intent','orderId':'SHORT-order','status':'NEW','executedQty':'0'}
   def user_trades(self,*args,**kwargs):return []
  self.assertEqual(self.read(x,C()),'LATE_ACK_READBACK_ONLY')
  self.assertEqual(x.snapshot('SHORTclaim')['state'],'ACKED')
 def test_no_mock_client_blocked(self):
  x=self.fixture();self.assertEqual(self.read(x,object()),'BLOCKED_MOCK_CLIENT_REQUIRED')

class SideIdentityRestored(Readback):
 def test_late_ack_persists_canonical_position_side(self):
  x=self.fixture()
  row=x.snapshot('SHORTclaim');row.pop('positionSide',None);row['side']='SHORT';x.put('SHORTclaim',row)
  class C:
   offline_mock_only=True
   def query_order(self,*args):return {'symbol':'XRPUSDT','clientOrderId':'SHORT-intent','orderId':'SHORT-order','status':'NEW','executedQty':'0'}
   def user_trades(self,*args,**kwargs):return []
  self.assertEqual(self.read(x,C()),'LATE_ACK_READBACK_ONLY')
  self.assertEqual(x.snapshot('SHORTclaim')['positionSide'],'SHORT')
 def test_conflicting_side_identity_blocks_without_mutation(self):
  x=self.fixture();row=x.snapshot('SHORTclaim');row['positionSide']='LONG';row['side']='SHORT';x.put('SHORTclaim',row)
  before=x.snapshot('SHORTclaim')
  class C:
   offline_mock_only=True
   def query_order(self,*args):return {'symbol':'XRPUSDT','clientOrderId':'SHORT-intent','orderId':'SHORT-order','status':'NEW','executedQty':'0'}
   def user_trades(self,*args,**kwargs):return []
  self.assertEqual(self.read(x,C()),'BLOCKED_SIDE_IDENTITY')
  self.assertEqual(x.snapshot('SHORTclaim'),before)

class PartialTerminalRestartReadback(Readback):
 def test_partial_fill_is_recognized_without_booking(self):
  x=self.fixture();before=x.snapshot('SHORTledger')
  class C:
   offline_mock_only=True
   def query_order(self,*args):return {'symbol':'XRPUSDT','clientOrderId':'SHORT-intent','orderId':'SHORT-order','status':'PARTIALLY_FILLED','executedQty':'25'}
   def user_trades(self,*args,**kw):return [{'id':1,'symbol':'XRPUSDT','orderId':'SHORT-order','qty':'25','realizedPnl':'1','commission':'.1'}]
  self.assertEqual(self.read(x,C()),'PARTIAL_FILLS_NEED_FINANCIAL_PROOF')
  self.assertEqual(x.snapshot('SHORTledger'),before)
  self.assertEqual(x.snapshot('SHORTclaim')['state'],'ACKED')
 def test_terminal_fill_also_needs_financial_proof(self):
  x=self.fixture();before=x.snapshot('SHORTledger')
  class C:
   offline_mock_only=True
   def query_order(self,*args):return {'symbol':'XRPUSDT','clientOrderId':'SHORT-intent','orderId':'SHORT-order','status':'FILLED','executedQty':'75'}
   def user_trades(self,*args,**kw):return [{'id':1,'symbol':'XRPUSDT','orderId':'SHORT-order','qty':'75','realizedPnl':'2','commission':'.1'}]
  self.assertEqual(self.read(x,C()),'TERMINAL_FILLS_NEED_FINANCIAL_PROOF')
  self.assertEqual(x.snapshot('SHORTledger'),before)
  self.assertNotEqual(x.snapshot('pair')['state'],'CLOSED')
