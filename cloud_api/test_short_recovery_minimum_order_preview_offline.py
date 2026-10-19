import unittest
from decimal import Decimal as D
from short_recovery_contract import Plan
from short_recovery_reduction import ReductionState
from short_recovery_minimum_order_preview_offline import preview_minimum_aware_reduction as preview

class MinimumCloseCarryForward(unittest.TestCase):
 def decide(self,*,steps=4,mark='95',closed='0',short='1',min_notional='30',price='100',min_qty='.01',step='.01'):
  state=ReductionState(Plan(D('100'),D('1'),D('5'),steps),D(closed),D(mark))
  return preview(state=state,exchange_short_qty=short,minimum_qty=min_qty,
                 quantity_step=step,minimum_notional=min_notional,executable_price=price)
 def test_four_step_skip_25_close_50_at_second_anchor(self):
  a=self.decide()
  self.assertEqual(a['status'],'WAIT_MINIMUM_CARRY_FORWARD')
  self.assertEqual(a['carried_due_qty'],D('.25'))
  b=self.decide(mark='90')
  self.assertEqual(b['status'],'PREVIEW_MINIMUM_VALID_REDUCE_ONLY')
  self.assertEqual(b['due_qty'],D('.5'))
  self.assertEqual(b['remaining_after'],D('.5'))
  c=self.decide(mark='85',closed='.5',short='.5')
  self.assertEqual(c['status'],'WAIT_MINIMUM_CARRY_FORWARD')
  d=self.decide(mark='80',closed='.5',short='.5')
  self.assertEqual(d['due_qty'],D('.5'))
 def test_ten_step_accumulates_three_targets(self):
  self.assertEqual(self.decide(steps=10,mark='95')['status'],'WAIT_MINIMUM_CARRY_FORWARD')
  self.assertEqual(self.decide(steps=10,mark='90')['status'],'WAIT_MINIMUM_CARRY_FORWARD')
  self.assertEqual(self.decide(steps=10,mark='85')['due_qty'],D('.3'))
 def test_final_dust_never_topups_or_rehedges(self):
  r=self.decide(mark='80',closed='.9',short='.1')
  self.assertEqual(r['status'],'BLOCKED_FINAL_REMAINDER_UNDER_MINIMUM')
  self.assertFalse(r['mayTopUp'])
  self.assertFalse(r['newCycleAuthorized'])
 def test_never_round_up_or_assume_dust_exception(self):
  r=self.decide(mark='90',closed='0',short='1',step='.3',min_notional='1')
  self.assertEqual(r['due_qty'],D('.3'))
  self.assertEqual(r['remaining_after'],D('.7'))
  s=ReductionState(Plan(D('100'),D('1'),D('5'),4),D('0'),D('95'))
  self.assertEqual(preview(state=s,exchange_short_qty='1',minimum_qty='.01',
     quantity_step='.01',minimum_notional='30',executable_price='100',
     reduce_only_dust_exempt=True)['status'],'BLOCKED_UNVERIFIED_DUST_EXEMPTION')
 def test_invalid_exchange_filters_fail_closed(self):
  self.assertEqual(self.decide(price='NaN')['status'],'BLOCKED_EXCHANGE_FILTER')
  self.assertEqual(self.decide(min_qty='0')['status'],'BLOCKED_EXCHANGE_FILTER')
 def test_pending_cannot_skip_claim(self):
  s=ReductionState(Plan(D('100'),D('1'),D('5'),4),D('0'),D('90'),pending=True)
  self.assertEqual(preview(state=s,exchange_short_qty='1',minimum_qty='.01',
    quantity_step='.01',minimum_notional='30',executable_price='100')['status'],'WAIT_PENDING')

if __name__=='__main__':unittest.main()
