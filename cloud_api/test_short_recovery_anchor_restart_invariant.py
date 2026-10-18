"""Offline price ladder invariant; persistent cycle-anchor binding remains NO-GO."""
import unittest
from decimal import Decimal as D
from short_recovery_contract import Plan
from short_recovery_reduction import ReductionState,plan_reduction,preview_after_fill,rehedge_permission
from short_recovery_multidoc_mock import MultiDocDB,Ref

class AnchorRestartInvariant(unittest.TestCase):
 def test_fixed_hedge_anchor_survives_partial_steps_and_mock_firestore_restart(self):
  db=MultiDocDB();key=('u','XRPUSDT','cycle','c')
  ref=Ref(db,key)
  db.commit(key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','anchor':'2','initialQty':'100','confirmedClosed':'0','pending':False})
  expected=[D('1.90'),D('1.80'),D('1.70'),D('1.60')]
  for index,price in enumerate(expected):
   db=db.restart();ref=Ref(db,key)
   saved=ref.get(transaction=db.transaction()).to_dict()
   plan=Plan(D(saved['anchor']),D(saved['initialQty']),D(5),4)
   self.assertEqual(plan.trigger(index+1),price)
   self.assertEqual(tuple(plan.trigger(n) for n in range(1,5)),tuple(expected))
   state=ReductionState(plan,D(saved['confirmedClosed']),price,pending=saved['pending'])
   self.assertEqual(rehedge_permission(state,remaining_exchange_short_qty=D(100)-D(saved['confirmedClosed']),long_qty=D(100)),'BLOCKED_NOT_FINAL')
   # Partial execution must not move the anchor, and must block new submission.
   partial=preview_after_fill(state,D(10))
   waiting=ReductionState(plan,partial.confirmed_closed,price,pending=True)
   self.assertEqual(plan_reduction(waiting)['status'],'WAIT_PENDING')
   self.assertEqual(rehedge_permission(waiting,remaining_exchange_short_qty=D(90)-D(saved['confirmedClosed']),long_qty=D(100)),'WAIT_PENDING')
   current=db.snapshot(key);db.commit(key,current[0],{**saved,'confirmedClosed':str(D(saved['confirmedClosed'])+D(25)),'pending':False})
  db=db.restart();saved=Ref(db,key).get(transaction=db.transaction()).to_dict()
  self.assertEqual(saved['anchor'],'2')
  self.assertEqual(saved['cycleId'],'c')
  self.assertEqual(saved['confirmedClosed'],'100')
  self.assertEqual(rehedge_permission(ReductionState(Plan(D(2),D(100),D(5),4),D(100),D('1.60')),remaining_exchange_short_qty=D(0),long_qty=D(100)),'PREVIEW_REHEDGE_1_TO_1')
  # No new cycle/anchor is written by the planner. Only future verified
  # execution and canonical rehedge finality may establish a new anchor.
  self.assertIsNone(db.snapshot(('u','XRPUSDT','cycle','next'))[1])
