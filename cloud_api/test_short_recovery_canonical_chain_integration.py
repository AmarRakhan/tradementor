"""Offline canonical intent -> owned claim -> final gate -> financial settlement proof.
No live transport, executor activation, or production reads.
"""
import unittest
from decimal import Decimal as D
from short_recovery_contract import Plan
from short_recovery_reduction import ReductionState
from short_recovery_shadow_bridge import preview_reconciliation
from short_recovery_executor_adapter import preview_canonical_executor
from short_recovery_order_claim_shadow import pre_submit_check, reserve
from short_recovery_order_resolution_shadow import resolve
from short_recovery_firestore_mock import decode
from short_recovery_multidoc_mock import transactional
from test_short_recovery_build48_settlement import Tests as Fixture

class CanonicalChain(unittest.TestCase):
 def setUp(self):
  self.h=Fixture('test_no_order_reconciled_terminal');self.h.setUp()
 def proposal(self,closed,price,short,exit_due=False,financial=False):
  state=ReductionState(Plan(D(2),D(100),D(5),4),D(closed),D(price))
  bridge=preview_reconciliation(protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),recovery_states={'XRPUSDT':state},exchange_short_quantities={'XRPUSDT':D(short)},long_quantities={'XRPUSDT':D(100)},net_exits={'XRPUSDT'} if exit_due else set())
  return preview_canonical_executor(reconciled=bridge,symbol='XRPUSDT',long_qty=100,short_qty=short,ownership_verified=True,claim_reserved=True,stop_clear=True,intent_ids={'LONG_CLOSE':'LONG-intent','SHORT_CLOSE':'SHORT-intent','SHORT_OPEN':'SHORT-open-intent'},net_evidence_verified=financial)
 def presubmit(self):
  h=self.h
  return pre_submit_check(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],control_ref=h.refs['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',account_close_guard=lambda:None)
 def event(self,event,**kw):
  h=self.h
  return resolve(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],ledger_ref=h.refs['ledger'],marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event=event,**kw)
 def stop(self,**changes):
  h=self.h;k=h.keys['control'];v,row=h.db.snapshot(k);h.db.commit(k,v,{**row,**changes})
 def test_short_reduction_through_claim_gate_and_confirmed_settlement(self):
  p=self.proposal(0,'1.9',100)
  self.assertEqual((p['status'],p['intents'][0].action,p['intents'][0].quantity),('PREVIEW_SHORT_REDUCE','CLOSE',D(25)))
  self.assertEqual(self.presubmit(),'PREFLIGHT_SHADOW_ONLY')
  self.assertEqual(self.event('ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED')
  evidence={'confirmed':True,'readbackVerified':True,'orderId':'o','executionId':'e1','quantity':'25','realizedPnl':'.60','commission':'.10','funding':'-.02'}
  self.assertEqual(self.event('FILL',evidence=evidence,execution_id='e1',quantity=25),'FILL_APPLIED')
  self.assertEqual(self.event('FILL',evidence=evidence,execution_id='e1',quantity=25),'ALREADY_APPLIED')
  self.assertEqual(decode(self.h.db.snapshot(self.h.keys['ledger'])[1]).cycle_realized('c'),D('.48'))
 def test_rehedge_is_proposal_only_and_not_implicitly_submitted(self):
  p=self.proposal(100,'1.6',0)
  self.assertEqual(p['status'],'PREVIEW_REHEDGE_REQUIRES_FINAL_READBACK')
  self.assertEqual((p['intents'][0].action,p['intents'][0].position_side.value),('OPEN','SHORT'))
  self.assertEqual(p['ordersSent'],0)
 def test_pair_exit_both_sides_requires_financial_proof(self):
  self.assertEqual(self.proposal(25,'1.8',75,True)['status'],'BLOCKED_NET_EVIDENCE')
  p=self.proposal(25,'1.8',75,True,True)
  self.assertEqual(p['status'],'PREVIEW_PAIR_CLOSE_REQUIRES_ATOMIC_CLAIMS')
  self.assertEqual([(i.action,i.position_side.value) for i in p['intents']],[('CLOSE','LONG'),('CLOSE','SHORT')])
  self.assertEqual(p['ordersSent'],0)
 def test_stop_and_unknown_survive_restart_without_new_claim(self):
  self.stop(enabled=False,emergencyStop=True)
  self.assertEqual(self.presubmit(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
  self.assertEqual(self.event('UNKNOWN'),'BLOCKED_UNKNOWN')
  self.h.db=self.h.db.restart();self.h.bind()
  h=self.h
  self.assertEqual(reserve(db=h.db,transactional=transactional,marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],ledger_ref=h.refs['ledger'],claim_ref=h.refs['claim'],control_ref=h.refs['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id='new',now=4),'BLOCKED_UNRESOLVED_CLAIM')
  self.assertEqual(self.event('LATE_ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED_RECOVERED')
 def test_unproven_fill_does_not_book(self):
  self.event('ACK',evidence={'confirmed':True,'orderId':'o'})
  self.assertEqual(self.event('FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='e',quantity=25),'BLOCKED_FINANCIAL_EVIDENCE')
  self.assertEqual(decode(self.h.db.snapshot(self.h.keys['ledger'])[1]).cycle_realized('c'),D(0))
