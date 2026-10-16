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
    def test_saved_mode_transitions_do_not_change_trading_controls(self):
        raw=self.base()
        raw.update(name="Existing bot",takeProfitMode="PORTFOLIO",portfolioTpValue=0.5,
                   longDcaDistance=0.003,shortDcaDistance=0.005,
                   priceZoneSeats={"enabled":True,"longSeatsPerZone":2,"shortSeatsPerZone":0})
        snapshots=[]
        for mode in ("OFF","EXTREME_SPIKE","BOLLINGER","OFF"):
            settings=dict(raw,entryFilterMode=mode,bollingerEntryFilter15mEnabled=(mode=="BOLLINGER"),
                          extremeSpikeLevel="5-6",extremeSpikeLongTimeframe="1m",
                          extremeSpikeShortTimeframe="15m")
            config=MultiBbConfig.from_mapping(settings)
            persisted=config.public_dict()
            restarted=MultiBbConfig.from_mapping(persisted)
            self.assertEqual(restarted.entry_filter_mode,mode)
            self.assertEqual(restarted.extreme_spike_long_timeframe,"1m")
            self.assertEqual(restarted.extreme_spike_short_timeframe,"15m")
            self.assertEqual(restarted.name,"Existing bot")
            snapshots.append(persisted)
        for previous,current in zip(snapshots,snapshots[1:]):
            for field in ("name","maximumPositions","longSlots","shortSlots",
                          "takeProfitMode","portfolioTpValue","priceZoneSeats"):
                self.assertEqual(previous.get(field),current.get(field),field)


    def test_mock_backend_patch_preserves_unmentioned_settings(self):
        old = self.base()
        old.update(
            entryFilterMode="EXTREME_SPIKE", bollingerEntryFilter15mEnabled=False,
            extremeSpikeLevel="5-6", extremeSpikeLongTimeframe="1m",
            extremeSpikeShortTimeframe="15m", takeProfitMode="TRADE",
            takeProfit=0.015, priceZoneSeats={"enabled": True, "longSeatsPerZone": 2, "shortSeatsPerZone": 0},
            directionalBollingerEnabled=True, bollingerLongTimeframe="1m",
            bollingerShortTimeframe="1m",
        )
        for patch in (
            {"takeProfit": 0.02},
            {"maximumPositions": 130},
            {"bollingerLongTimeframe": "15m"},
        ):
            candidate = MultiBbConfig.from_mapping({**old, **patch})
            saved = candidate.public_dict()
            assert saved["entryFilterMode"] == "EXTREME_SPIKE"
            assert saved["bollingerEntryFilter15mEnabled"] is False
            assert saved["priceZoneSeats"]["enabled"] is True
            assert saved["priceZoneSeats"]["shortSeatsPerZone"] == 0
            assert saved["extremeSpikeLevel"] == "5-6"
            assert saved["takeProfit"] == patch.get("takeProfit", old["takeProfit"])
            assert saved["bollingerLongTimeframe"] == patch.get("bollingerLongTimeframe", "1m")

    def test_mock_backend_rejects_stale_bollinger_switch_during_spike(self):
        old = self.base()
        old.update(entryFilterMode="EXTREME_SPIKE", bollingerEntryFilter15mEnabled=False)
        with self.assertRaises(ValueError):
            MultiBbConfig.from_mapping({**old, "bollingerEntryFilter15mEnabled": True})

if __name__=="__main__": unittest.main()
