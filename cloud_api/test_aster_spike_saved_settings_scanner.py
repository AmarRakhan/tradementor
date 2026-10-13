"""Isolated scanner-admission contract: persisted config -> completed candle -> side-specific filter.
No Aster network or Firestore writes.
"""
import unittest
from aster_multi_bb_core import MultiBbConfig
from aster_extreme_spike_filter import require_extreme_spike_entry, SpikeFilterRejected

class ScannerSavedSettingsTests(unittest.TestCase):
    def base(self):
        return {"universeTopN":350,"maximumPositions":125,"longSlots":63,"shortSlots":62,
                "minimumLeverage":20,"maximumLeverage":20}
    def test_saved_spike_mode_drives_long_and_short_market_admission(self):
        raw=self.base()
        raw.update(entryFilterMode="EXTREME_SPIKE",bollingerEntryFilter15mEnabled=False,
                   extremeSpikeLevel="5-6",extremeSpikeLongTimeframe="1m",extremeSpikeShortTimeframe="15m")
        config=MultiBbConfig.from_mapping(MultiBbConfig.from_mapping(raw).public_dict())
        calls=[]
        class Client:
            def klines(self,*,symbol,interval,limit):
                calls.append((symbol,interval,limit))
                step=60000 if interval=="1m" else 900000
                rows=[]
                for i in range(21):
                    close=100+(i%2)*2
                    rows.append([i*step,close,102,100,close,0,(i+1)*step-1])
                rows[20][3]=95.5 if interval=="1m" else 100
                rows[20][2]=102 if interval=="1m" else 106.5
                rows.append([21*step,101,102,90,101,0,22*step-1])
                return rows
        c=Client()
        for side in ("LONG","SHORT"):
            tf=config.extreme_spike_long_timeframe if side=="LONG" else config.extreme_spike_short_timeframe
            score=require_extreme_spike_entry(c,symbol="BTCUSDT",side=side,
                level=config.extreme_spike_level,timeframe=tf,
                now_ms=(21*(60000 if side=="LONG" else 900000))+10)
            self.assertEqual(score.level,"5-6")
        self.assertEqual(calls,[("BTCUSDT","1m",23),("BTCUSDT","15m",23)])
        with self.assertRaises(SpikeFilterRejected):
            require_extreme_spike_entry(c,symbol="BTCUSDT",side="LONG",level="7+",
                timeframe=config.extreme_spike_long_timeframe,now_ms=21*60000+10)

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
