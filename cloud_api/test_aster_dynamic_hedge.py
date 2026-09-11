import unittest

from aster_dynamic_hedge import (
    DynamicHedgeConfig, assess_dynamic_hedge, dynamic_target_range,
    net_exposure, robust_hedge_coverage, safety_status,
)


def risk(ratio=10, equity=300, maintenance=30, reliable=True):
    return {
        "reliable": reliable,
        "liquidationRiskPct": ratio,
        "equity": equity,
        "maintenanceMarginUsd": maintenance,
    }


def exposure(long=1000, short=300, reliable=True):
    return {"reliable": reliable, "longExposureUsd": long, "shortExposureUsd": short}


def candidate(current_buffer=270, current_ratio=10, projected_buffer=260, projected_ratio=8,
              projected_maintenance=40, projected_equity=300):
    return {
        "currentMarginBufferUsd": current_buffer,
        "currentBufferRatio": current_ratio,
        "projectedMarginBufferUsd": projected_buffer,
        "projectedBufferRatio": projected_ratio,
        "projectedMaintenanceMarginUsd": projected_maintenance,
        "projectedEquity": projected_equity,
    }


class DynamicHedgeTests(unittest.TestCase):
    def test_robust_coverage_long_dominant(self):
        self.assertAlmostEqual(robust_hedge_coverage(8774, 1622), 18.486437, places=5)

    def test_robust_coverage_short_dominant(self):
        self.assertEqual(robust_hedge_coverage(250, 1000), 25.0)
        self.assertEqual(net_exposure(250, 1000), (-750.0, "SHORT"))

    def test_flat_zero_book_is_fully_neutral(self):
        self.assertEqual(robust_hedge_coverage(0, 0), 100.0)

    def test_safety_status_is_server_policy(self):
        self.assertEqual(safety_status(risk(10)), "VEILIG")
        self.assertEqual(safety_status(risk(30)), "OPLETTEN")
        self.assertEqual(safety_status(risk(60)), "HOOG_RISICO")
        self.assertEqual(safety_status(risk(80)), "KRITIEK")

    def test_equity_at_maintenance_is_critical(self):
        self.assertEqual(safety_status(risk(20, equity=50, maintenance=50)), "KRITIEK")

    def test_unreliable_data_never_safe(self):
        self.assertEqual(safety_status(risk(reliable=False)), "DATA_ONBETROUWBAAR")

    def test_available_is_not_an_input(self):
        value = risk(10)
        value["availableBalance"] = 0
        self.assertEqual(safety_status(value), "VEILIG")

    def test_dynamic_target_changes_with_margin_risk(self):
        self.assertEqual(dynamic_target_range(risk(10)), (25.0, 40.0))
        self.assertEqual(dynamic_target_range(risk(30)), (40.0, 60.0))
        self.assertEqual(dynamic_target_range(risk(60)), (60.0, 80.0))
        self.assertIsNone(dynamic_target_range(risk(80)))

    def test_disabled_mode_is_monitor_only(self):
        out = assess_dynamic_hedge(enabled=False, ownership_state="NORMAL", exposure=exposure(), risk=risk())
        self.assertEqual(out["engineState"], "MONITORING")
        self.assertFalse(out["riskAddingAllowed"])

    def test_adoption_never_trades(self):
        out = assess_dynamic_hedge(enabled=True, ownership_state="ADOPTING", exposure=exposure(), risk=risk(), candidate=candidate())
        self.assertEqual(out["engineState"], "POSITIONS_ADOPTING")
        self.assertFalse(out["riskAddingAllowed"])

    def test_manual_lock_never_trades(self):
        out = assess_dynamic_hedge(enabled=True, ownership_state="MANUAL_ACTION_LOCK", exposure=exposure(), risk=risk(), candidate=candidate())
        self.assertEqual(out["engineState"], "AUTOMATION_PAUSED")
        self.assertFalse(out["riskAddingAllowed"])

    def test_low_hedge_without_projection_fails_closed(self):
        out = assess_dynamic_hedge(enabled=True, ownership_state="DYNAMIC_HEDGE_ACTIVE", exposure=exposure(1000, 100), risk=risk())
        self.assertEqual(out["engineState"], "PROTECT_MARGIN_BUFFER")
        self.assertEqual(out["reasonCode"], "PROJECTED_MARGIN_EVIDENCE_MISSING")
        self.assertFalse(out["riskAddingAllowed"])

    def test_low_hedge_with_safe_projection_can_build(self):
        out = assess_dynamic_hedge(enabled=True, ownership_state="DYNAMIC_HEDGE_ACTIVE", exposure=exposure(1000, 100), risk=risk(), candidate=candidate())
        self.assertEqual(out["engineState"], "HEDGE_BUILDING")
        self.assertEqual(out["recommendedAction"], "OPEN_SHORT")
        self.assertTrue(out["riskAddingAllowed"])

    def test_low_hedge_with_unsafe_projection_is_blocked(self):
        bad = candidate(projected_buffer=2, projected_ratio=1.05, projected_maintenance=298)
        out = assess_dynamic_hedge(enabled=True, ownership_state="DYNAMIC_HEDGE_ACTIVE", exposure=exposure(1000, 100), risk=risk(), candidate=bad)
        self.assertEqual(out["engineState"], "PROTECT_MARGIN_BUFFER")
        self.assertFalse(out["riskAddingAllowed"])

    def test_critical_margin_prefers_gross_reduction_not_more_hedge(self):
        out = assess_dynamic_hedge(enabled=True, ownership_state="DYNAMIC_HEDGE_ACTIVE", exposure=exposure(1000, 100), risk=risk(85), candidate=candidate())
        self.assertEqual(out["engineState"], "REDUCE_GROSS_EXPOSURE")
        self.assertEqual(out["recommendedAction"], "REDUCE_GROSS_EXPOSURE")
        self.assertFalse(out["riskAddingAllowed"])

    def test_overhedged_recommends_close_smaller_side(self):
        cfg = DynamicHedgeConfig(normal_target_min_pct=20, normal_target_max_pct=30)
        out = assess_dynamic_hedge(enabled=True, ownership_state="DYNAMIC_HEDGE_ACTIVE", exposure=exposure(1000, 700), risk=risk(10), config=cfg)
        self.assertEqual(out["engineState"], "HEDGE_REDUCING")
        self.assertEqual(out["recommendedAction"], "CLOSE_SHORT")


if __name__ == "__main__":
    unittest.main()
