from pathlib import Path

from aster_leverage_tiers import normalized_tiers, maximum_for_notional, resolve_entry, resolve_dca, tier_preview


HYPE = [{"symbol":"HYPEUSDT","brackets":[
    {"notionalFloor":"0","notionalCap":"3000","initialLeverage":300,"maintMarginRatio":"0.004"},
    {"notionalFloor":"3000","notionalCap":"10000","initialLeverage":75,"maintMarginRatio":"0.01"},
    {"notionalFloor":"10000","notionalCap":"0","initialLeverage":50,"maintMarginRatio":"0.02"},
]}]
ALT = [{"symbol":"ALTUSDT","brackets":[
    {"notionalFloor":"0","notionalCap":"5000","initialLeverage":100,"maintMarginRatio":"0.005"},
    {"notionalFloor":"5000","notionalCap":"0","initialLeverage":50,"maintMarginRatio":"0.02"},
]}]


def test_tiers_are_exchange_rows_not_symbol_hardcodes():
    assert [x["maxLeverage"] for x in normalized_tiers(HYPE,"HYPEUSDT")] == [300,75,50]
    assert [x["maxLeverage"] for x in normalized_tiers(ALT,"ALTUSDT")] == [100,50]
    source=Path("aster_leverage_tiers.py").read_text()
    assert "HYPEUSDT" not in source and "3000" not in source


def test_maximum_is_based_on_total_notional():
    assert maximum_for_notional(HYPE,"HYPEUSDT",2999) == 300
    assert maximum_for_notional(HYPE,"HYPEUSDT",3001) == 75
    assert maximum_for_notional(HYPE,"HYPEUSDT",10001) == 50


def test_margin_entry_finds_self_consistent_lower_tier_instead_of_stopping():
    result=resolve_entry(HYPE,"HYPEUSDT",configured_minimum=300,entry_margin_usd=20,entry_notional_usd=1,entry_sizing_mode="margin")
    assert result["leverage"] == 75
    assert result["orderNotional"] == 1500
    assert result["forcedBelowConfiguredMinimum"] is True


def test_entry_stays_at_highest_tier_when_size_allows_it():
    result=resolve_entry(HYPE,"HYPEUSDT",configured_minimum=300,entry_margin_usd=5,entry_notional_usd=1,entry_sizing_mode="margin")
    assert result["leverage"] == 300
    assert result["orderNotional"] == 1500


def test_long_or_short_share_the_same_contract_tier_math():
    # Side is deliberately absent: Aster leverage is contract-wide.
    result=resolve_dca(HYPE,"HYPEUSDT",current_notional=2900,current_leverage=300,dca_margin_usd=2,configured_minimum=300)
    assert result["leverage"] == 75 and result["tierReduction"] is True
    assert result["projectedNotional"] == 3050
    assert result["additionalMarginRequired"] > 0


def test_dca_inside_tier_keeps_leverage():
    result=resolve_dca(HYPE,"HYPEUSDT",current_notional=1500,current_leverage=300,dca_margin_usd=2,configured_minimum=300)
    assert result["leverage"] == 300 and result["tierReduction"] is False


def test_repeated_dca_never_steps_leverage_back_up():
    first=resolve_dca(HYPE,"HYPEUSDT",current_notional=2900,current_leverage=300,dca_margin_usd=2,configured_minimum=300)
    second=resolve_dca(HYPE,"HYPEUSDT",current_notional=first["projectedNotional"],current_leverage=first["leverage"],dca_margin_usd=2,configured_minimum=300)
    assert first["leverage"] == 75 and second["leverage"] == 75


def test_unlimited_dca_can_cross_multiple_tiers_by_repeated_resolution():
    notional=2900; leverage=300; seen=[]
    for _ in range(100):
        step=resolve_dca(HYPE,"HYPEUSDT",current_notional=notional,current_leverage=leverage,dca_margin_usd=1,configured_minimum=300)
        leverage=step["leverage"]; notional=step["projectedNotional"]; seen.append(leverage)
        if leverage == 50: break
    assert 75 in seen and 50 in seen


def test_preview_estimates_next_tier_dcas_without_trading():
    preview=tier_preview(HYPE,"HYPEUSDT",configured_minimum=300,entry_margin_usd=5,entry_notional_usd=1,entry_sizing_mode="margin",dca_margin_usd=2)
    assert preview["source"] == "/fapi/v3/leverageBracket"
    assert preview["nextTier"]["maxLeverage"] == 75
    assert preview["estimatedDcasToNextTier"] is not None


def test_reentry_and_diagnostics_contract_is_explicit_in_runtime_source():
    source=Path("aster_multi_bb.py").read_text()
    assert "REENTRY_STATE_CLEARED" in source
    assert "selected_keys" in source
    for status in ("READY_FOR_ENTRY","ENTRY_PLANNED","ENTRY_SUBMITTED","POSITION_ALREADY_OPEN","WAITING_CAPACITY","WAITING_BUDGET","WAITING_EXCHANGE","ORDER_REJECTED"):
        assert status in source
    assert '"lastReason": f"{entry_status}: {entry_reason}"' in source


def test_start_clears_stale_pending_reopens_and_old_report_then_forces_first_tick():
    source=Path("main.py").read_text()
    assert '"pendingReopens":[]' in source
    assert '"multiBbReport":{}' in source
    assert 'first=_run_aster_strategy2_tick(uid,dry_run=settings.mode!="live")' in source


def test_managed_dca_may_change_entire_contract_leverage_only_with_explicit_opt_in():
    source=Path("aster_execution.py").read_text()
    assert "allow_existing_contract_leverage_change" in source
    multi=Path("aster_multi_bb.py").read_text()
    assert "allow_existing_contract_leverage_change=True" in multi
    assert "INSUFFICIENT_MARGIN_FOR_TIER_LEVERAGE_REDUCTION" in multi
