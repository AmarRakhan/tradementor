"""Contract guard: legacy Auto Hedge GET exposes an optional default-OFF plan.

Read-only source assertion; no Firestore clients or order execution.
"""
import pathlib
import unittest
from short_recovery_gate import normalize_settings

class ReadbackContractTests(unittest.TestCase):
    def test_default_off(self):
        self.assertFalse(normalize_settings(None)["enabled"])
    def test_custom_steps(self):
        plan=normalize_settings({"enabled":False,"steps":20,"stepPct":"2"})
        self.assertEqual(plan["steps"],20)
        self.assertEqual(plan["lastLevelPct"],"40")
    def test_malformed_fields_fail_closed(self):
        with self.assertRaises(ValueError):
            normalize_settings({"steps":4,"stepPct":"NaN"})
    def test_existing_api_readback_is_optional(self):
        path=pathlib.Path(__file__).with_name("aster_position_loss_auto_hedge_extension.py")
        source=path.read_text(encoding="utf-8")
        self.assertIn('row.get("shortRecoveryPlan")',source)
        self.assertIn('"shortRecoveryPlan": recovery_plan',source)
        self.assertIn('"enabled": False, "status": "INVALID_SETTINGS"',source)
    def test_no_new_order_or_user_write_route(self):
        source=pathlib.Path(__file__).with_name("aster_position_loss_auto_hedge_extension.py").read_text(encoding="utf-8")
        self.assertNotIn('@main.app.put("/v1/me/aster/short-recovery"',source)

if __name__=="__main__": unittest.main()
