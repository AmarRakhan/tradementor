"""Deny-only Recovery live ownership boundary, tested without importing the live server."""
import ast
import unittest
from pathlib import Path
from short_recovery_gate import blocks_live_recovery_without_canonical_fence as blocked

class LiveRecoveryFenceOffline(unittest.TestCase):
    def test_enabled_recovery_blocks(self):
        for steps in (4,10):
            self.assertTrue(blocked({'enabled':True,'steps':steps,'stepPct':'2'}))
    def test_invalid_recovery_fails_closed(self):
        for plan in ({'enabled':True,'steps':0}, 'invalid', {'enabled':True,'stepPct':'NaN'}):
            with self.subTest(plan=plan): self.assertTrue(blocked(plan))
    def test_classic_remains_unaffected(self):
        self.assertFalse(blocked(None))
        self.assertFalse(blocked({'enabled':False}))
    def test_execution_path_denies_before_client_creation(self):
        path=Path(__file__).with_name('aster_position_loss_auto_hedge_extension.py')
        tree=ast.parse(path.read_text())
        method=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_run_uid')
        calls=[n for n in ast.walk(method) if isinstance(n,ast.Call)]
        gate=[n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='blocks_live_recovery_without_canonical_fence']
        clients=[n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='_client']
        self.assertEqual(len(gate),1)
        self.assertEqual(len(clients),1)
        self.assertLess(gate[0].lineno, clients[0].lineno)
