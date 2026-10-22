"""Isolated scanner-admission contract: persisted config -> live price vs 20 completed candles -> side-specific filter.
No Aster network or Firestore writes.
"""
import unittest
from aster_multi_bb_core import MultiBbConfig
from aster_extreme_spike_filter import require_extreme_spike_entry, SpikeFilterRejected

class ScannerSavedSettingsTests(unittest.TestCase):
    def setUp(self):
        from aster_extreme_spike_filter import clear_reference_cache
        clear_reference_cache()
        if hasattr(super(), 'setUp'): super().setUp()
    def base(self):
        return {"universeTopN":350,"maximumPositions":125,"longSlots":63,"shortSlots":62,
                "minimumLeverage":20,"maximumLeverage":20}
    def test_saved_spike_mode_drives_long_and_short_market_admission(self):
        raw=self.base()
        raw.update(entryFilterMode="EXTREME_SPIKE",extremeSpikeSettingsVersion=2,bollingerEntryFilter15mEnabled=False,
                   extremeSpikeLevel="5-6",extremeSpikeLongTimeframe="1m",extremeSpikeShortTimeframe="15m")
        config=MultiBbConfig.from_mapping(MultiBbConfig.from_mapping(raw).public_dict())
        calls=[]
        class Client:
            def klines(self,*,symbol,interval,limit):
                calls.append((symbol,interval,limit))
                step=60000 if interval=="1m" else 900000
                # 21 afgesloten candles + de lopende candle (sluit in de toekomst).
                rows=[[i*step,100+(i%2)*2,102,100,100+(i%2)*2,0,(i+1)*step-1] for i in range(22)]
                rows.append([22*step,101,102,90,101,0,23*step-1])
                return rows
        c=Client()
        # Spike 1.1: de actuele prijs tijdens de lopende candle telt, niet een oude wick.
        for side,live in (("LONG",95.5),("SHORT",106.5)):
            tf=config.extreme_spike_long_timeframe if side=="LONG" else config.extreme_spike_short_timeframe
            step=60000 if tf=="1m" else 900000
            found=require_extreme_spike_entry(c,symbol="BTCUSDT",side=side,
                level=config.extreme_spike_level,timeframe=tf,
                now_ms=22*step+10,live_price=live)
            self.assertEqual(found.level,"5")
        self.assertEqual(calls,[("BTCUSDT","1m",23),("BTCUSDT","15m",23)])
        with self.assertRaises(SpikeFilterRejected):
            require_extreme_spike_entry(c,symbol="BTCUSDT",side="LONG",level="7",
                timeframe=config.extreme_spike_long_timeframe,now_ms=22*60000+10,live_price=95.5)

    def test_off_mode_never_invokes_spike_market_adapter(self):
        raw=self.base()
        raw.update(entryFilterMode="OFF",bollingerEntryFilter15mEnabled=False)
        config=MultiBbConfig.from_mapping(MultiBbConfig.from_mapping(raw).public_dict())
        self.assertEqual(config.entry_filter_mode,"OFF")
        self.assertFalse(config.bollinger_entry_filter_15m_enabled)

    def test_legacy_bollinger_mode_retains_existing_admission(self):
        raw=self.base()
        raw.update(bollingerEntryFilter15mEnabled=True)
        config=MultiBbConfig.from_mapping(MultiBbConfig.from_mapping(raw).public_dict())
        self.assertEqual(config.entry_filter_mode,"BOLLINGER")
        self.assertTrue(config.bollinger_entry_filter_15m_enabled)

if __name__=="__main__":unittest.main()
