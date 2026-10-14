"""Read-only regression characterization for Extreme Spike rollout zone safety.

This test does not modify account data or send any exchange orders.
It establishes why a rollout must not silently reinterpret legacy and
canonical price-zone switches when they disagree.
"""
import unittest
from aster_multi_bb_core import MultiBbConfig
from pathlib import Path
import ast


class ZoneConfigurationRegressionCharacterization(unittest.TestCase):
    def test_conflicting_price_zone_flags_are_not_equivalent(self):
        raw = {
            "zoneSoldiersEnabled": True,
            "zoneSoldiersOptInVersion": 1,
            "priceZoneSeats": {
                "enabled": False,
                "longSeatsPerZone": 2,
                "shortSeatsPerZone": 0,
            },
        }
        parsed = MultiBbConfig.from_mapping(raw)
        # Characterization of the actual release-code precedence. This
        # disagreement is unsafe to auto-reconcile without an authoritative
        # persisted configuration/version. The release gate must flag it.
        self.assertTrue(raw["zoneSoldiersEnabled"])
        self.assertFalse(parsed.zone_soldiers_enabled)
        self.assertNotEqual(
            raw["zoneSoldiersEnabled"], parsed.zone_soldiers_enabled,
            "Conflicting legacy/canonical flags should be visible to the gate",
        )

    def test_missing_zone_must_not_be_implicitly_converted_to_zero(self):
        source = (Path(__file__).parent / "aster_multi_bb_core.py").read_text()
        self.assertIn('active_zone_value = _i(active_zone_raw) if active_zone_raw is not None else None', source)
        self.assertIn('active_zone_value=_i(active_zone_raw) if active_zone_raw is not None else None', source)
        self.assertIn('if active_zone_value is not None else {}', source)

    def test_backend_explicit_zone_opt_in_uses_canonical_when_present(self):
        # Extract only the pure helper to avoid importing the live API module.
        source = (Path(__file__).parent / "main.py").read_text()
        module = ast.parse(source)
        fn = next(node for node in module.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_explicit_zone_soldier_opt_in")
        ns = {"Any": object, "safe_float": lambda value: float(value or 0)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<zone-opt-in>", "exec"), ns)
        enabled = ns["_explicit_zone_soldier_opt_in"]
        self.assertTrue(enabled({"priceZoneSeats": {"enabled": True}}))
        self.assertFalse(enabled({"priceZoneSeats": {"enabled": False},
                                  "zoneSoldiersEnabled": True, "zoneSoldiersOptInVersion": 1}))
        self.assertTrue(enabled({"zoneSoldiersEnabled": True, "zoneSoldiersOptInVersion": 1}))
        self.assertFalse(enabled({"zoneSoldiersEnabled": True, "zoneSoldiersOptInVersion": 0}))

    def test_matching_flags_preserve_price_zone_mode(self):
        raw = {
            "zoneSoldiersEnabled": True,
            "zoneSoldiersOptInVersion": 1,
            "priceZoneSeats": {
                "enabled": True,
                "longSeatsPerZone": 2,
                "shortSeatsPerZone": 0,
            },
        }
        parsed = MultiBbConfig.from_mapping(raw)
        self.assertTrue(parsed.zone_soldiers_enabled)
        self.assertEqual(parsed.zone_base_long_soldiers, 2)
        self.assertEqual(parsed.zone_base_short_soldiers, 0)


if __name__ == "__main__":
    unittest.main()
