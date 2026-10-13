import unittest
from aster_extreme_spike_filter import evaluate_spike, SpikeFilterRejected, normalize_mode,validate_settings
class SpikeTests(unittest.TestCase):
    def setUp(self):
        self.closes=[100.0 + (i%2)*2 for i in range(20)]
        self.base=dict(side="LONG",level="5-6",timeframe="15m",previous_closes=self.closes,candle_high=102,candle_low=95.5,candle_close_ms=10000,now_ms=11000,max_staleness_ms=2000)
    def test_sigma_band(self):
        out=evaluate_spike(**self.base)
        self.assertAlmostEqual(out.score,5.5)
        self.assertGreater(out.overshoot_pct,0)
    def test_long_short_symmetry(self):
        obj=dict(self.base,side="SHORT",candle_low=100,candle_high=106.5)
        self.assertAlmostEqual(evaluate_spike(**obj).score,5.5)
    def test_level_edges(self):
        for level,price in (("2-3",98.5),("3-4",97.5),("4-5",96.5),("6-7",94.5),("7+",93.5)):
            self.assertEqual(evaluate_spike(**dict(self.base,level=level,candle_low=price)).level,level)
    def test_fail_closed(self):
        cases=[dict(candle_close_ms=12000),dict(candle_close_ms=1),dict(previous_closes=[100]),dict(candle_low=0),dict(level="unknown"),dict(candle_low=99)]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(SpikeFilterRejected):
                evaluate_spike(**dict(self.base,**change))
    def test_legacy_mode(self):
        self.assertEqual(normalize_mode(None,True),"BOLLINGER")
        self.assertEqual(normalize_mode(None,False),"OFF")
    def test_mutual_exclusion(self):
        with self.assertRaises(ValueError):
            validate_settings(mode="EXTREME_SPIKE",level="5-6",long_tf="1m",short_tf="15m",legacy_bb_enabled=True)
        with self.assertRaises(ValueError):
            validate_settings(mode="BOLLINGER",level="5-6",long_tf="1m",short_tf="15m",legacy_bb_enabled=False)
        validate_settings(mode="EXTREME_SPIKE",level="5-6",long_tf="1m",short_tf="4h",legacy_bb_enabled=False)
if __name__=="__main__": unittest.main()
