import unittest
from aster_multi_bb_core import MultiBbConfig

class ExtremeSpikeConfigTests(unittest.TestCase):
    def base(self):
        return {"universeTopN":350,"maximumPositions":125,"longSlots":63,"shortSlots":62,"minimumLeverage":20,"maximumLeverage":20,"bollingerEntryFilter15mEnabled":True}
    def test_legacy_settings_preserve_bollinger(self):
        c=MultiBbConfig.from_mapping(self.base())
        self.assertEqual(c.entry_filter_mode,"BOLLINGER")
        self.assertTrue(c.bollinger_entry_filter_15m_enabled)
        self.assertEqual(c.public_dict()["entryFilterMode"],"BOLLINGER")
    def test_legacy_off(self):
        raw=self.base();raw["bollingerEntryFilter15mEnabled"]=False
        self.assertEqual(MultiBbConfig.from_mapping(raw).entry_filter_mode,"OFF")
    def test_extreme_spike_valid_and_roundtrip(self):
        raw=self.base()
        raw.update(entryFilterMode="EXTREME_SPIKE",bollingerEntryFilter15mEnabled=False,extremeSpikeLevel="5-6",extremeSpikeLongTimeframe="1m",extremeSpikeShortTimeframe="4h")
        obj=MultiBbConfig.from_mapping(raw)
        self.assertEqual(MultiBbConfig.from_mapping(obj.public_dict()).entry_filter_mode,"EXTREME_SPIKE")
        self.assertEqual(obj.extreme_spike_short_timeframe,"4h")
    def test_concurrent_filters_rejected(self):
        raw=self.base();raw["entryFilterMode"]="EXTREME_SPIKE"
        with self.assertRaises(ValueError): MultiBbConfig.from_mapping(raw)
    def test_invalid_level_rejected(self):
        raw=self.base();raw.update(entryFilterMode="EXTREME_SPIKE",bollingerEntryFilter15mEnabled=False,extremeSpikeLevel="9-10")
        with self.assertRaises(ValueError): MultiBbConfig.from_mapping(raw)
if __name__=="__main__": unittest.main()
