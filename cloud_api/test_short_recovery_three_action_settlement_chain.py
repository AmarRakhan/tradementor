"""One offline chain using existing bridge, claim, resolver and ledger (no orders)."""
import unittest
from decimal import Decimal as D
from short_recovery_contract import Plan,cycle_net_pnl
from short_recovery_reduction import ReductionState
from short_recovery_shadow_bridge import preview_reconciliation
from short_recovery_order_claim_shadow import reserve
from short_recovery_order_resolution_shadow import resolve
from short_recovery_multidoc_mock import transactional
from short_recovery_firestore_mock import decode
from test_short_recovery_build48_settlement import Tests as Fixture

class Chain(unittest.TestCase):
 def setUp(self):
  self.h=Fixture('test_no_order_reconciled_terminal');self.h.setUp()
 def bridge(self,closed,price,short,exit_due=False):
  state=ReductionState(Plan(D('2'),D(100),D(5),4),D(closed),D(price))
  return preview_reconciliation(protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),recovery_states={'XRPUSDT':state},exchange_short_quantities={'XRPUSDT':D(short)},long_quantities={'XRPUSDT':D(100)},net_exits={'XRPUSDT'} if exit_due else set())['recovery_previews']['XRPUSDT']
 def settle(self,event,**kwargs):
  h=self.h;r=h.refs
  return resolve(db=h.db,transactional=transactional,claim_ref=r['claim'],ledger_ref=r['ledger'],marker_ref=r['marker'],owner_ref=r['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event=event,**kwargs)
 def test_reduce_confirmed_finances_then_net_pair_exit_preempts_next_step(self):
  before=self.bridge(0,'1.9',100)
  self.assertEqual(before['reduction']['due_qty'],D(25))
  self.assertEqual(self.settle('ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED')
  fill={'confirmed':True,'readbackVerified':True,'orderId':'o','executionId':'fill1','quantity':'25','realizedPnl':'.50','commission':'.05','funding':'0'}
  self.assertEqual(self.settle('FILL',evidence=fill,execution_id='fill1',quantity=25),'FILL_APPLIED')
  ledger=decode(self.h.db.snapshot(self.h.keys['ledger'])[1]);self.assertEqual(ledger.allocations[0].remaining,D(75))
  net=cycle_net_pnl('-.20','-.10',ledger.cycle_realized('c'),'.03','0')
  self.assertEqual(net,D('.12'))
  # This is a signal only; no pair CLOSE is submitted by the bridge.
  result=self.bridge(25,'1.8',75,exit_due=net>=D('.10'))
  self.assertEqual(result['status'],'EXIT_PAIR_PRIORITY')
  self.assertEqual(result['reduction']['status'],'BLOCKED_NET_EXIT')
 def test_unproven_fill_never_advances_reduction_cycle(self):
  self.assertEqual(self.settle('ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED')
  self.assertEqual(self.settle('FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='x',quantity=25),'BLOCKED_FINANCIAL_EVIDENCE')
  self.assertEqual(decode(self.h.db.snapshot(self.h.keys['ledger'])[1]).allocations[0].remaining,D(100))
 def test_unknown_does_not_trigger_rehedge_and_stop_blocks_new_claim(self):
  self.assertEqual(self.settle('UNKNOWN'),'BLOCKED_UNKNOWN')
  state=self.bridge(100,'1.6',0)
  self.assertEqual(state['rehedge'],'PREVIEW_REHEDGE_1_TO_1')
  self.h.db.commit(self.h.keys['control'],1,{'account':'u','enabled':False,'emergencyStop':True,'closeAllActive':False})
  h=self.h;r=h.refs
  self.assertEqual(reserve(db=h.db,transactional=transactional,marker_ref=r['marker'],owner_ref=r['owner'],ledger_ref=r['ledger'],claim_ref=r['claim'],control_ref=r['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id='new',now=2),'BLOCKED_UNRESOLVED_CLAIM')
  self.assertEqual(self.settle('LATE_ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED_RECOVERED')
