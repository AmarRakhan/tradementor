"""Read-only regression characterization for Extreme Spike rollout zone safety.

This test does not modify account data or send any exchange orders.
It establishes why a rollout must not silently reinterpret legacy and
canonical price-zone switches when they disagree.
"""
import unittest
from aster_multi_bb_core import MultiBbConfig


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
