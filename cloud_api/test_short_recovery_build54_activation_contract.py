"""Offline source contracts: no frontend activation until real execution gates validated."""
import pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parent.parent
class ActivationContracts(unittest.TestCase):
 def test_default_off_backend(self):
  from short_recovery_gate import normalize_settings
  self.assertFalse(normalize_settings(None)['enabled'])
 def test_same_auto_hedge_endpoint(self):
  source=(ROOT/'cloud_api/aster_position_loss_auto_hedge_extension.py').read_text()
  self.assertIn('shortRecoveryPlan: dict[str, Any] | None = None',source)
  self.assertIn('if request.shortRecoveryPlan is not None:',source)
 def test_legacy_config_write_unchanged(self):
  source=(ROOT/'web/components/aster-position-loss-auto-hedge-bridge.tsx').read_text()
  self.assertIn('enabled, thresholdUsd: threshold, confirmDisable:',source)
 def test_preview_switch_locked(self):
  source=(ROOT/'web/components/short-recovery-plan-preview.tsx').read_text()
  self.assertIn('checked={false} disabled',source)
  self.assertNotIn('authenticatedRequest(',source)
 def test_shadow_gate_separate_from_live(self):
  source=(ROOT/'cloud_api/aster_position_loss_auto_hedge_extension.py').read_text()
  self.assertIn('if (not execute and',source)
  self.assertIn('ASTER_SHORT_RECOVERY_SHADOW_ENABLED',source)
if __name__=="__main__":unittest.main()
