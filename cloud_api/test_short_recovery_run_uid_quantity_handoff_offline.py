"""Real offline run_uid integration of the quantity-based claim handoff."""
import unittest
from decimal import Decimal as D
from test_short_recovery_run_uid_integration import RunUidIntegration
from test_short_recovery_pair_aster_bridge import VerifiedAsterBridge
from short_recovery_multidoc_mock import Ref
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_standalone_offline import RECOVERY

class PriorClient:
 offline_mock_only=True
 def account_information(self):return {'account':'u','hedgeMode':True}
 def position_risk(self,s):return [{'symbol':s,'positionSide':'SHORT','positionAmt':'75'}]
 def open_orders(self,s):return []
 def query_order(self,s,c):return {'symbol':s,'clientOrderId':c,'orderId':'close-1','status':'FILLED','executedQty':'25'}
 def user_trades(self,s,**kw):return [{'id':1,'symbol':s,'orderId':'close-1','qty':'25','realizedPnl':'1','commission':'.1'}]

class RunUidQuantityHandoff(unittest.TestCase):
 def test_second_step_actual_canonical_mock_submit_without_funding_settlement(self):
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  db=h.fixture.db
  prev_id=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
  previous=Ref(db,'prior-close-1');new=Ref(db,'next-close-2')
  selector=Ref(db,'selector');pos=Ref(db,'standalone-pos')
  coord=Ref(db,('u','XRPUSDT','coordination'))
  db.commit(previous.key,0,{'account':'u','symbol':'XRPUSDT','cycle':'c',
    'intentId':prev_id,'step':1,'side':'SHORT','action':'CLOSE',
    'state':'PARTIAL','orderId':'close-1','offlineOrderTerminalVerified':True,
    'offlineTerminalQty':'25','offlineFundingStatus':'UNRECONCILED',
    'offlineNextClaimAuthorized':False,
    'offlineTerminalExecutions':[['1','25','1','0.1']]})
  db.commit(selector.key,0,{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  db.commit(pos.key,0,{'account':'u','symbol':'XRPUSDT','cycle':'c',
    'offlineOnly':True,'state':'ADOPTED_OFFLINE','pending':True,
    'steps':4,'originalShortQty':'100','confirmedClosed':'25'})
  db.commit(coord.key,0,{'recoveryFenceReservation':{'account':'u',
    'symbol':'XRPUSDT','cycle':'c','intentId':prev_id,
    'state':'RECOVERY_SUBMITTING_RECONCILE_ONLY'}})
  h.fixture.refs['SHORTclaim']=new
  posts=[]
  def post(intent):posts.append((intent.intent_id,intent.quantity,intent.action))
  r,_,h=RunUidIntegration().run_case(existing_harness=h,
    action_mode='REDUCE',reduction_step=2,reduction_mark='1.8',
    confirmed_closed=D(25),mock_transport=post,
    previous_close_claim_ref=previous,initialize_action_claim=False,
    quantity_handoff_refs={'selector_ref':selector,'position_ref':pos},
    previous_order_mock_client=PriorClient())
  self.assertEqual(r.get('shortRecoveryQuantityHandoff'),'QUANTITY_HANDOFF_RESERVED_OFFLINE',r)
  self.assertEqual(r.get('shortRecoverySubmit'),('SUBMITTED_RECONCILE_ONLY',),r)
  self.assertEqual(len(posts),1)
  self.assertEqual(posts[0][1],D(25))
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['state'],'SUBMITTING')
  self.assertEqual(h.fixture.snapshot('SHORTclaim')['financialSettlement'],'UNRECONCILED')
  self.assertEqual(db.snapshot(pos.key)[1]['pending'],False)
  self.assertEqual(db.snapshot(previous.key)[1]['offlineFundingStatus'],'UNRECONCILED')
  self.assertEqual(db.snapshot(coord.key)[1]['recoveryFenceReservation']['intentId'],posts[0][0])
if __name__=='__main__':unittest.main()
