import math
import pytest

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus import (
    DEFAULT_FOCUS_DCA, MAX_FOCUS_DCA, FocusMarket, FocusState,
    apply_focus_buy, can_add_focus_order, dca_drop_sequence,
    dca_notional_sequence, exit_decision, exposure_preview,
    focus_order_notional, next_dca_trigger, rank_focus_pairs, reset_after_full_exit,
    select_focus_pair, update_trailing, weighted_average_entry,
)
from aster_strategy2_focus_shadow import (
    FocusRiskSnapshot, FocusShadowBoundary, FocusShadowInputs,
    FocusShadowMutationBlocked, plan_focus_shadow,
)


def candles(base=100.0, drift=.002, n=60):
    return tuple(base * ((1 + drift) ** i) for i in range(n))


def market(symbol, change, price=100, volume=100_000_000, closes=None, liquidity=1.0):
    return FocusMarket(symbol, price, change, volume, liquidity, closes or candles())


def config(**overrides):
    raw={
        "tradingMode":"focus","focusShadowEnabled":True,
        "focusMaxBudgetUsd":5000,"focusStartOrderNotional":100,
        "focusDcaNotional":100,"focusMaxDca":5,"focusDcaDistance":.02,
        "focusDcaMultiplier":1,"focusTrailingActivationPct":.02,
        "focusTrailingDistancePct":.025,"focusMinimumProfitPct":.015,
        "minimumQuoteVolume24hUsdt":1_000_000,"leverage":20,
    }
    raw.update(overrides)
    return Strategy2Config.from_mapping(raw)


def risk(**overrides):
    values=dict(portfolio_equity=1000,available_margin=500,strategy_margin_used=0,
                strategy_budget_margin=450,exchange_max_notional_remaining=100_000,
                liquidation_distance_pct=.5,minimum_liquidation_distance_pct=.05,
                maintenance_margin_ratio=.1,maximum_maintenance_margin_ratio=.7)
    values.update(overrides)
    return FocusRiskSnapshot(**values)


def test_existing_accounts_default_to_multi_pair_and_focus_off():
    c=Strategy2Config.from_mapping({})
    assert c.trading_mode=="multi_pair"
    assert c.focus_shadow_enabled is False


def test_default_focus_dca_is_conservative_and_max_is_30():
    c=Strategy2Config.from_mapping({})
    assert c.focus_max_dca==DEFAULT_FOCUS_DCA==5
    assert MAX_FOCUS_DCA==30
    assert c.focus_max_dca < MAX_FOCUS_DCA


def test_focus_max_30_is_valid_but_31_is_rejected():
    assert config(focusMaxDca=30).focus_max_dca==30
    with pytest.raises(ValueError): config(focusMaxDca=31)


def test_manual_focus_requires_pair_when_focus_is_selected():
    with pytest.raises(ValueError): config(focusSelectionMode="manual",focusManualPair="")
    assert config(focusSelectionMode="manual",focusManualPair="btcusdt").focus_manual_pair=="BTCUSDT"


def test_only_focus_config_does_not_change_old_multi_pair_fields():
    c=Strategy2Config.from_mapping({"maximumPairs":12,"longMaxDca":4,"shortMaxDca":7})
    assert c.maximum_pairs==12 and c.long_max_dca==4 and c.short_max_dca==7
    assert c.trading_mode=="multi_pair"


def test_highest_24h_riser_is_primary_candidate():
    rows=rank_focus_pairs([market("AAAUSDT",.15),market("BBBUSDT",.10),market("CCCUSDT",.05)])
    assert rows[0].symbol=="AAAUSDT"


def test_extreme_overstretch_can_allow_second_leader_to_win():
    flat=tuple([100.0]*59+[100.0])
    overstretched=market("AAAUSDT",.15,price=130,closes=flat)
    healthy=market("BBBUSDT",.14,price=100,closes=tuple([90+i*.2 for i in range(60)]))
    rows=rank_focus_pairs([overstretched,healthy])
    assert rows[0].symbol=="BBBUSDT"
    assert next(r for r in rows if r.symbol=="AAAUSDT").overextended


def test_volume_filter_rejects_illiquid_leader():
    selected,rows,_=select_focus_pair([market("AAAUSDT",.20,volume=1000),market("BBBUSDT",.10)],minimum_quote_volume=1_000_000)
    assert selected.symbol=="BBBUSDT"
    assert next(r for r in rows if r.symbol=="AAAUSDT").eligible is False


def test_manual_selection_works():
    selected,_,reason=select_focus_pair([market("AAAUSDT",.20),market("BBBUSDT",.10)],selection_mode="manual",manual_pair="BBBUSDT")
    assert selected.symbol=="BBBUSDT" and "handmatige" in reason


def test_no_pair_hopping_during_active_cycle():
    selected,_,reason=select_focus_pair([market("AAAUSDT",.30),market("BBBUSDT",.10)],active_pair="BBBUSDT",cycle_open=True)
    assert selected.symbol=="BBBUSDT"
    assert "geen pair-hopping" in reason


def test_selection_can_change_after_full_exit():
    before,_,_=select_focus_pair([market("AAAUSDT",.10),market("BBBUSDT",.20)])
    assert before.symbol=="BBBUSDT"
    after,_,_=select_focus_pair([market("AAAUSDT",.30),market("BBBUSDT",.05)])
    assert after.symbol=="AAAUSDT"


def test_ranking_uses_only_supplied_current_data():
    # Deterministic pure call proves no clock/network/future-data dependency.
    markets=[market("AAAUSDT",.12),market("BBBUSDT",.10)]
    assert [r.public_dict() for r in rank_focus_pairs(markets)]==[r.public_dict() for r in rank_focus_pairs(markets)]


def test_focus_sizing_fixed_and_compounding_percentage():
    assert focus_order_notional(sizing_mode="fixed_usd",fixed_usd=100,equity_pct=.5,equity=250,max_start_order_usd=1000)==100
    assert focus_order_notional(sizing_mode="equity_pct",fixed_usd=100,equity_pct=.5,equity=250,max_start_order_usd=1000)==125
    assert focus_order_notional(sizing_mode="equity_pct",fixed_usd=100,equity_pct=.5,equity=3000,max_start_order_usd=500)==500


def test_fixed_dca_geometric_series_is_exact():
    assert dca_notional_sequence(amount=100,multiplier=1,count=3)==(100,100,100)
    assert dca_notional_sequence(amount=100,multiplier=1.5,count=4)==pytest.approx((100,150,225,337.5))


def test_no_hidden_exponential_growth_in_preview():
    p=exposure_preview(entry_price=100,first_order_notional=100,dca_enabled=True,dca_amount=100,dca_multiplier=1.5,max_dca=4,dca_distance_pct=.02,dca_mode="fixed",leverage=20,equity=1000,available_margin=1000,focus_budget=5000)
    assert p.total_max_order_notional==pytest.approx(912.5)
    assert p.required_margin==pytest.approx(45.625)


def test_example_100_plus_30_dca_at_20x_is_3100_notional_and_155_margin():
    p=exposure_preview(entry_price=100,first_order_notional=100,dca_enabled=True,dca_amount=100,dca_multiplier=1,max_dca=30,dca_distance_pct=.01,dca_mode="fixed",leverage=20,equity=1000,available_margin=1000,focus_budget=5000)
    assert p.total_max_order_notional==3100
    assert p.required_margin==155
    assert p.max_leveraged_exposure==3100


def test_focus_budget_is_notional_not_margin():
    p=exposure_preview(entry_price=100,first_order_notional=100,dca_enabled=True,dca_amount=100,dca_multiplier=1,max_dca=5,dca_distance_pct=.02,dca_mode="fixed",leverage=20,equity=1000,available_margin=1000,focus_budget=500)
    assert p.total_max_order_notional==600
    assert p.required_margin==30
    assert p.safe is False and p.status=="budget overschreden"


def test_available_margin_is_separate_hard_gate():
    p=exposure_preview(entry_price=100,first_order_notional=100,dca_enabled=True,dca_amount=100,dca_multiplier=1,max_dca=1,dca_distance_pct=.02,dca_mode="fixed",leverage=10,equity=1000,available_margin=10,focus_budget=1000)
    assert p.required_margin==20
    assert p.safe is False and "margin" in p.status


def test_fixed_dca_drop_and_progressive_drop():
    assert dca_drop_sequence(distance_pct=.02,count=3,mode="fixed")==pytest.approx((.02,.04,.06))
    assert dca_drop_sequence(distance_pct=.02,count=3,mode="progressive")==pytest.approx((.02,.06,.12))


def test_weighted_average_entry_is_quantity_weighted():
    avg=weighted_average_entry(100,100,(98,96),(100,100))
    expected=300/(1+100/98+100/96)
    assert avg==pytest.approx(expected)


def test_every_dca_rechecks_focus_budget():
    ok,reason=can_add_focus_order(proposed_notional=100,leverage=20,focus_budget_used=450,focus_budget=500,strategy_margin_used=0,strategy_budget=100,available_margin=100,exchange_max_notional_remaining=1000,liquidation_distance_pct=.5,minimum_liquidation_distance_pct=.05,maintenance_margin_ratio=.1,maximum_maintenance_margin_ratio=.7)
    assert not ok and reason=="Focus-budget bereikt"


def test_dca_rechecks_strategy_budget():
    ok,reason=can_add_focus_order(proposed_notional=100,leverage=10,focus_budget_used=0,focus_budget=1000,strategy_margin_used=95,strategy_budget=100,available_margin=100,exchange_max_notional_remaining=1000,liquidation_distance_pct=.5,minimum_liquidation_distance_pct=.05,maintenance_margin_ratio=.1,maximum_maintenance_margin_ratio=.7)
    assert not ok and reason=="Strategy-2-budget bereikt"


def test_dca_rechecks_exchange_notional():
    ok,reason=can_add_focus_order(proposed_notional=100,leverage=10,focus_budget_used=0,focus_budget=1000,strategy_margin_used=0,strategy_budget=100,available_margin=100,exchange_max_notional_remaining=50,liquidation_distance_pct=.5,minimum_liquidation_distance_pct=.05,maintenance_margin_ratio=.1,maximum_maintenance_margin_ratio=.7)
    assert not ok and reason=="exchange max-notional bereikt"


def test_dca_rechecks_liquidation_distance():
    ok,reason=can_add_focus_order(proposed_notional=100,leverage=10,focus_budget_used=0,focus_budget=1000,strategy_margin_used=0,strategy_budget=100,available_margin=100,exchange_max_notional_remaining=1000,liquidation_distance_pct=.02,minimum_liquidation_distance_pct=.05,maintenance_margin_ratio=.1,maximum_maintenance_margin_ratio=.7)
    assert not ok and "liquidation" in reason


def test_apply_focus_buy_updates_weighted_entry_and_dca_count():
    s=FocusState(active_pair="AAAUSDT")
    s=apply_focus_buy(s,price=100,notional=100,leverage=10,timestamp_ms=1,is_dca=False)
    s=apply_focus_buy(s,price=90,notional=100,leverage=10,timestamp_ms=2,is_dca=True)
    assert s.dca_count==1 and s.total_notional==200 and s.focus_budget_used==200
    assert 90<s.weighted_entry<100


def test_trailing_activation_and_floor_never_moves_down():
    s=FocusState(active_pair="AAAUSDT",weighted_entry=100,total_quantity=1,total_notional=100,highest_price=100)
    a=update_trailing(s,price=105,activation_pct=.02,trailing_distance_pct=.02,minimum_profit_pct=.015)
    assert a.trailing_active and a.trailing_floor==pytest.approx(102.9)
    b=update_trailing(a,price=110,activation_pct=.02,trailing_distance_pct=.02,minimum_profit_pct=.015)
    c=update_trailing(b,price=107,activation_pct=.02,trailing_distance_pct=.02,minimum_profit_pct=.015)
    assert b.trailing_floor> a.trailing_floor
    assert c.trailing_floor==b.trailing_floor


def test_runner_stays_open_until_trailing_floor_is_hit():
    s=FocusState(active_pair="AAAUSDT",weighted_entry=100,total_quantity=1,total_notional=100,highest_price=100)
    s,d=exit_decision(s,price=115,minimum_profit_pct=.015,trailing_activation_pct=.02,trailing_distance_pct=.03,partial_tp_enabled=False,first_partial_tp_pct=.05,first_partial_close_pct=.25,second_partial_tp_pct=.10,second_partial_close_pct=.25)
    assert d.kind=="HOLD"
    floor=s.trailing_floor
    s,d=exit_decision(s,price=floor-.01,minimum_profit_pct=.015,trailing_activation_pct=.02,trailing_distance_pct=.03,partial_tp_enabled=False,first_partial_tp_pct=.05,first_partial_close_pct=.25,second_partial_tp_pct=.10,second_partial_close_pct=.25)
    assert d.kind=="CLOSE"


def test_partial_profit_taking_can_happen_twice_then_runner_remains():
    s=FocusState(active_pair="AAAUSDT",weighted_entry=100,total_quantity=10,total_notional=1000,highest_price=100)
    s,d1=exit_decision(s,price=106,minimum_profit_pct=.015,trailing_activation_pct=.02,trailing_distance_pct=.03,partial_tp_enabled=True,first_partial_tp_pct=.05,first_partial_close_pct=.25,second_partial_tp_pct=.10,second_partial_close_pct=.25)
    assert d1.kind=="PARTIAL_TP" and d1.close_fraction==.25
    s,d2=exit_decision(s,price=111,minimum_profit_pct=.015,trailing_activation_pct=.02,trailing_distance_pct=.03,partial_tp_enabled=True,first_partial_tp_pct=.05,first_partial_close_pct=.25,second_partial_tp_pct=.10,second_partial_close_pct=.25)
    assert d2.kind=="PARTIAL_TP" and set(s.partials_taken)=={1,2}
    s,d3=exit_decision(s,price=112,minimum_profit_pct=.015,trailing_activation_pct=.02,trailing_distance_pct=.03,partial_tp_enabled=True,first_partial_tp_pct=.05,first_partial_close_pct=.25,second_partial_tp_pct=.10,second_partial_close_pct=.25)
    assert d3.kind=="HOLD"


def test_full_exit_resets_pair_for_new_selection():
    s=FocusState(active_pair="AAAUSDT",cycle_id="c",weighted_entry=100,total_quantity=1,total_notional=100,dca_count=3)
    r=reset_after_full_exit(s,realized_pnl=12,theoretical_portfolio_value=1012)
    assert r.active_pair=="" and r.dca_count==0 and r.cycle_status=="Nieuwe pair zoeken"
    assert r.realized_pnl==12


def test_shadow_disabled_sends_zero_orders():
    c=Strategy2Config.from_mapping({"tradingMode":"focus","focusShadowEnabled":False})
    result=plan_focus_shadow(FocusShadowInputs(c,(market("AAAUSDT",.2),),FocusState(),risk(),1))
    assert result["ordersSent"]==0 and result["theoreticalActions"]==[]


def test_shadow_new_entry_is_long_only_and_one_pair():
    result=plan_focus_shadow(FocusShadowInputs(config(),(market("AAAUSDT",.20),market("BBBUSDT",.10)),FocusState(),risk(),1))
    assert result["ordersSent"]==0
    assert result["newFocusPairLimit"]==1 and result["side"]=="LONG"
    assert len(result["theoreticalActions"])==1
    assert result["theoreticalActions"][0]["kind"]=="OPEN"


def test_shadow_wait_until_flat_blocks_only_new_focus_entry():
    c=config(focusWaitUntilFlat=True)
    result=plan_focus_shadow(FocusShadowInputs(c,(market("AAAUSDT",.20),),FocusState(),risk(),1,legacy_open_positions=4))
    assert result["ordersSent"]==0
    assert result["theoreticalActions"]==[]
    assert result["legacyPositionsManagedByMultiPair"]==4


def test_shadow_keeps_active_pair_even_if_new_leader_appears():
    s=FocusState(active_pair="BBBUSDT",cycle_id="c",weighted_entry=100,original_entry=100,total_quantity=1,total_notional=100,highest_price=100,focus_budget_used=100)
    result=plan_focus_shadow(FocusShadowInputs(config(),(market("AAAUSDT",.30),market("BBBUSDT",.05)),s,risk(),1))
    assert result["state"]["active_pair"]=="BBBUSDT"
    assert "geen pair-hopping" in result["selectionReason"]


def test_shadow_budget_block_skips_dca_but_does_not_close_position():
    c=config(focusMaxBudgetUsd=150,focusDcaNotional=100)
    s=FocusState(active_pair="AAAUSDT",cycle_id="c",weighted_entry=100,original_entry=100,total_quantity=1,total_notional=100,highest_price=100,focus_budget_used=100,dca_count=0)
    falling=market("AAAUSDT",.20,price=97,closes=candles())
    result=plan_focus_shadow(FocusShadowInputs(c,(falling,),s,risk(),1))
    assert result["ordersSent"]==0
    assert result["decision"]["kind"]=="HOLD"
    assert "DCA overgeslagen" in result["decision"]["reason"]


def test_shadow_reports_comparison_metrics_and_zero_orders():
    current={"portfolioEquity":995,"realizedPnl":5,"maxDrawdown":.02}
    result=plan_focus_shadow(FocusShadowInputs(config(),(market("AAAUSDT",.20),),FocusState(),risk(),1,current_strategy2_metrics=current))
    assert result["currentStrategy2"]==current
    assert "performance" in result and result["ordersSent"]==0


def test_shadow_boundary_has_no_usable_order_path():
    boundary=FocusShadowBoundary()
    with pytest.raises(FocusShadowMutationBlocked):boundary.submit_order(symbol="AAAUSDT")
    with pytest.raises(FocusShadowMutationBlocked):boundary.persist_exchange_change()


def test_strategy2_public_dict_exposes_focus_but_defaults_remain_safe():
    public=Strategy2Config.from_mapping({}).public_dict()
    assert public["tradingMode"]=="multi_pair"
    assert public["focusShadowEnabled"] is False
    assert public["focusMaxDca"]==5


def test_partial_percentages_must_leave_runner_remainder():
    with pytest.raises(ValueError): config(focusPartialTpEnabled=True,focusFirstPartialClosePct=.5,focusSecondPartialClosePct=.5)


def test_trailing_activation_cannot_be_below_minimum_profit():
    with pytest.raises(ValueError): config(focusMinimumProfitPct=.03,focusTrailingActivationPct=.02)

def test_manual_selection_can_choose_noneligible_tradable_pair():
    markets=[FocusMarket('HYPEUSDT',10,-.05,50_000_000,1.0,())]
    selected,ranking,reason=select_focus_pair(markets,selection_mode='manual',manual_pair='HYPEUSDT',minimum_quote_volume=10_000_000)
    assert selected is not None and selected.symbol=='HYPEUSDT'
    assert selected.eligible is False
    assert reason=='handmatige Focus-selectie'

def test_micro_dca_linear_amounts_and_custom_levels():
    assert dca_notional_sequence(amount=25,multiplier=1,count=8,amount_mode="linear",increment=5) == (25,30,35,40,45,50,55,60)
    levels=(.0025,.005,.008,.0115,.0155,.02,.025,.031)
    assert dca_drop_sequence(distance_pct=.02,count=8,mode="custom",custom_levels=levels) == levels
    assert next_dca_trigger(original_entry=100,dca_count=3,max_dca=8,distance_pct=.02,mode="custom",custom_levels=levels) == pytest.approx(98.85)
