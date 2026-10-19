import unittest
from decimal import Decimal as D
from short_recovery_multidoc_mock import Ref
from short_recovery_standalone_offline import RECOVERY
from test_short_recovery_run_uid_integration import RunUidIntegration
from test_short_recovery_pair_aster_bridge import VerifiedAsterBridge


class RunUidMinimumCarry(unittest.TestCase):
 def setUp(self):
  self.h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');self.h.setUp()
  db=self.h.fixture.db
  self.selector=Ref(db,'minimum-selector');self.position=Ref(db,'minimum-position')
  # The shared financial fixture has a pre-existing SHORT claim; use a fresh
  # canonical claim document to exercise reservation rather than overwrite it.
  self.h.fixture.refs['SHORTclaim']=Ref(db,'minimum-new-short-claim')
  db.commit(self.selector.key,0,{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  db.commit(self.position.key,0,{'account':'u','symbol':'XRPUSDT','cycle':'c',
    'offlineOnly':True,'state':'ADOPTED_OFFLINE','pending':False,'anchor':'2',
    'stepPct':'5','steps':4,'originalShortQty':'100','confirmedClosed':'0'})
  self.posts=[]
  from test_short_recovery_mock_aster_inventory import Client
  self.mock_client=Client()
  self.mock_client.qty='100'
  self.mock_client.exchange_filters=lambda symbol:{'symbol':symbol,'minimumQty':'1', 'quantityStep':'1','minimumNotional':'30'}
  self.mock_client.executable_price=lambda symbol:'1'
 def run_step(self,step,minimum_notional='60'):
  # Mock symbol is worth 1 per unit: 25 too small, 50 valid.
  mark='1.9' if step==1 else '1.8'
  scope={'selector_ref':self.selector,'position_ref':self.position,
    'mark':mark,'exchange_short_qty':'100','minimum_qty':'1',
    'quantity_step':'1','minimum_notional':minimum_notional,
    'executable_price':'1'}
  def post(intent):self.posts.append((intent.quantity,intent.intent_id))
  return RunUidIntegration().run_case(existing_harness=self.h,
    action_mode='REDUCE',reduction_step=step,reduction_mark=mark,
    confirmed_closed=D(0),mock_transport=post,
    minimum_carry_scope=scope,
    inventory_mock_client=self.mock_client,
    inventory_readback={'account':'u','symbol':'XRPUSDT','verified':True,
      'hedgeMode':True,'openOrders':[],'timestampMs':10000,'LONG':'100','SHORT':'100'})
 def test_first_small_step_has_no_claim_or_submit(self):
  r,_,_=self.run_step(1)
  self.assertEqual(r.get('shortRecoveryMinimumCarry'),'WAIT_MINIMUM_CARRY_FORWARD')
  self.assertNotIn('shortRecoverySubmit',r)
  self.assertEqual(self.posts,[])
 def test_second_step_submits_cumulative_amount_once(self):
  r,_,h=self.run_step(2,minimum_notional='30')
  self.assertEqual(r.get('shortRecoveryMinimumCarry'),'MINIMUM_CARRY_RESERVED_OFFLINE',repr(r))
  self.assertEqual(r.get('shortRecoverySubmit'),('SUBMITTED_RECONCILE_ONLY',),repr(r))
  self.assertEqual(len(self.posts),1)
  self.assertEqual(self.posts[0][0],D(50))
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['minimumCarryQuantity'],'50')
  again,_,_=self.run_step(2,minimum_notional='30')
  self.assertNotIn('shortRecoverySubmit',again)
  self.assertEqual(len(self.posts),1)
if __name__=='__main__':unittest.main()
