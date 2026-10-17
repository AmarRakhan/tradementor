import unittest
from short_recovery_settings import canonical_recovery_settings as norm, project_user_settings, execution_allowed, reconcile_routing
class Tests(unittest.TestCase):
    def test_default_off(self):self.assertEqual(norm()["mode"],"OFF")
    def test_four_three(self):self.assertEqual(norm({"enabled":True,"stepPct":"3","steps":4})["mode"],"SHADOW_ONLY")
    def test_twenty_two(self):self.assertEqual(norm({"enabled":True,"stepPct":"2","steps":20})["steps"],20)
    def test_invalid_twenty_five(self):
        with self.assertRaises(ValueError):norm({"enabled":True,"stepPct":"5","steps":20})
    def test_boolean_steps_rejected(self):
        with self.assertRaises(ValueError):norm({"enabled":True,"steps":True})
    def test_enable_type(self):
        with self.assertRaises(ValueError):norm({"enabled":"true"})
    def test_nonfinite(self):
        with self.assertRaises(ValueError):norm({"enabled":True,"stepPct":"NaN"})
    def test_independent_autohedge(self):
        self.assertFalse(project_user_settings({"enabled":True})["enabled"])
    def test_no_orders(self):self.assertFalse(execution_allowed(norm({"enabled":True})))
    def test_shadow_does_not_change_legacy_skip(self):
        r=reconcile_routing(settings={"shortRecoveryPlan":{"enabled":True,"steps":4,"stepPct":"3"}}, deliberate_partial_symbols={"XRPUSDT"},existing_skip_symbols={"ETHUSDT"})
        self.assertEqual(r["legacy_skip_symbols"],{"ETHUSDT"})
        self.assertEqual(r["preview_excluded_symbols"],{"XRPUSDT"})
    def test_off_no_preview_exclusions(self):
        r=reconcile_routing(settings={},deliberate_partial_symbols={"XRPUSDT"},existing_skip_symbols=set())
        self.assertEqual(r["preview_excluded_symbols"],set())
if __name__=="__main__":unittest.main()
