"""Check the exact partition passed before canonical Auto Hedge reconciliation, offline."""
import unittest
from short_recovery_gate import partition_reconciliation
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class PrePartition(unittest.TestCase):
 def partition(self, enabled=True, ownership=True):
  return partition_reconciliation(settings={'enabled':enabled,'steps':4,'stepPct':'5'},protected_sides={'XRPUSDT':'LONG','BTCUSDT':'LONG'},existing_skip_symbols=set(),recovery_cycles={'XRPUSDT':{'ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':ownership,'state':'PARTIAL'}})
 def test_recovery_prevents_legacy_topup(self):
  p=self.partition();h=TestShadowReconciler();h.setUp()
  r=h.run_shadow(p['shadow_skip']-p['legacy_skip'])
  self.assertEqual([a['symbol'] for a in r['actions']],['BTCUSDT'])
  self.assertEqual(r['ordersSent'],0)
 def test_disabled_legacy_behavior(self):
  p=self.partition(enabled=False);h=TestShadowReconciler();h.setUp()
  self.assertIn('XRPUSDT',[a['symbol'] for a in h.run_shadow(p['shadow_skip']-p['legacy_skip'])['actions']])
 def test_unverified_cycle_not_suppressed(self):
  p=self.partition(ownership=False);h=TestShadowReconciler();h.setUp()
  self.assertIn('XRPUSDT',[a['symbol'] for a in h.run_shadow(p['shadow_skip']-p['legacy_skip'])['actions']])
 def test_existing_run_uid_routes_offline_owned_symbols_to_deny_gate(self):
  import ast
  from pathlib import Path
  tree=ast.parse(Path(__file__).with_name('aster_position_loss_auto_hedge_extension.py').read_text())
  runner=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_run_uid')
  calls=[n for n in ast.walk(runner) if isinstance(n,ast.Call)
         and isinstance(n.func,ast.Name) and n.func.id=='reconcile_auto_hedge']
  self.assertEqual(len(calls),1)
  params={kw.arg:kw.value for kw in calls[0].keywords}
  self.assertIn('recovery_owned_symbols',params)
  self.assertEqual(ast.unparse(params['recovery_owned_symbols']),
                   ast.unparse(params['recovery_fence_required_symbols']))

 def test_live_reconciler_does_not_apply_shadow_skip(self):
  from unittest.mock import patch
  from aster_position_loss_auto_hedge import reconcile_auto_hedge
  h=TestShadowReconciler();h.setUp()
  # The production function only incorporates recovery_shadow_skip_symbols inside `if not execute`.
  # Avoid calling execute=True: it would be an order-execution test, not a safe read-only assertion.
  import inspect
  source=inspect.getsource(reconcile_auto_hedge)
  self.assertIn('if not execute:\n        shadow_skips.update(recovery_shadow_skip_symbols or set())',source)
