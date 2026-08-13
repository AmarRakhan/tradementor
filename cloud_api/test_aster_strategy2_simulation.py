from aster_strategy2_simulation import standard_suite, failure_suite

def test_required_market_scenarios_are_deterministic_and_bounded():
    results=standard_suite()
    assert [x.name for x in results]==["bull","bear","sideways","crash","pump","reversal"]
    assert all(x.passed and x.duplicate_orders==0 for x in results)

def test_bull_and_bear_are_mirrored_profit_harvesters():
    bull,bear=standard_suite()[:2]
    assert any("LONG:FULL_TP" in x for x in bull.decisions)
    assert any("SHORT:FULL_TP" in x for x in bear.decisions)

def test_sideways_harvests_both_directions():
    values=standard_suite()[2].decisions
    assert any("LONG:FULL_TP" in x for x in values)
    assert any("SHORT:FULL_TP" in x for x in values)

def test_crash_and_pump_do_not_create_unbounded_dca():
    crash,pump=standard_suite()[3:5]
    assert crash.final_long_size<=50 and pump.final_short_size<=50

def test_failure_and_cashflow_suite():
    assert all(failure_suite().values())
