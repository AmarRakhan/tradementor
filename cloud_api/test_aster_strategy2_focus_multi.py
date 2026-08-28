from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_multi import _cycle_dca_policy, _migrate_legacy_focus_leg, _next_trigger, resolve_slot_leverage
from aster_strategy2_state import OwnedLeg


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


def test_legacy_single_focus_ownership_migrates_to_matching_slot_only():
    legacy=OwnedLeg("aster-strategy-2","strategy2","SOLUSDT","LONG","focus-cycle",1,9.0,108.0133,5,"FOCUS",created_at_ms=1000,last_order_at_ms=2000)
    raw={"focusLiveState":{"activePair":"SOLUSDT","cycleId":"focus-cycle","originalEntry":108.99,"openedAt":1000,"dcaCount":5}}
    row={"symbol":"SOLUSDT","positionSide":"LONG","positionAmt":"9","entryPrice":"108.0133","markPrice":"106.9"}
    owned,migrated,state=_migrate_legacy_focus_leg([legacy],raw,slot_id="slot-1",symbol="SOLUSDT",side="LONG",row=row,timestamp_ms=3000)
    assert migrated is not None
    assert migrated.role=="FOCUS_SLOT:slot-1"
    assert migrated.cycle_id=="focus-cycle" and migrated.dca_count==5
    assert migrated.quantity==9.0 and migrated.weighted_entry==108.0133
    assert owned[0].role=="FOCUS_SLOT:slot-1" and state["originalEntry"]==108.99


def test_legacy_single_focus_migration_fails_closed_on_cycle_or_pair_mismatch():
    legacy=OwnedLeg("aster-strategy-2","strategy2","SOLUSDT","LONG","focus-cycle",1,9.0,108.0133,5,"FOCUS")
    row={"symbol":"SOLUSDT","positionSide":"LONG","positionAmt":"9","entryPrice":"108.0133"}
    for raw,symbol in (({"focusLiveState":{"activePair":"SOLUSDT","cycleId":"other-cycle"}},"SOLUSDT"),({"focusLiveState":{"activePair":"BTCUSDT","cycleId":"focus-cycle"}},"SOLUSDT")):
        owned,migrated,_=_migrate_legacy_focus_leg([legacy],raw,slot_id="slot-1",symbol=symbol,side="LONG",row=row,timestamp_ms=3000)
        assert migrated is None and owned[0].role=="FOCUS"


def test_existing_position_keeps_actual_leverage_when_minimum_is_satisfied():
    settings=cfg()
    slot={"pair":"SOLUSDT","leverageMode":"minimum","leverage":50,"startNotional":100}
    assert resolve_slot_leverage(Client(100),slot,settings,existing_leverage=50)==(50,100)
    assert resolve_slot_leverage(Client(100),slot,settings,existing_leverage=75)==(75,100)


def test_existing_position_below_minimum_is_blocked_without_rewriting():
    settings=cfg()
    slot={"pair":"SOLUSDT","leverageMode":"minimum","leverage":50,"startNotional":100}
    try: resolve_slot_leverage(Client(100),slot,settings,existing_leverage=25)
    except ValueError as exc: assert "onder minimum 50x" in str(exc)
    else: raise AssertionError("existing leverage below minimum must fail")


def test_existing_exact_position_must_already_match_exact_leverage():
    settings=cfg()
    slot={"pair":"SOLUSDT","leverageMode":"exact","leverage":50,"startNotional":100}
    assert resolve_slot_leverage(Client(100),slot,settings,existing_leverage=50)==(50,100)
    try: resolve_slot_leverage(Client(100),slot,settings,existing_leverage=100)
    except ValueError as exc: assert "Exact vereist 50x" in str(exc)
    else: raise AssertionError("existing exact mismatch must fail")


def test_active_cycle_keeps_legacy_fixed_spacing_when_settings_change():
    settings=cfg(focusDcaDistance=.005,focusDcaMode="fixed",focusMaxDca=30)
    state={"pair":"SOLUSDT","side":"LONG","cycleId":"focus-cycle","originalEntry":108.99}
    raw={"focusLiveState":{"activePair":"SOLUSDT","cycleId":"focus-cycle","originalEntry":108.99,"dcaCount":5,"nextDcaTrigger":107.02818}}
    mode,distance,custom=_cycle_dca_policy(settings,state,raw,symbol="SOLUSDT",side="LONG")
    assert mode=="fixed"
    assert abs(distance-.003)<1e-12
    assert abs(_next_trigger(settings,side="LONG",original=108.99,dca_count=7,mode=mode,distance=distance,custom_levels=custom)-106.37424)<1e-9


def test_persisted_cycle_spacing_wins_over_new_settings():
    settings=cfg(focusDcaDistance=.02,focusDcaMode="fixed",focusMaxDca=30)
    state={"cycleId":"cycle","originalEntry":100.0,"cycleDcaMode":"fixed","cycleDcaDistance":.003,"cycleDcaCustomLevels":[]}
    mode,distance,custom=_cycle_dca_policy(settings,state,{},symbol="SOLUSDT",side="LONG")
    assert distance==.003
    assert abs(_next_trigger(settings,side="LONG",original=100,dca_count=9,mode=mode,distance=distance,custom_levels=custom)-97.0)<1e-9


def test_focus_dca_uses_focus_budget_and_actual_available_margin_not_generic_strategy_budget():
    from pathlib import Path
    source=Path("aster_strategy2_focus_multi.py").read_text()
    assert 'current_slot_notional+notional>settings.focus_max_budget_usd' in source
    assert 'required*1.05>available_remaining' in source
    assert 'required>strategy_margin_remaining' not in source
    assert 'reason="onvoldoende actuele Aster available margin"' in source
