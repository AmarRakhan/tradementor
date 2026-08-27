import pytest
from aster_strategy2_focus_cycle import (
    FocusCycleState, ParkedPair, brake_triggered, can_rotate,
    cycle_state_from_mapping, cycle_state_to_mapping, mark_pair_used,
    park_pair, reset_cycle, update_high_water,
)


def test_high_water_and_usd_brake():
    s=reset_cycle(equity=250,cycle_id="c",timestamp_ms=1)
    s=update_high_water(s,equity=260,timestamp_ms=2)
    s=update_high_water(s,equity=255,timestamp_ms=3)
    assert s.high_water_equity==260 and s.drawdown_usd==5
    assert brake_triggered(s,mode="usd",value=5)
    assert not brake_triggered(s,mode="usd",value=6)


def test_pct_brake_uses_cycle_high_water():
    s=reset_cycle(equity=200,cycle_id="c")
    s=update_high_water(s,equity=250,timestamp_ms=1)
    s=update_high_water(s,equity=225,timestamp_ms=2)
    assert s.drawdown_pct==pytest.approx(.10)
    assert brake_triggered(s,mode="pct",value=.10)


def test_brake_off_is_backward_compatible():
    s=update_high_water(FocusCycleState(),equity=100,timestamp_ms=1)
    s=update_high_water(s,equity=1,timestamp_ms=2)
    assert not brake_triggered(s,mode="off",value=1)
    assert not brake_triggered(s,mode="usd",value=0)


def test_pair_cap_prevents_n_plus_one():
    s=FocusCycleState(used_pairs=("AAAUSDT","BBBUSDT"))
    assert can_rotate(s,3)
    assert not can_rotate(s,2)
    assert not can_rotate(s,0)


def test_parked_pair_is_persisted_and_used():
    s=mark_pair_used(FocusCycleState(cycle_id="c"),"AAAUSDT",timestamp_ms=1)
    p=ParkedPair("AAAUSDT","c",original_quantity=2,hedge_quantity=2,hedge_order_id="o",hedge_intent_id="i",parked_at_ms=2)
    s=park_pair(s,p,timestamp_ms=2)
    raw=cycle_state_to_mapping(s); restored=cycle_state_from_mapping(raw)
    assert restored.used_pairs==("AAAUSDT",)
    assert restored.parked_pairs[0].hedge_quantity==2
    assert restored.last_event=="FOCUS_PARKED"


def test_reset_cycle_clears_parked_and_used_state():
    s=FocusCycleState(used_pairs=("AAAUSDT",),parked_pairs=(ParkedPair("AAAUSDT","c"),),high_water_equity=300)
    r=reset_cycle(equity=280,cycle_id="new",timestamp_ms=5)
    assert r.used_pairs==() and r.parked_pairs==()
    assert r.high_water_equity==280 and r.current_pair_number==0
