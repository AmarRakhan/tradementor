"""Static source contract tests: no HTTP, Firestore or exchange calls."""
import pathlib
import unittest

BASE = pathlib.Path(__file__).parent
SOURCE = (BASE/"aster_position_loss_auto_hedge_extension.py").read_text(encoding="utf-8")

class SettingsSourceTests(unittest.TestCase):
    def test_optional_request_field(self):
        self.assertIn("shortRecoveryPlan: dict[str, Any] | None = None", SOURCE)
    def test_existing_get_includes_canonical_plan(self):
        self.assertIn('"shortRecoveryPlan": recovery_plan', SOURCE)
    def test_existing_put_merges_only_if_supplied(self):
        put = SOURCE.split('@main.app.put("/v1/me/aster/position-loss-auto-hedge")')[1].split('@main.app.post(')[0]
        self.assertIn("if request.shortRecoveryPlan is not None:",put)
        self.assertIn('payload["shortRecoveryPlan"] =',put)
        self.assertIn('_doc(uid).set(payload, merge=True)',put)
    def test_invalid_plan_fails_before_write(self):
        put = SOURCE.split('@main.app.put("/v1/me/aster/position-loss-auto-hedge")')[1].split('@main.app.post(')[0]
        self.assertLess(put.index("normalize_recovery(request.shortRecoveryPlan)"),put.index("_doc(uid).set(payload, merge=True)"))
    def test_write_keeps_original_autohedge_keys(self):
        self.assertIn('"enabled": bool(request.enabled), "thresholdUsd": threshold',SOURCE)
    def test_shadow_gate_default_off(self):
        self.assertIn('os.getenv("ASTER_SHORT_RECOVERY_SHADOW_ENABLED", "false")',SOURCE)
    def test_no_second_settings_route(self):
        self.assertNotIn('@main.app.put("/v1/me/aster/short-recovery"',SOURCE)

if __name__=="__main__":unittest.main()
