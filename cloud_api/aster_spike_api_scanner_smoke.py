"""Read a settings payload from stdin, execute the real scanner in dry_run.
Only isolated mocks; no credentials, user account, network or order calls.
"""
import json,sys
from types import SimpleNamespace
from unittest.mock import patch
from aster_multi_bb_core import MultiBbConfig,run_multi_bb_step
from test_aster_spike_real_scanner_dry_run import FakeClient,Ref

def main():
    settings=MultiBbConfig.from_mapping(json.load(sys.stdin))
    client=FakeClient()
    plan=SimpleNamespace(leverage=20,notional_per_leg=20,quantity=.2)
    with patch("aster_multi_bb_core.rank_top_volume",return_value=[{"symbol":"BTCUSDT","quoteVolume":1000000}]), \
         patch("aster_multi_bb_core.max_contract_leverage",return_value=20), \
         patch("aster_multi_bb_core._plan_new",return_value=(plan,{"exchangeMaxLeverage":20,"forcedBelowConfiguredMinimum":False})):
        output=run_multi_bb_step(client=client,ref=Ref(),raw_state={},settings=settings,
           uid="isolated-api-scanner-test",account={"availableBalance":100,"totalMarginBalance":100},
           positions=[],open_orders=[],timestamp_ms=21*60000+10,dry_run=True,order_budget=1)
    assert output["ordersSent"]==0
    assert "1m" in client.intervals
    assert any(a.get("kind")=="ENTRY" and a.get("side")=="LONG" for a in output["actions"]),output["actions"]
    print("PASS: actual API-persisted Spike settings -> real scanner LONG 1m candidate, zero writes/orders")
if __name__=="__main__":main()
