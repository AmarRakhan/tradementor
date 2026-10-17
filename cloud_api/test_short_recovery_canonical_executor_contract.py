import unittest
from decimal import Decimal as D
from short_recovery_contract import Plan
from short_recovery_reduction import ReductionState
from short_recovery_shadow_bridge import preview_reconciliation
from short_recovery_executor_adapter import preview_canonical_executor
class CanonicalExecutor(unittest.TestCase):
 def preview(self,closed,price,short,exit=False):
  state=ReductionState(Plan(D(2),D(100),D(5),4),D(closed),D(price))
  bridge=preview_reconciliation(protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),recovery_states={'XRPUSDT':state},exchange_short_quantities={'XRPUSDT':D(short)},long_quantities={'XRPUSDT':D(100)},net_exits={'XRPUSDT'} if exit else set())
  return bridge
 def route(self,bridge,short,**flags):
  return preview_canonical_executor(reconciled=bridge,symbol='XRPUSDT',long_qty=100,short_qty=short,ownership_verified=True,claim_reserved=True,stop_clear=True,intent_ids={'LONG_CLOSE':'LONG-intent','SHORT_CLOSE':'SHORT-intent','SHORT_OPEN':'SHORT-open-intent'},**flags)
 def test_25_percent_reduction_is_only_short_close(self):
  r=self.route(self.preview(0,'1.9',100),100)
  self.assertEqual(r['status'],'PREVIEW_SHORT_REDUCE');self.assertEqual(len(r['intents']),1)
  self.assertEqual((r['intents'][0].action,r['intents'][0].position_side.value,r['intents'][0].quantity),('CLOSE','SHORT',D(25)))
  self.assertEqual(r['ordersSent'],0)
 def test_full_final_rehedge_requires_zero_short(self):
  r=self.route(self.preview(100,'1.6',0),0)
  self.assertEqual(r['status'],'PREVIEW_REHEDGE_REQUIRES_FINAL_READBACK')
  self.assertEqual((r['intents'][0].action,r['intents'][0].quantity),('OPEN',D(100)))
 def test_pair_net_exit_requires_proven_finances(self):
  bridge=self.preview(25,'1.8',75,exit=True)
  self.assertEqual(self.route(bridge,75)['status'],'BLOCKED_NET_EVIDENCE')
  result=self.route(bridge,75,net_evidence_verified=True)
  self.assertEqual(result['status'],'PREVIEW_PAIR_CLOSE_REQUIRES_ATOMIC_CLAIMS')
  self.assertEqual([x.position_side.value for x in result['intents']],['LONG','SHORT'])
 def test_stop_claim_or_owner_missing_blocks_every_action(self):
  bridge=self.preview(0,'1.9',100)
  for field in ('stop_clear','claim_reserved','ownership_verified'):
   args=dict(reconciled=bridge,symbol='XRPUSDT',long_qty=100,short_qty=100,stop_clear=True,claim_reserved=True,ownership_verified=True)
   args[field]=False
   self.assertEqual(preview_canonical_executor(**args)['status'],'BLOCKED_GATES')
 def test_not_canonically_skipped_blocks_legacy_collision(self):
  b=self.preview(0,'1.9',100);b['skip_symbols'].clear()
  self.assertEqual(self.route(b,100)['status'],'BLOCKED_LEGACY_RECONCILER')
