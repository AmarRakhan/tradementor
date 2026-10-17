import unittest
from decimal import Decimal as D
from short_recovery_contract import Plan
from short_recovery_reduction import ReductionState
from short_recovery_shadow_bridge import preview_reconciliation

class ShadowBridgeTests(unittest.TestCase):
    def setUp(self):
        self.s=ReductionState(Plan(D(2),D(100),D(3),4), D(25), D("1.8"))
    def preview(self,**kw):
        return preview_reconciliation(protected_sides={"XRPUSDT":"LONG","BTCUSDT":"LONG"},
            existing_skip_symbols=set(),recovery_states={"XRPUSDT":self.s},
            exchange_short_quantities={"XRPUSDT":D(75)},long_quantities={"XRPUSDT":D(100)},**kw)
    def test_prevents_topup(self):
        r=self.preview()
        self.assertIn("XRPUSDT",r["skip_symbols"])
        self.assertEqual(r["orders_sent"],0)
    def test_other_long_untouched(self):
        r=self.preview()
        self.assertNotIn("BTCUSDT",r["skip_symbols"])
    def test_shadow_due_only(self):
        self.assertEqual(self.preview()["recovery_previews"]["XRPUSDT"]["reduction"]["due_qty"],D(50))
    def test_bounce_no_rehedge(self):
        self.assertEqual(self.preview()["recovery_previews"]["XRPUSDT"]["rehedge"],"BLOCKED_NOT_FINAL")
    def test_missing_owner_blocked(self):
        r=preview_reconciliation(protected_sides={},existing_skip_symbols=set(),
              recovery_states={"XRPUSDT":self.s},exchange_short_quantities={},long_quantities={})
        self.assertEqual(r["recovery_previews"]["XRPUSDT"]["status"],"BLOCKED_NOT_LONG_OWNER")
    def test_exit_preempts_rehedge(self):
        s=ReductionState(self.s.plan,D(100),D("1.75"))
        r=preview_reconciliation(protected_sides={"XRPUSDT":"LONG"},existing_skip_symbols=set(),
             recovery_states={"XRPUSDT":s},exchange_short_quantities={"XRPUSDT":D(0)},
             long_quantities={"XRPUSDT":D(100)},net_exits={"XRPUSDT"})
        self.assertEqual(r["recovery_previews"]["XRPUSDT"]["rehedge"],"EXIT_INSTEAD")
if __name__=="__main__":unittest.main()
