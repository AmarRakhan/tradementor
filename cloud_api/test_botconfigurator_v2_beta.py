import unittest

from aster_multi_bb_core import (
    MultiBbConfig,
    _effective_entry_timeframe,
    _exposure_refill_context,
)


class BotConfiguratorV2BetaRuntimeTests(unittest.TestCase):
    def test_legacy_defaults_remain_unchanged(self):
        cfg = MultiBbConfig.from_mapping({
            "engine": "multi_bb_v1",
            "universeTopN": 30,
            "maximumPositions": 2,
            "longSlots": 1,
            "shortSlots": 1,
            "minimumLeverage": 50,
            "entryMarginUsd": 1,
            "entryNotionalUsd": 50,
            "dcaMarginUsd": 1,
            "dcaDistance": .10,
            "takeProfit": .015,
        })
        self.assertFalse(cfg.directional_bollinger_enabled)
        self.assertFalse(cfg.exposure_refill_enabled)
        self.assertEqual(cfg.bollinger_entry_filter_timeframe, "15m")

    def test_short_heavy_exposure_activates_long_fast_refill(self):
        cfg = MultiBbConfig.from_mapping({
            "engine": "multi_bb_v1",
            "universeTopN": 30,
            "maximumPositions": 2,
            "longSlots": 1,
            "shortSlots": 1,
            "minimumLeverage": 50,
            "entryMarginUsd": 1,
            "entryNotionalUsd": 50,
            "dcaMarginUsd": 1,
            "dcaDistance": .10,
            "takeProfit": .015,
            "bollingerEntryFilter15mEnabled": True,
            "directionalBollingerEnabled": True,
            "bollingerLongTimeframe": "15m",
            "bollingerShortTimeframe": "15m",
            "exposureRefillEnabled": True,
            "exposureRefillLongTimeframe": "1m",
            "exposureRefillShortTimeframe": "1m",
            "exposureRefillTriggerPercent": 20,
            "exposureRefillReleasePercent": 8,
        })
        positions = [
            {"positionSide": "LONG", "positionAmt": "4", "markPrice": "100"},
            {"positionSide": "SHORT", "positionAmt": "6", "markPrice": "100"},
        ]
        exposure = _exposure_refill_context(cfg, positions, {})
        self.assertEqual(exposure["activeSide"], "LONG")
        self.assertEqual(_effective_entry_timeframe(cfg, "LONG", exposure), "1m")
        self.assertEqual(_effective_entry_timeframe(cfg, "SHORT", exposure), "15m")

    def test_hysteresis_keeps_refill_until_release_threshold(self):
        cfg = MultiBbConfig.from_mapping({
            "engine": "multi_bb_v1",
            "universeTopN": 30,
            "maximumPositions": 2,
            "longSlots": 1,
            "shortSlots": 1,
            "minimumLeverage": 50,
            "entryMarginUsd": 1,
            "entryNotionalUsd": 50,
            "dcaMarginUsd": 1,
            "dcaDistance": .10,
            "takeProfit": .015,
            "exposureRefillEnabled": True,
            "exposureRefillTriggerPercent": 20,
            "exposureRefillReleasePercent": 8,
        })
        positions = [
            {"positionSide": "LONG", "positionAmt": "45", "markPrice": "10"},
            {"positionSide": "SHORT", "positionAmt": "55", "markPrice": "10"},
        ]
        exposure = _exposure_refill_context(cfg, positions, {"exposureRefillSide": "LONG"})
        self.assertEqual(exposure["activeSide"], "LONG")


if __name__ == "__main__":
    unittest.main()
