"""Build 624: minimale afstand tot het gemiddelde (%) naast k sigma, per kant, gespiegeld voor SHORT."""
import unittest

from aster_extreme_spike_filter import (
    DEFAULT_MIN_DISTANCE_PCT, SpikeFilterRejected, evaluate_spike, spike_band_price,
    spike_settings_from_mapping, validate_side_settings,
)

# Rustige markt: gemiddelde 100, sd 0,2 → 4σ = 0,8 % van het gemiddelde (zoals RENDER 23-10)
CALM = [99.8, 100.2] * 10
# Beweeglijke markt: gemiddelde 100, sd 1 → 4σ = 4 %
WILD = [99.0, 101.0] * 10
LIVE_CLOSE = 1_800_000_000_000


def check(side, closes, price, min_distance):
    return evaluate_spike(side=side, level="4", timeframe="15m", previous_closes=closes,
                          candle_high=price, candle_low=price, candle_close_ms=LIVE_CLOSE,
                          now_ms=LIVE_CLOSE - 60_000, max_staleness_ms=1_200_000,
                          min_distance_pct=min_distance)


class MinDistanceTests(unittest.TestCase):
    def test_calm_market_long_spike_is_blocked_by_min_distance(self):
        check("LONG", CALM, 99.1, 0)  # 4,5σ maar 0,9 % — zonder minimum: instap
        with self.assertRaises(SpikeFilterRejected) as ctx:
            check("LONG", CALM, 99.1, 2.0)
        self.assertEqual(ctx.exception.reason, "SPIKE_BELOW_MIN_DISTANCE")

    def test_calm_market_deep_drop_still_enters(self):
        check("LONG", CALM, 97.9, 2.0)  # 10σ en 2,1 % onder het gemiddelde

    def test_short_is_mirrored(self):
        check("SHORT", CALM, 100.9, 0)
        with self.assertRaises(SpikeFilterRejected) as ctx:
            check("SHORT", CALM, 100.9, 2.0)
        self.assertEqual(ctx.exception.reason, "SPIKE_BELOW_MIN_DISTANCE")
        check("SHORT", CALM, 102.1, 2.0)

    def test_wild_market_sigma_is_the_binding_rule(self):
        with self.assertRaises(SpikeFilterRejected) as ctx:
            check("LONG", WILD, 97.5, 2.0)  # 2,5 % maar pas 2,5σ
        self.assertEqual(ctx.exception.reason, "SPIKE_OUTSIDE_SELECTED_RANGE")
        check("LONG", WILD, 95.9, 2.0)

    def test_realtime_band_uses_farthest_of_both(self):
        self.assertAlmostEqual(spike_band_price(CALM, side="LONG", level="4"), 99.2)
        self.assertAlmostEqual(spike_band_price(CALM, side="LONG", level="4", min_distance_pct=2.0), 98.0)
        self.assertAlmostEqual(spike_band_price(CALM, side="SHORT", level="4", min_distance_pct=2.0), 102.0)
        self.assertAlmostEqual(spike_band_price(WILD, side="LONG", level="4", min_distance_pct=2.0), 96.0)

    def test_settings_default_and_validation(self):
        spike = spike_settings_from_mapping({})
        self.assertEqual(spike["longMinDistancePct"], DEFAULT_MIN_DISTANCE_PCT)
        self.assertEqual(spike["shortMinDistancePct"], DEFAULT_MIN_DISTANCE_PCT)
        spike = spike_settings_from_mapping({"extremeSpikeLongMinDistancePct": 0, "extremeSpikeShortMinDistancePct": 3.5})
        self.assertEqual((spike["longMinDistancePct"], spike["shortMinDistancePct"]), (0.0, 3.5))
        validate_side_settings(spike)
        with self.assertRaises(ValueError):
            validate_side_settings(spike_settings_from_mapping({"extremeSpikeShortMinDistancePct": 25}))

    def test_config_round_trip(self):
        from aster_multi_bb_core import MultiBbConfig
        settings = MultiBbConfig.from_mapping({"entryFilterMode": "EXTREME_SPIKE", "extremeSpikeSettingsVersion": 2,
                                               "extremeSpikeLongMinDistancePct": 1.5, "extremeSpikeShortMinDistancePct": 0})
        self.assertEqual(settings.extreme_spike_long_min_distance_pct, 1.5)
        self.assertEqual(settings.extreme_spike_short_min_distance_pct, 0.0)
        mapped = settings.public_dict()
        self.assertEqual(mapped["extremeSpikeLongMinDistancePct"], 1.5)
        self.assertEqual(mapped["extremeSpikeShortMinDistancePct"], 0.0)


class RealtimeWatchTests(unittest.TestCase):
    def test_watch_reads_min_distance(self):
        from aster_spike_realtime import watch_from_control
        watch = watch_from_control("u1", {"enabled": True, "multiBbReport": {"spikeWatch": {
            "symbols": ["BTCUSDT"], "level": "4", "longTimeframe": "15m", "shortTimeframe": "15m",
            "longEnabled": True, "shortEnabled": True, "updatedAtMs": LIVE_CLOSE,
            "longMinDistancePct": 2.0, "shortMinDistancePct": 1.0}}}, now_ms=LIVE_CLOSE)
        self.assertEqual((watch.long_min_distance_pct, watch.short_min_distance_pct), (2.0, 1.0))


if __name__ == "__main__":
    unittest.main()
