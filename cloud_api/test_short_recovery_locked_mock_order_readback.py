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
