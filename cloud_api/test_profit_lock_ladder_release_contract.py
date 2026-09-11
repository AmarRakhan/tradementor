from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_profit_lock_ladder_release_contract_is_additive_and_safe():
    facade = (ROOT / "aster_multi_bb.py").read_text()
    runtime = (ROOT / "aster_profit_lock_ladder_runtime.py").read_text()
    helper = (ROOT / "aster_profit_lock_ladder.py").read_text()
    dynamic = (ROOT / "aster_dynamic_hedge_sequence.py").read_text()

    assert 'profit_lock_ladder_enabled: bool = False' in facade
    assert 'normalized["longSlots"] = total' in facade
    assert 'normalized["shortSlots"] = 0' in facade
    assert 'effective_tp_mode = "OFF" if settings.profit_lock_ladder_enabled' in facade
    assert 'blocked_side="SHORT"' in facade.replace(" ", "")
    assert 'short_notional > long_notional' in helper
    assert 'FINAL_100_PERCENT_LEVEL_REACHED' in helper
    assert 'BLOCKED_NORMAL_SHORTS' in runtime
    assert 'Profit Lock SHORT-close niet flat bevestigd' in runtime
    assert 'PROFIT_LOCK_CYCLE_CLOSED' in runtime
    assert 'profit_lock_ladder_enabled' in dynamic
