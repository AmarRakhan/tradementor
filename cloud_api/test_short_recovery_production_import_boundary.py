"""Static audit of known production entrypoints; not a runtime security boundary."""
import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
FINANCIAL={
 'short_recovery_order_resolution_shadow','short_recovery_marker_lifecycle_shadow',
 'short_recovery_order_settlement_shadow','short_recovery_transaction_adapter',
 'short_recovery_firestore_mock',
}
ENTRYPOINTS=('main.py','aster_position_loss_auto_hedge_extension.py')

class ProductionImportBoundary(unittest.TestCase):
 def test_no_unreviewed_dynamic_or_direct_financial_entrypoint(self):
  for filename in ENTRYPOINTS:
   source=(ROOT/filename).read_text()
   tree=ast.parse(source,filename=filename)
   findings=[]
   for node in ast.walk(tree):
    if isinstance(node,ast.Import):
     findings.extend((node.lineno,a.name) for a in node.names if a.name.split('.')[0] in FINANCIAL)
    elif isinstance(node,ast.ImportFrom):
     if (node.module or '').split('.')[0] in FINANCIAL:
      findings.append((node.lineno,node.module))
    elif isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='__import__':
     if node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str) and node.args[0].value.split('.')[0] in FINANCIAL:
      findings.append((node.lineno,node.args[0].value))
    elif isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='import_module':
     if node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str) and node.args[0].value.split('.')[0] in FINANCIAL:
      findings.append((node.lineno,node.args[0].value))
   expected=[] if filename=='main.py' else [(642,'short_recovery_order_resolution_shadow')]
   self.assertEqual(findings,expected,filename)
   if filename.endswith('extension.py'):
    self.assertIn('if execute or not force_shadow or not recovery_offline_partition:',source)
    self.assertIn('if ctx.get("account") != uid or not ctx.get("mock_only"):',source)
