from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_multi import _next_trigger, resolve_slot_leverage


class Client:
    def __init__(self, maximum=100): self.maximum=maximum
    def leverage_brackets(self, symbol=None):
        return [{"symbol":symbol or "SOLUSDT","brackets":[{"notionalFloor":"0","notionalCap":"1000000","initialLeverage":str(self.maximum),"maintMarginRatio":"0.01"}]}]


def cfg(**updates):
    raw={"tradingMode":"focus","focusLiveEnabled":True,"focusSelectionMode":"manual","focusManualPair":"SOLUSDT",**updates}
    return Strategy2Config.from_mapping(raw)


def test_multi_focus_slots_validate_and_roundtrip():
    settings=cfg(focusSlots=[
        {"slotId":"s1","pair":"SOLUSDT","side":"LONG","leverageMode":"minimum","leverage":50,"startNotional":100},
        {"slotId":"s2","pair":"BTCUSDT","side":"SHORT","leverageMode":"exact","leverage":75,"startNotional":150},
    ])
    assert len(settings.focus_slots)==2
    assert settings.public_dict()["focusSlots"][1]["side"]=="SHORT"


def test_duplicate_symbol_blocked_because_aster_leverage_is_symbol_wide():
    try:
        cfg(focusSlots=[{"slotId":"a","pair":"BTCUSDT","side":"LONG","leverage":50},{"slotId":"b","pair":"BTCUSDT","side":"SHORT","leverage":100}])
    except ValueError as exc:
        assert "symbol-wide leverage" in str(exc)
    else: raise AssertionError("duplicate symbol should fail")


def test_minimum_50_resolves_to_exchange_max_100():
    settings=cfg()
    effective,maximum=resolve_slot_leverage(Client(100),{"pair":"SOLUSDT","leverageMode":"minimum","leverage":50,"startNotional":100},settings)
    assert (effective,maximum)==(100,100)


def test_minimum_50_rejects_exchange_max_25():
    settings=cfg()
    try: resolve_slot_leverage(Client(25),{"pair":"SOLUSDT","leverageMode":"minimum","leverage":50,"startNotional":100},settings)
    except ValueError as exc: assert "minimum 50x" in str(exc)
    else: raise AssertionError("must reject")


def test_exact_50_stays_50_even_if_exchange_max_100():
    effective,maximum=resolve_slot_leverage(Client(100),{"pair":"SOLUSDT","leverageMode":"exact","leverage":50,"startNotional":100},cfg())
    assert effective==50 and maximum==100


def test_dca_01_percent_is_side_correct():
    settings=cfg(focusDcaDistance=.001,focusMaxDca=100)
    assert abs(_next_trigger(settings,side="LONG",original=100,dca_count=0)-99.9)<1e-9
    assert abs(_next_trigger(settings,side="SHORT",original=100,dca_count=0)-100.1)<1e-9


def test_100_dca_is_valid_for_focus():
    settings=cfg(focusMaxDca=100)
    assert settings.focus_max_dca==100


def test_usdt_tp_requires_positive_target():
    try: cfg(focusTakeProfitMode="usdt",focusTakeProfitUsdt=0)
    except ValueError as exc: assert "USDT-doel" in str(exc)
    else: raise AssertionError("must reject")


def test_multi_focus_source_keeps_queue_priority_and_hedge_correction():
    from pathlib import Path
    source=Path("aster_strategy2_focus_multi.py").read_text()
    assert "configured_slots.sort(key=slot_priority)" in source
    assert '"kind":"FOCUS_HEDGE_CORRECTION"' in source
    assert '"kind":f"FOCUS_SLOT_{_action}"' in source
    assert "remaining-=1" in source


def test_queue_recovery_preserves_multifocus_roles():
    from pathlib import Path
    source=Path("main.py").read_text()
    assert 'FOCUS_SLOT:{slot_id}' in source
    assert 'FOCUS_SLOT_HEDGE:{slot_id}' in source
    assert '"FOCUS_SLOT_DCA"' in source


def test_unlimited_dca_has_no_count_stop_and_keeps_triggering():
    settings=cfg(focusDcaUnlimited=True,focusDcaMode="fixed",focusDcaDistance=.001,focusMaxDca=5)
    assert settings.focus_dca_unlimited is True
    # Well beyond configured max: there is still a valid next trigger.
    assert _next_trigger(settings,side="LONG",original=100,dca_count=1000)>0
    assert _next_trigger(settings,side="SHORT",original=100,dca_count=1000)>100


def test_unlimited_dca_requires_fixed_spacing():
    try: cfg(focusDcaUnlimited=True,focusDcaMode="custom")
    except ValueError as exc: assert "vaste DCA-afstand" in str(exc)
    else: raise AssertionError("unlimited custom ladder must fail")
