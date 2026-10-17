"""Existing Auto Hedge bridge: priority among reduction, final rehedge and pair exit."""
import unittest
from decimal import Decimal as D
from short_recovery_contract import Plan, cycle_net_pnl
from short_recovery_reduction import ReductionState
from short_recovery_shadow_bridge import preview_reconciliation

class ThreeActions(unittest.TestCase):
 def plan(self,closed,mark):return ReductionState(Plan(D(2),D(100),D(5),4),D(closed),D(mark))
 def bridge(self,state,*,net_exit=False,short=None,long=D(100)):
  return preview_reconciliation(protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),recovery_states={'XRPUSDT':state},exchange_short_quantities={'XRPUSDT':D(100)-state.confirmed_closed if short is None else D(short)},long_quantities={'XRPUSDT':long},net_exits={'XRPUSDT'} if net_exit else set())
 def test_absolute_step_reduces_short_only(self):
  r=self.bridge(self.plan('0','1.9'))
  self.assertEqual(r['recovery_previews']['XRPUSDT']['reduction']['due_qty'],D(25))
  self.assertEqual(r['recovery_previews']['XRPUSDT']['rehedge'],'BLOCKED_NOT_FINAL')
  self.assertEqual(r['orders_sent'],0)
 def test_final_fill_can_rehedge_one_to_one(self):
  r=self.bridge(self.plan('100','1.6'),short=0)
  self.assertEqual(r['recovery_previews']['XRPUSDT']['rehedge'],'PREVIEW_REHEDGE_1_TO_1')
 def test_pair_net_exit_overrides_reduction(self):
  pnl=cycle_net_pnl('-0.20','-0.10','0.65','0.08','-0.02')
  self.assertEqual(pnl,D('0.25'))
  r=self.bridge(self.plan('25','1.8'),net_exit=pnl>=D('0.20'))
  self.assertEqual(r['recovery_previews']['XRPUSDT']['status'],'EXIT_PAIR_PRIORITY')
  self.assertEqual(r['recovery_previews']['XRPUSDT']['reduction']['status'],'BLOCKED_NET_EXIT')
  self.assertEqual(r['recovery_previews']['XRPUSDT']['rehedge'],'EXIT_INSTEAD')
 def test_pair_net_exit_overrides_rehedge(self):
  r=self.bridge(self.plan('100','1.6'),short=0,net_exit=True)
  self.assertEqual(r['recovery_previews']['XRPUSDT']['status'],'EXIT_PAIR_PRIORITY')
  self.assertEqual(r['orders_sent'],0)
 def test_other_account_and_legacy_execution_not_mutated(self):
  original={'XRPUSDT':'LONG'}
  r=preview_reconciliation(protected_sides=original,existing_skip_symbols={'BTCUSDT'},recovery_states={'XRPUSDT':self.plan('25','1.8')},exchange_short_quantities={'XRPUSDT':D(75)},long_quantities={'XRPUSDT':D(100)})
  self.assertEqual(original,{'XRPUSDT':'LONG'})
  self.assertIn('BTCUSDT',r['skip_symbols'])
  self.assertIn('XRPUSDT',r['skip_symbols'])
