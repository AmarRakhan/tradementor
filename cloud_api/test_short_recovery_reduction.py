import unittest
from decimal import Decimal as D
from short_recovery_contract import Plan
from short_recovery_reduction import ReductionState,plan_reduction,preview_after_fill,rehedge_permission

class ReductionTests(unittest.TestCase):
    def setUp(self):self.p=Plan(D(2),D(100),D(3),4)
    def state(self,mark='1.8',closed=0,**kw):return ReductionState(self.p,D(closed),D(mark),**kw)
    def test_catchup_10_pct(self):
        d=plan_reduction(self.state())
        self.assertEqual((d['reached_steps'],d['due_qty']),(3,D(75)))
    def test_no_roi(self):self.assertEqual(plan_reduction(self.state(mark='2.1'))['due_qty'],D(0))
    def test_partial_fill(self):
        s=preview_after_fill(self.state(),D(30))
        self.assertEqual(plan_reduction(s)['due_qty'],D(45))
    def test_no_repeat(self):self.assertEqual(plan_reduction(self.state(closed=75))['due_qty'],D(0))
    def test_final_trigger(self):self.assertEqual(plan_reduction(self.state(mark='1.76'))['due_qty'],D(100))
    def test_no_rehedge_after_partial(self):self.assertEqual(rehedge_permission(self.state(closed=75),remaining_exchange_short_qty=25,long_qty=100),'BLOCKED_NOT_FINAL')
    def test_final_fill_required(self):self.assertEqual(rehedge_permission(self.state(closed=100),remaining_exchange_short_qty=1,long_qty=100),'BLOCKED_SHORT_NOT_ZERO')
    def test_rehedge_final(self):self.assertEqual(rehedge_permission(self.state(closed=100),remaining_exchange_short_qty=0,long_qty=100),'PREVIEW_REHEDGE_1_TO_1')
    def test_net_exit_first(self):self.assertEqual(rehedge_permission(self.state(closed=100),remaining_exchange_short_qty=0,long_qty=100,net_exit_due=True),'EXIT_INSTEAD')
    def test_pending(self):self.assertEqual(plan_reduction(self.state(pending=True))['status'],'WAIT_PENDING')
if __name__=='__main__':unittest.main()

class AnchoredFullCycle(unittest.TestCase):
 def test_all_steps_from_fixed_anchor_and_confirmed_fills_only(self):
  p=Plan(D(2),D(100),D(5),4)
  state=ReductionState(p,D(0),D(2))
  for step,mark in enumerate(('1.90','1.80','1.70','1.60'),1):
   state=ReductionState(p,state.confirmed_closed,D(mark))
   due=plan_reduction(state)
   self.assertEqual(due['reached_steps'],step)
   self.assertEqual(due['due_qty'],D(25))
   self.assertEqual(rehedge_permission(state,remaining_exchange_short_qty=D(100)-state.confirmed_closed,long_qty=D(100)),'BLOCKED_NOT_FINAL')
   state=preview_after_fill(state,D(25))
  self.assertEqual(state.confirmed_closed,D(100))
  self.assertEqual(rehedge_permission(state,remaining_exchange_short_qty=D(0),long_qty=D(100)),'PREVIEW_REHEDGE_1_TO_1')
  self.assertEqual(plan_reduction(state)['due_qty'],D(0))
