"""One continuous offline 4/10 run_uid reduction -> finality -> rehedge path.

Every claim uses the SAME MultiDocDB, selector, shared fence, and canonical
offline submit CAS. The external exchange is a mock and no financial settlement
is asserted. Lease creation remains a separately mocked authorized worker step.
"""
import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from concurrent.futures import ThreadPoolExecutor
from test_short_recovery_run_uid_integration import FourStepRunUidCycle
from short_recovery_multidoc_mock import Ref,transactional
from short_recovery_order_claim_shadow import canonical_intent_id,submit_once_offline
from short_recovery_final_quantity_cycle_offline import finalize_short_quantity_cycle_offline
from short_recovery_lease_fence_offline import reserve_verified_rehedge_mock_only
from short_recovery_rehedge_fill_activation_offline import activate_verified_rehedge_offline
from aster_gateway import AsterOrderIntent,PositionSide


class ContinuousRecoveryCycle(unittest.TestCase):
 def check_cycle(self,steps,financial=False):
  h,exchange,final_ref,selector,position=FourStepRunUidCycle().check_full_cycle(steps)
  db=h.fixture.db
  coord=Ref(db,('u','XRPUSDT','coordination'))
  control=h.fixture.refs['control']
  qty=D(100)/steps
  terminal=finalize_short_quantity_cycle_offline(
    mock_only=True,db=db,transactional=transactional,client=exchange,
    selector_ref=selector,position_ref=position,claim_ref=final_ref,
    coordination_ref=coord,control_ref=control,account='u',
    symbol='XRPUSDT',cycle='c',step=steps,long_qty=D(100))
  self.assertEqual(terminal,'QUANTITY_CYCLE_TERMINAL_UNSETTLED_FENCE_LOCKED')
  self.assertEqual(db.snapshot(position.key)[1]['state'],'FINAL_SHORT_FILLED_OFFLINE')
  self.assertEqual(db.snapshot(final_ref.key)[1]['executedQty'],str(qty))
  self.assertEqual(db.snapshot(final_ref.key)[1]['financialSettlement'],'UNRECONCILED')
  # Simulate the existing owner's acquisition of a NEW, still-valid lease.
  owner=Ref(db,'continuous-owner')
  db.commit(owner.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c',
    'ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True})
  now=datetime.now(timezone.utc)
  ver,row=db.snapshot(coord.key)
  db.commit(coord.key,ver,{**row,'lease':{'token':'new-lease','until':now+timedelta(minutes=2)}})
  if financial:
   # Explicitly supplied financial fixture; not an exchange income-history readback.
   v,claim=db.snapshot(final_ref.key)
   db.commit(final_ref.key,v,{**claim,'financialVerified':True,
      'fillsComplete':True,'incomeHistoryComplete':True,
      'financialSettlement':'RECONCILED',
      'executionFinancials':{'mock-fill':[str(qty),'1','0.1','0']}})
   v,current=db.snapshot(coord.key)
   db.commit(coord.key,v,{**current,'recoveryFenceReservation':None})
  new_ref=Ref(db,'continuous-new-'+str(steps))
  new_id=canonical_intent_id(account='u',symbol='XRPUSDT',
    cycle='c2',side='SHORT',action='OPEN',step=0)
  def reserve():
   return reserve_verified_rehedge_mock_only(
    mock_only=True,db=db,transactional=transactional,client=exchange,
    coordination_ref=coord,owner_ref=owner,final_claim_ref=final_ref,
    new_claim_ref=new_ref,control_ref=control,account='u',symbol='XRPUSDT',
    old_cycle='c',new_cycle='c2',lease_token='new-lease',intent_id=new_id,
    now=now,long_qty=D(100),now_ms=10000,
    allow_quantity_terminal_fence=not financial,require_financial_finality=financial)
  with ThreadPoolExecutor(max_workers=2) as pool:
   results=list(pool.map(lambda _:reserve(),range(2)))
  self.assertEqual(results.count('RESERVED_REHEDGE_MOCK_ONLY'),1)
  self.assertEqual(results.count('BLOCKED_REHEDGE_NEW_CLAIM_EXISTS'),1)
  self.assertEqual(db.snapshot(position.key)[1]['cycle'],'c')
  posts=[]
  def mock_post(intent):
   posts.append((intent.intent_id,intent.quantity,intent.action))
   return {'orderId':'new-short-open-'+str(steps)}
  def submit():
   return submit_once_offline(db=db,transactional=transactional,
    claim_ref=new_ref,control_ref=control,coordination_ref=coord,
    standalone_selector_ref=selector,require_shared_fence=True,
    account='u',symbol='XRPUSDT',cycle='c2',
    intent=AsterOrderIntent(new_id,'XRPUSDT',PositionSide.SHORT,D(100),'OPEN'),
    account_close_guard=lambda:None,submit_mock=mock_post)
  with ThreadPoolExecutor(max_workers=2) as pool:
   submissions=list(pool.map(lambda _:submit(),range(2)))
  self.assertEqual(submissions.count('SUBMITTED_RECONCILE_ONLY'),1)
  self.assertEqual(len(posts),1)
  self.assertEqual(submit(),'BLOCKED_CLAIM_NOT_RESERVED')
  self.assertEqual(db.snapshot(position.key)[1]['cycle'],'c')
  # The canonical client-order ID and independently resolved mock order ID
  # must be bound before the new cycle activation is permitted.
  open_oid='new-short-open-'+str(steps)
  version,claim=db.snapshot(new_ref.key)
  db.commit(new_ref.key,version,{**claim,'orderId':open_oid})
  def activate():
   return activate_verified_rehedge_offline(db=db,transactional=transactional,
    client=exchange,selector_ref=selector,position_ref=position,
    open_claim_ref=new_ref,coordination_ref=coord,control_ref=control,
    account='u',symbol='XRPUSDT',old_cycle='c',new_cycle='c2',
    steps=steps,step_pct='5')
  self.assertNotEqual(activate(),'NEW_CYCLE_FILL_VERIFIED_FENCE_LOCKED')
  exchange.short=D(100)
  exchange.order_id=open_oid
  exchange.query_order=lambda s,c:{'symbol':s,'clientOrderId':c,
   'orderId':open_oid,'status':'FILLED','executedQty':'100'}
  exchange.user_trades=lambda s,**kw:[{'symbol':s,'orderId':open_oid,
    'id':100+steps,'qty':'100','price':'1.625'}]
  self.assertEqual(activate(),'NEW_CYCLE_FILL_VERIFIED_FENCE_LOCKED')
  newpos=db.snapshot(position.key)[1]
  self.assertEqual((newpos['cycle'],newpos['anchor'],newpos['originalShortQty']),
                   ('c2','1.625','100'))
  self.assertEqual(db.snapshot(final_ref.key)[1]['financialSettlement'],
                   'RECONCILED' if financial else 'UNRECONCILED')
  self.assertEqual(submit(),'BLOCKED_CLAIM_NOT_RESERVED')
  self.assertEqual(len(posts),1)
 def test_four_steps_to_fresh_one_to_one_anchor(self):self.check_cycle(4)
 def test_ten_steps_to_fresh_one_to_one_anchor(self):self.check_cycle(10)
 def test_four_steps_with_explicit_reconciled_fixture(self):self.check_cycle(4,financial=True)
 def test_ten_steps_with_explicit_reconciled_fixture(self):self.check_cycle(10,financial=True)

if __name__=='__main__':unittest.main()
