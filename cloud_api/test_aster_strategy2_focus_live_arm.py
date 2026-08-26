from pathlib import Path
from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_live import run_focus_live_step

class Ref:
    def set(self,*_a,**_k): raise AssertionError("unarmed Focus must not mutate or order")

def test_focus_live_is_unarmed_by_default_for_existing_shadow_accounts():
    config=Strategy2Config.from_mapping({"tradingMode":"focus","mode":"live"})
    assert config.focus_live_enabled is False
    assert config.public_dict()["focusLiveEnabled"] is False
    assert run_focus_live_step(client=object(),ref=Ref(),raw_state={},settings=config,uid="u",account={},positions=[],timestamp_ms=1) is None

def test_only_confirmed_start_endpoint_arms_focus_live():
    source=Path(__file__).with_name("main.py").read_text()
    assert 'settings=replace(settings,focus_live_enabled=bool(settings.trading_mode=="focus" and settings.mode=="live"))' in source
    assert 'incoming["focusLiveEnabled"]=bool(old.get("focusLiveEnabled",False))' in source
