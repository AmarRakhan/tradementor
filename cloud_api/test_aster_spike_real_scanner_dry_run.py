"""Exercise the REAL run_multi_bb_step candidate scan safely with deterministic candles.

No credentials, Firestore writes, leverage adjustments or exchange orders.
The executor path is separately tested because dry_run intentionally bypasses it.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from aster_multi_bb_core import MultiBbConfig, run_multi_bb_step

class Ref:
    def set(self,*args,**kwargs): raise AssertionError("dry-run must never write")
    def collection(self,*args,**kwargs): raise AssertionError("dry-run must never write")

class FakeClient:
    # Spike 1.1: de scanner-ticker is de actuele prijs tijdens de lopende candle.
    def __init__(self,price="101"):
        self.intervals=[]
        self.price=price
    def public_exchange_info(self):
        return {"symbols":[{"symbol":"BTCUSDT","status":"TRADING","quoteAsset":"USDT"}]}
    def ticker_prices(self):
        return [{"symbol":"BTCUSDT","price":self.price}]
    def ticker_24h(self):
        return [{"symbol":"BTCUSDT","quoteVolume":"1000000"}]
    def leverage_brackets(self,symbol):
        return []
    def klines(self,*,symbol,interval,limit):
        self.intervals.append(interval)
        step={"1m":60000,"15m":900000}[interval]
        rows=[]
        for i in range(21):
            price=100+(i%2)*2
            rows.append([i*step,price,102,100,price,0,(i+1)*step-1])
        rows[20][3]=100
        rows[20][2]=102
        rows.append([21*step,101,110,90,95.5 if interval=="1m" else 106.5,0,22*step-1])
        return rows
    def __getattr__(self,name):
        raise AssertionError("Unexpected exchange interaction: "+name)

class ScannerDryRunTests(unittest.TestCase):
    def setUp(self):
        from aster_extreme_spike_filter import clear_reference_cache
        clear_reference_cache()
        if hasattr(super(), 'setUp'): super().setUp()
    def test_real_scanner_uses_saved_spike_settings_without_order(self):
        settings=MultiBbConfig.from_mapping({
           "universeTopN":1,"maximumPositions":1,"longSlots":1,"shortSlots":0,
           "minimumLeverage":20,"maximumLeverage":20,
           "entryFilterMode":"EXTREME_SPIKE","extremeSpikeSettingsVersion":2,"bollingerEntryFilter15mEnabled":False,
           "extremeSpikeLevel":"5-6","extremeSpikeLongTimeframe":"1m",
           "extremeSpikeShortTimeframe":"15m"})
        settings=MultiBbConfig.from_mapping(settings.public_dict())
        client=FakeClient("95.5")
        plan=SimpleNamespace(leverage=20,notional_per_leg=20,quantity=.2)
        with patch("aster_multi_bb_core.rank_top_volume",return_value=[{"symbol":"BTCUSDT","quoteVolume":1000000}]), \
             patch("aster_multi_bb_core.max_contract_leverage",return_value=20), \
             patch("aster_multi_bb_core._plan_new",return_value=(plan,{"exchangeMaxLeverage":20,"forcedBelowConfiguredMinimum":False})):
            result=run_multi_bb_step(client=client,ref=Ref(),raw_state={},settings=settings,
                uid="test-only",account={"availableBalance":100,"totalMarginBalance":100},
                positions=[],open_orders=[],timestamp_ms=21*60000+10,dry_run=True,
                order_budget=1)
        self.assertEqual(result["status"],"simulated")
        self.assertEqual(result["ordersSent"],0)
        self.assertIn("1m",client.intervals)
        self.assertTrue(any(a.get("kind")=="ENTRY" for a in result["actions"]),result["actions"])

    def test_real_scanner_short_15m_spike_without_order(self):
        settings=MultiBbConfig.from_mapping({
           "universeTopN":1,"maximumPositions":1,"longSlots":0,"shortSlots":1,
           "minimumLeverage":20,"maximumLeverage":20,
           "entryFilterMode":"EXTREME_SPIKE","extremeSpikeSettingsVersion":2,"bollingerEntryFilter15mEnabled":False,
           "extremeSpikeLevel":"5-6","extremeSpikeLongTimeframe":"1m",
           "extremeSpikeShortTimeframe":"15m","extremeSpikeShortEnabled":True})
        client=FakeClient("106.5")
        plan=SimpleNamespace(leverage=20,notional_per_leg=20,quantity=.2)
        with patch("aster_multi_bb_core.rank_top_volume",return_value=[{"symbol":"BTCUSDT","quoteVolume":1000000}]), \
             patch("aster_multi_bb_core.max_contract_leverage",return_value=20), \
             patch("aster_multi_bb_core._plan_new",return_value=(plan,{"exchangeMaxLeverage":20,"forcedBelowConfiguredMinimum":False})):
            result=run_multi_bb_step(client=client,ref=Ref(),raw_state={},settings=settings,
                uid="test-only",account={"availableBalance":100,"totalMarginBalance":100},
                positions=[],open_orders=[],timestamp_ms=21*900000+10,dry_run=True,
                order_budget=1)
        self.assertEqual(result["ordersSent"],0)
        self.assertIn("15m",client.intervals)
        self.assertTrue(any(a.get("kind")=="ENTRY" and a.get("side")=="SHORT" for a in result["actions"]),result["actions"])

    def test_real_scanner_rejects_nonmatching_sigma_without_order(self):
        settings=MultiBbConfig.from_mapping({
           "universeTopN":1,"maximumPositions":1,"longSlots":1,"shortSlots":0,
           "minimumLeverage":20,"maximumLeverage":20,
           "entryFilterMode":"EXTREME_SPIKE","extremeSpikeSettingsVersion":2,"bollingerEntryFilter15mEnabled":False,
           "extremeSpikeLevel":"7+","extremeSpikeLongTimeframe":"1m",
           "extremeSpikeShortTimeframe":"15m"})
        client=FakeClient("95.5")
        with patch("aster_multi_bb_core.rank_top_volume",return_value=[{"symbol":"BTCUSDT","quoteVolume":1000000}]), \
             patch("aster_multi_bb_core.max_contract_leverage",return_value=20):
            result=run_multi_bb_step(client=client,ref=Ref(),raw_state={},settings=settings,
                uid="test-only",account={"availableBalance":100,"totalMarginBalance":100},
                positions=[],open_orders=[],timestamp_ms=21*60000+10,dry_run=True,
                order_budget=1)
        self.assertEqual(result["ordersSent"],0)
        self.assertFalse(any(a.get("kind")=="ENTRY" for a in result["actions"]),result["actions"])
        self.assertTrue(any(a.get("reason")=="SPIKE_OUTSIDE_SELECTED_RANGE" for a in result["actions"]),result["actions"])
        # Build 618: wachten op een spike is geen orderfout.
        self.assertEqual(result["entryStatus"],"WAITING_SPIKE_ENTRY")
        self.assertTrue(result["entryReason"].startswith("Wacht op spike"),result["entryReason"])



class SpikeSideToggleTests(unittest.TestCase):
    def setUp(self):
        from aster_extreme_spike_filter import clear_reference_cache
        clear_reference_cache()
        if hasattr(super(), 'setUp'): super().setUp()
    """Spike 1.1: LONG en SHORT apart aan/uit; een uitgezette kant opent niets."""
    def run_short(self, short_enabled):
        settings=MultiBbConfig.from_mapping({
           "universeTopN":1,"maximumPositions":1,"longSlots":0,"shortSlots":1,
           "minimumLeverage":20,"maximumLeverage":20,
           "entryFilterMode":"EXTREME_SPIKE","extremeSpikeSettingsVersion":2,"bollingerEntryFilter15mEnabled":False,
           "extremeSpikeLevel":"5","extremeSpikeShortTimeframe":"15m",
           "extremeSpikeShortEnabled":short_enabled})
        client=FakeClient("106.5")
        plan=SimpleNamespace(leverage=20,notional_per_leg=20,quantity=.2)
        with patch("aster_multi_bb_core.rank_top_volume",return_value=[{"symbol":"BTCUSDT","quoteVolume":1000000}]), \
             patch("aster_multi_bb_core.max_contract_leverage",return_value=20), \
             patch("aster_multi_bb_core._plan_new",return_value=(plan,{"exchangeMaxLeverage":20,"forcedBelowConfiguredMinimum":False})):
            return run_multi_bb_step(client=client,ref=Ref(),raw_state={},settings=settings,
                uid="test-only",account={"availableBalance":100,"totalMarginBalance":100},
                positions=[],open_orders=[],timestamp_ms=21*900000+10,dry_run=True,order_budget=1)
    def test_short_disabled_blocks_short_spike(self):
        result=self.run_short(False)
        self.assertFalse(any(a.get("kind")=="ENTRY" for a in result["actions"]),result["actions"])
        self.assertTrue(any(a.get("reason")=="SPIKE_SIDE_DISABLED" for a in result["actions"]),result["actions"])
    def test_short_enabled_allows_short_spike(self):
        result=self.run_short(True)
        self.assertTrue(any(a.get("kind")=="ENTRY" and a.get("side")=="SHORT" for a in result["actions"]),result["actions"])
    def test_defaults_long_on_short_off_15m_level_5(self):
        cfg=MultiBbConfig.from_mapping({"universeTopN":1,"maximumPositions":2,"longSlots":1,"shortSlots":1,
           "minimumLeverage":20,"maximumLeverage":20,"entryFilterMode":"EXTREME_SPIKE"})
        self.assertEqual((cfg.extreme_spike_level,cfg.extreme_spike_long_timeframe,cfg.extreme_spike_short_timeframe),("5","15m","15m"))
        self.assertTrue(cfg.extreme_spike_long_enabled)
        self.assertFalse(cfg.extreme_spike_short_enabled)

if __name__=="__main__":unittest.main()
