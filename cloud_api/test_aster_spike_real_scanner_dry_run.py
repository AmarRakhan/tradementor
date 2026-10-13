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
    def __init__(self):
        self.intervals=[]
    def public_exchange_info(self):
        return {"symbols":[{"symbol":"BTCUSDT","status":"TRADING","quoteAsset":"USDT"}]}
    def ticker_prices(self):
        return [{"symbol":"BTCUSDT","price":"101"}]
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
        rows[20][3]=95.5
        rows.append([21*step,101,102,90,101,0,22*step-1])
        return rows
    def __getattr__(self,name):
        raise AssertionError("Unexpected exchange interaction: "+name)

class ScannerDryRunTests(unittest.TestCase):
    def test_real_scanner_uses_saved_spike_settings_without_order(self):
        settings=MultiBbConfig.from_mapping({
           "universeTopN":1,"maximumPositions":1,"longSlots":1,"shortSlots":0,
           "minimumLeverage":20,"maximumLeverage":20,
           "entryFilterMode":"EXTREME_SPIKE","bollingerEntryFilter15mEnabled":False,
           "extremeSpikeLevel":"5-6","extremeSpikeLongTimeframe":"1m",
           "extremeSpikeShortTimeframe":"15m"})
        settings=MultiBbConfig.from_mapping(settings.public_dict())
        client=FakeClient()
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

if __name__=="__main__":unittest.main()
