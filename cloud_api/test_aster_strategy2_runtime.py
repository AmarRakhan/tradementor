from aster_strategy2 import Strategy2Config
from aster_strategy2_state import OwnedLeg
from aster_strategy2_runtime import *
from datetime import datetime,timedelta,timezone

def row(side="LONG",qty="1",entry="100",mark="100",pnl="0"):
    return {"symbol":"BTCUSDT","positionSide":side,"positionAmt":qty,"entryPrice":entry,"markPrice":mark,"unRealizedProfit":pnl}

def test_mapping_round_trip_keeps_ownership_identity():
    leg=OwnedLeg("s2","strategy2","BTCUSDT","LONG","c1",3,1,100,2,"PROTECTION",("i",),("f",),(),1,2,3,4)
    assert owned_from_mapping(owned_to_mapping(leg))==leg

def test_missing_ownership_recovers_only_with_matching_audit_and_exchange_fill():
    stamp=datetime(2026,8,10,15,43,8,tzinfo=timezone.utc)
    positions=[{"symbol":"VIRTUALUSDT","positionSide":"LONG","positionAmt":"2","entryPrice":"5"}]
    audit=[{"event":"INITIAL_OPEN_LEG","symbol":"VIRTUALUSDT","side":"LONG","cycleId":"c1","configVersion":1,"timestamp":stamp}]
    fills=[{"symbol":"VIRTUALUSDT","positionSide":"LONG","qty":"2","price":"5","time":int(stamp.timestamp()*1000),"id":"f1"}]
    owned,recovered=recover_audited_ownership(persisted=[],positions=positions,audit_events=audit,fills=fills)
    assert [(x.symbol,x.side,x.quantity,x.weighted_entry) for x in owned]==[("VIRTUALUSDT","LONG",2,5)]
    assert recovered==[{"symbol":"VIRTUALUSDT","side":"LONG","cycleId":"c1"}]

def test_confirmed_normal_refill_recovers_after_refresh_timeout():
    stamp=datetime(2026,8,16,1,0,0,tzinfo=timezone.utc)
    positions=[{"symbol":"REFILLUSDT","positionSide":"SHORT","positionAmt":"3","entryPrice":"8"}]
    audit=[{"event":"OPEN_LEG","strategyId":"aster-strategy-2","symbol":"REFILLUSDT",
        "side":"SHORT","cycleId":"refill-c1","configVersion":7,"timestamp":stamp}]
    fills=[{"symbol":"REFILLUSDT","positionSide":"SHORT","qty":"3","price":"8",
        "time":int(stamp.timestamp()*1000),"id":"fill-refill"}]
    owned,recovered=recover_audited_ownership(persisted=[],positions=positions,audit_events=audit,fills=fills)
    assert len(owned)==1 and owned[0].cycle_id=="refill-c1"
    assert recovered==[{"symbol":"REFILLUSDT","side":"SHORT","cycleId":"refill-c1"}]

def test_open_audit_without_matching_fill_never_claims_ownership():
    stamp=datetime(2026,8,16,1,0,0,tzinfo=timezone.utc)
    positions=[{"symbol":"MANUALUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"9"}]
    audit=[{"event":"OPEN_LEG","strategyId":"aster-strategy-2","symbol":"MANUALUSDT",
        "side":"LONG","cycleId":"c","timestamp":stamp}]
    owned,recovered=recover_audited_ownership(persisted=[],positions=positions,audit_events=audit,fills=[])
    assert owned==[] and recovered==[]

def test_missing_ownership_is_not_recovered_without_a_matching_fill():
    positions=[{"symbol":"ADAUSDT","positionSide":"SHORT","positionAmt":"20","entryPrice":".5"}]
    audit=[{"event":"INITIAL_OPEN_LEG","symbol":"ADAUSDT","side":"SHORT","cycleId":"c2","timestamp":1_000}]
    owned,recovered=recover_audited_ownership(persisted=[],positions=positions,audit_events=audit,fills=[])
    assert owned==[] and recovered==[]

def test_missing_strategy2_ownership_never_claims_strategy3_leg():
    stamp=datetime(2026,8,12,12,0,0,tzinfo=timezone.utc)
    positions=[{"symbol":"CAPUSDT","positionSide":"LONG","positionAmt":"172","entryPrice":".0585"}]
    audit=[{"event":"INITIAL_OPEN_LEG","symbol":"CAPUSDT","side":"LONG","cycleId":"old-s2","timestamp":stamp}]
    fills=[{"symbol":"CAPUSDT","positionSide":"LONG","time":int(stamp.timestamp()*1000),"id":"s3-fill"}]
    owned,recovered=recover_audited_ownership(persisted=[],positions=positions,audit_events=audit,fills=fills,
        excluded_keys={("CAPUSDT","LONG")})
    assert owned==[] and recovered==[]

def test_exclusive_transfer_keeps_s2_and_absorbs_s3_without_changing_exchange_truth():
    s2_cap=OwnedLeg("aster-strategy-2","strategy2","CAPUSDT","LONG","old-s2",1,172,.0585)
    s2_btc=OwnedLeg("aster-strategy-2","strategy2","BTCUSDT","SHORT","real-s2",1,1,100)
    s3_eth=OwnedLeg("aster-strategy-3","strategy3","ETHUSDT","LONG","s3",1,2,2000,
        intent_ids=("s3-1abdc22e638a-open-long",))
    positions=[{"symbol":"CAPUSDT","positionSide":"LONG","positionAmt":"173","entryPrice":".0586"},
        {"symbol":"BTCUSDT","positionSide":"SHORT","positionAmt":"1","entryPrice":"100"},
        {"symbol":"ETHUSDT","positionSide":"LONG","positionAmt":"2.5","entryPrice":"2010"}]
    transferred,missing,errors=transfer_active_ownership_to_strategy2(positions=positions,
        strategy2_legs=[s2_cap,s2_btc],strategy3_legs=[s3_eth])
    assert missing==[] and errors==[]
    assert {(x.symbol,x.side,x.strategy_id,x.engine_type) for x in transferred}=={
        ("CAPUSDT","LONG","aster-strategy-2","strategy2"),
        ("BTCUSDT","SHORT","aster-strategy-2","strategy2"),
        ("ETHUSDT","LONG","aster-strategy-2","strategy2")}
    cap=next(x for x in transferred if x.symbol=="CAPUSDT")
    assert cap.cycle_id=="old-s2" and cap.quantity==173 and cap.weighted_entry==.0586

def test_exclusive_transfer_fails_closed_when_any_active_position_lacks_evidence():
    positions=[{"symbol":"ADAUSDT","positionSide":"SHORT","positionAmt":"20","entryPrice":".5"}]
    transferred,missing,errors=transfer_active_ownership_to_strategy2(positions=positions,strategy2_legs=[])
    assert transferred==[] and missing==[("ADAUSDT","SHORT")] and errors==[]

def test_exclusive_transfer_rejects_duplicate_source_claims():
    position={"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100"}
    leg=OwnedLeg("aster-strategy-2","strategy2","BTCUSDT","LONG","c",1,1,100)
    _,_,errors=transfer_active_ownership_to_strategy2(positions=[position],strategy2_legs=[leg,leg])
    assert errors==["duplicate-strategy2-ownership"]

def test_global_portfolio_includes_all_risk_but_strategy_exposure_only_owned():
    owned=[OwnedLeg("s2","strategy2","BTCUSDT","LONG","c",1,1,100)]
    p=portfolio_state(Strategy2Config(),{"totalMarginBalance":"1000","totalMaintMargin":"10"},[row(),row("SHORT",qty="2")],owned,900)
    assert p.long_exposure==100 and p.short_exposure==200 and p.strategy_exposure==100 and p.adjusted_high_water_mark==1000

def test_management_uses_exchange_position_and_selects_dca():
    cfg=Strategy2Config(long_dca_distance=.02)
    leg=OwnedLeg("s2","strategy2","BTCUSDT","LONG","c",1,1,100)
    positions=[row(mark="97",pnl="-3")]
    p=portfolio_state(cfg,{"totalMarginBalance":"1000","totalMaintMargin":"10"},positions,[leg],1000)
    chosen=next_management_decision(cfg,p,[leg],positions)
    assert chosen and chosen[1].kind=="ADD_DCA"

def test_scanner_stops_at_pair_or_budget_limit():
    cfg=Strategy2Config(maximum_pairs=1,strategy_budget=.5)
    leg=OwnedLeg("s2","strategy2","BTCUSDT","LONG","c",1,1,100)
    p=portfolio_state(cfg,{"totalMarginBalance":"1000"},[row()],[leg],1000)
    assert scanner_allowed(cfg,p,[leg]) is False

def test_scanner_budget_uses_required_margin_instead_of_notional():
    config=Strategy2Config(base_notional=100,leverage=20,strategy_budget=.10,maximum_pairs=5)
    portfolio=PortfolioState(1000,1000,.1,0,0,0,strategy_margin=80)
    assert scanner_allowed(config,portfolio,[]) is True

def test_initial_fifty_positions_target_exactly_twenty_five_per_side():
    assert balanced_entry_targets(50)==(25,25)
    assert entry_order_limit(False,[],50)==50

def test_initial_build_bypasses_one_per_tick_but_refill_does_not():
    owned=[]
    for index in range(10):
        owned.append(OwnedLeg("s2","strategy2",f"L{index}USDT","LONG",f"l{index}",1,1,100))
        owned.append(OwnedLeg("s2","strategy2",f"S{index}USDT","SHORT",f"s{index}",1,1,100))
    assert entry_order_limit(False,owned,50)==30
    assert entry_order_limit(True,owned,50)==1

def test_tp_and_dca_always_preempt_incomplete_balanced_initial_build():
    config=Strategy2Config(maximum_pairs=50)
    owned=[OwnedLeg("s2","strategy2",f"L{x}USDT","LONG",f"l{x}",1,1,100) for x in range(9)]
    owned += [OwnedLeg("s2","strategy2",f"S{x}USDT","SHORT",f"s{x}",1,1,100) for x in range(9)]
    assert management_preempts_initial_build(config,owned,Decision("FULL_TP","LONG",risk_reducing=True)) is True
    assert management_preempts_initial_build(config,owned,Decision("ADD_DCA","LONG")) is True

def test_profitable_leg_is_selected_during_incomplete_initial_build():
    config=Strategy2Config(maximum_pairs=50,take_profit=.015)
    winning=OwnedLeg("s2","strategy2","BANANAS31USDT","LONG","banana",1,1964,.010187)
    incomplete=[winning,OwnedLeg("s2","strategy2","RAVEUSDT","SHORT","rave",1,1,.326)]
    positions=[{"symbol":"BANANAS31USDT","positionSide":"LONG","positionAmt":"1964","entryPrice":".010187","markPrice":".010690","unRealizedProfit":".99"},row("SHORT",entry=".326",mark=".326")]
    portfolio=portfolio_state(config,{"totalMarginBalance":"117","totalMaintMargin":"28"},positions,incomplete,117)
    selected=next_management_decision(config,portfolio,incomplete,positions)
    assert selected and selected[0].symbol=="BANANAS31USDT"
    assert selected[1].kind=="FULL_TP"
    assert management_preempts_initial_build(config,incomplete,selected[1]) is True

def test_protection_and_emergency_always_preempt_initial_build():
    config=Strategy2Config(maximum_pairs=50)
    owned=[OwnedLeg("s2","strategy2","BTCUSDT","LONG","l",1,1,100)]
    assert management_preempts_initial_build(config,owned,Decision("OPEN_PROTECTION","SHORT")) is True
    assert management_preempts_initial_build(config,owned,Decision("EMERGENCY_REDUCE","LONG",risk_reducing=True)) is True

def test_management_resumes_after_balanced_start_is_complete():
    config=Strategy2Config(maximum_pairs=2)
    owned=[OwnedLeg("s2","strategy2","BTCUSDT","LONG","l",1,1,100),OwnedLeg("s2","strategy2","ETHUSDT","SHORT","s",1,1,100)]
    assert management_preempts_initial_build(config,owned,Decision("FULL_TP","LONG",risk_reducing=True)) is True

def test_protection_hedges_do_not_distort_harvest_balance():
    owned=[OwnedLeg("s2","strategy2","BTCUSDT","LONG","l",1,1,100),OwnedLeg("s2","strategy2","BTCUSDT","SHORT","h",1,1,100,role="PROTECTION")]
    assert harvest_counts(owned)==(1,0)
    assert next_balanced_entry_side(owned,4)=="SHORT"

def test_only_exchange_confirmed_side_costs_are_attributed_to_leg():
    leg=OwnedLeg("s2","strategy2","BTCUSDT","LONG","c",1,1,100,created_at_ms=100)
    enriched=enrich_confirmed_costs([leg],[{"symbol":"BTCUSDT","positionSide":"LONG","time":101,"commission":".2","realizedPnl":"1"},{"symbol":"BTCUSDT","positionSide":"SHORT","time":101,"commission":"9"}],
        [{"symbol":"BTCUSDT","positionSide":"LONG","time":102,"incomeType":"FUNDING_FEE","income":"-.1"}])[0]
    assert enriched.fees==.2 and enriched.realized_pnl==1 and enriched.funding==-.1

def test_caution_opens_same_pair_protection_only_after_real_dca_loss():
    cfg=Strategy2Config(caution_drawdown=.03,defensive_drawdown=.06,emergency_drawdown=.10)
    leg=OwnedLeg("s2","strategy2","BTCUSDT","LONG","c",1,1,100,dca_count=1)
    p=PortfolioState(960,1000,.2,100,0,100)
    chosen=same_pair_protection_decision(cfg,p,[leg],[row(mark="90",pnl="-10")])
    assert chosen and chosen[0].symbol=="BTCUSDT" and chosen[1].side=="SHORT" and chosen[1].kind=="OPEN_PROTECTION"

def test_tiny_spread_loss_does_not_open_hedge_before_dca():
    cfg=Strategy2Config(caution_drawdown=.03,defensive_drawdown=.06,emergency_drawdown=.10)
    leg=OwnedLeg("s2","strategy2","BTCUSDT","LONG","c",1,1,100,dca_count=0)
    p=PortfolioState(960,1000,.2,100,0,100)
    assert same_pair_protection_decision(cfg,p,[leg],[row(mark="99.9",pnl="-.01")]) is None

def test_normal_mode_closes_temporary_same_pair_protection():
    cfg=Strategy2Config();leg=OwnedLeg("s2","strategy2","BTCUSDT","SHORT","c",1,1,100,role="PROTECTION")
    p=PortfolioState(1000,1000,.1,100,100,200)
    assert portfolio_protection_decision(cfg,p,[leg])[1].kind=="CLOSE_PROTECTION"

def test_emergency_margin_reduces_overweight_side_instead_of_adding_gross_risk():
    cfg=Strategy2Config();leg=OwnedLeg("s2","strategy2","BTCUSDT","LONG","c",1,2,100)
    p=PortfolioState(1000,1000,.8,700,100,800)
    assert portfolio_protection_decision(cfg,p,[leg])[1].kind=="EMERGENCY_REDUCE"

def test_exchange_minimum_blocked_dca_does_not_monopolize_scheduler():
    config=Strategy2Config(base_notional=15,long_dca_distance=.02)
    leg=OwnedLeg("s2","strategy2","LITUSDT","LONG","c1",1,10,1)
    positions=[{"symbol":"LITUSDT","positionSide":"LONG","positionAmt":"10","entryPrice":"1","markPrice":"0.97","notional":"9.7"}]
    portfolio=portfolio_state(config,{"totalMarginBalance":"100","totalMaintMargin":"1"},positions,[leg],100)
    assert next_management_decision(config,portfolio,[leg],positions) is not None
    assert next_management_decision(config,portfolio,[leg],positions,{("LITUSDT","LONG")}) is None

def test_confirmed_flat_initial_build_resets_stale_drawdown_baseline():
    account={"totalMarginBalance":"451.55","totalWalletBalance":"451.55","totalMaintMargin":"0"}
    hwm=initial_build_high_water_mark(account=account,positions=[],owned=[],previous_hwm=600,
        initial_build_complete=False)
    portfolio=portfolio_state(Strategy2Config(),account,[],[],hwm)
    assert hwm==451.55
    assert portfolio.drawdown==0
    assert risk_mode(Strategy2Config(),portfolio)=="NORMAL"

def test_initial_build_never_resets_high_water_mark_with_active_exposure():
    account={"totalMarginBalance":"451.55","totalWalletBalance":"451.55","totalMaintMargin":"0"}
    positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1","markPrice":"10"}]
    assert initial_build_high_water_mark(account=account,positions=positions,owned=[],previous_hwm=600,
        initial_build_complete=False)==600
    leg=OwnedLeg("aster-strategy-2","strategy2","BTCUSDT","LONG","c",1,1,10)
    assert initial_build_high_water_mark(account=account,positions=[],owned=[leg],previous_hwm=600,
        initial_build_complete=False)==600

def test_unchanged_owned_legs_do_not_request_fill_history():
    owned=[OwnedLeg("s3","strategy3","BTCUSDT","LONG","c1",1,2,100)]
    positions=[row(qty="2",entry="100")]
    assert changed_owned_symbols(owned,positions)==set()

def test_only_changed_owned_symbols_require_fill_history():
    owned=[
        OwnedLeg("s3","strategy3","BTCUSDT","LONG","c1",1,2,100),
        OwnedLeg("s3","strategy3","ETHUSDT","SHORT","c2",1,3,50),
    ]
    positions=[row(qty="2",entry="101"),
        {"symbol":"ETHUSDT","positionSide":"SHORT","positionAmt":"3","entryPrice":"50"}]
    assert changed_owned_symbols(owned,positions)=={"BTCUSDT"}

def _live_state(now):
    return {"monitor":True,"enabled":True,"liveReady":True,"canaryValidated":True,
        "runtimeEnabled":True,"phase":"RUNNING","lastTickAt":now,"lastReason":"Actieve controle"}

def _tp_owned(symbol,side,qty,entry,now,*,fees=0.0,funding=0.0,role="HARVEST"):
    return OwnedLeg("aster-strategy-2","strategy2",symbol,side,"cycle",1,qty,entry,
        role=role,fees=fees,funding=funding,costs_updated_at_ms=int(now.timestamp()*1000))

def test_beat_like_gross_37_40_percent_uses_net_costs_and_closes_in_normal_mode():
    now=datetime(2026,8,14,18,0,tzinfo=timezone.utc);cfg=Strategy2Config(mode="live",take_profit=.015)
    owned=_tp_owned("BEATUSDT","SHORT",17,.889,now,fees=.10,funding=-.02)
    row={"symbol":"BEATUSDT","positionSide":"SHORT","positionAmt":"17","quantity":17,
        "entryPrice":.889,"markPrice":.647,"notionalUsd":11,"unrealizedPnl":4.11}
    portfolio=PortfolioState(1000,1000,.1,100,100,200)
    result=strategy2_position_tp_contract(row=row,owned=owned,config=cfg,state=_live_state(now),portfolio=portfolio,now=now)
    assert round(result["netProfitUsd"],4)==3.9845
    assert round(result["takeProfitTargetUsd"],3)==.165
    assert result["takeProfitPercent"]==1.5 and result["status"]=="TP bereikt"
    assert result["decision"]=="FULL_TP" and "volledige sluiting" in result["blockReason"]

def test_ena_like_gross_4_83_percent_still_uses_fees_funding_and_close_fee():
    now=datetime(2026,8,14,18,0,tzinfo=timezone.utc);cfg=Strategy2Config(mode="live",take_profit=.015)
    owned=_tp_owned("ENAUSDT","SHORT",227,.08814,now,fees=.10,funding=.01)
    row={"symbol":"ENAUSDT","positionSide":"SHORT","positionAmt":"227","quantity":227,
        "entryPrice":.08814,"markPrice":.08408,"notionalUsd":19.09,"unrealizedPnl":.92}
    portfolio=PortfolioState(1000,1000,.1,100,100,200)
    result=strategy2_position_tp_contract(row=row,owned=owned,config=cfg,state=_live_state(now),portfolio=portfolio,now=now)
    assert round(result["netProfitUsd"],6)==round(.92+.01-.10-19.09*.0005,6)
    assert result["status"]=="TP bereikt" and result["decision"]=="FULL_TP"

def test_strategy2_off_keeps_existing_profitable_position_orderable_for_full_tp():
    now=datetime(2026,8,14,18,0,tzinfo=timezone.utc);cfg=Strategy2Config(mode="live",take_profit=.015)
    state={**_live_state(now),"enabled":False,"monitor":True,"phase":"PROTECTIVE_ONLY"}
    owned=_tp_owned("BEATUSDT","SHORT",17,.889,now,fees=.10,funding=-.02)
    position={"symbol":"BEATUSDT","positionSide":"SHORT","positionAmt":"17","quantity":17,
        "entryPrice":.889,"markPrice":.647,"notional":11,"notionalUsd":11,
        "unRealizedProfit":4.11,"unrealizedPnl":4.11}
    portfolio=PortfolioState(1000,1000,.1,100,100,200)
    contract=strategy2_position_tp_contract(row=position,owned=owned,config=cfg,state=state,
        portfolio=portfolio,now=now)
    selected=next_management_decision(cfg,portfolio,[owned],[position])
    assert contract["status"]=="TP bereikt" and contract["decision"]=="FULL_TP"
    assert selected and selected[1].kind=="FULL_TP" and selected[1].risk_reducing is True

def test_contract_uses_the_persisted_take_profit_instead_of_the_default():
    now=datetime(2026,8,14,18,0,tzinfo=timezone.utc)
    cfg=Strategy2Config.from_mapping({"mode":"live","takeProfit":.0175})
    owned=_tp_owned("BEATUSDT","SHORT",17,.889,now)
    result=strategy2_position_tp_contract(row={"notionalUsd":11,"unrealizedPnl":4.11},owned=owned,
        config=cfg,state=_live_state(now),portfolio=None,now=now)
    assert round(result["takeProfitPercent"],4)==1.75
    assert round(result["takeProfitTargetUsd"],4)==.1925

def test_protection_mode_returns_partial_close_or_concrete_block_reason():
    now=datetime(2026,8,14,18,0,tzinfo=timezone.utc);cfg=Strategy2Config(mode="live",take_profit=.015)
    owned=_tp_owned("BEATUSDT","SHORT",17,.889,now)
    row={"symbol":"BEATUSDT","positionSide":"SHORT","positionAmt":"17","quantity":17,
        "entryPrice":.889,"markPrice":.647,"notionalUsd":11,"unrealizedPnl":4.11}
    portfolio=PortfolioState(900,1000,.60,600,50,650)
    result=strategy2_position_tp_contract(row=row,owned=owned,config=cfg,state=_live_state(now),portfolio=portfolio,now=now)
    assert result["status"]=="TP bereikt"
    assert result["decision"] in {"PARTIAL_TP","ASSIGN_PROTECTION"}
    assert result["blockReason"]

def test_missing_ownership_never_produces_orderable_tp_status():
    now=datetime(2026,8,14,18,0,tzinfo=timezone.utc);cfg=Strategy2Config(mode="live")
    result=strategy2_position_tp_contract(row={"notionalUsd":11,"unrealizedPnl":4.11},owned=None,
        config=cfg,state=_live_state(now),portfolio=None,now=now)
    assert result["status"]=="Niet betrouwbaar te bepalen" and result["netProfitUsd"] is None
    assert result["ownershipProven"] is False and "ownership" in result["blockReason"]
    assert result["takeProfitTargetUsd"] is None and result["takeProfitPercent"] is None
    assert result["paidFeesUsd"] is None and result["fundingUsd"] is None and result["estimatedCloseFeeUsd"] is None

def test_eigen_like_negative_position_is_reliably_below_tp():
    now=datetime(2026,8,14,18,0,tzinfo=timezone.utc);cfg=Strategy2Config(mode="live",take_profit=.015)
    owned=_tp_owned("EIGENUSDT","LONG",55.82,1,now,fees=.03,funding=-.01)
    result=strategy2_position_tp_contract(row={"symbol":"EIGENUSDT","positionSide":"LONG","quantity":55.82,
        "entryPrice":1,"markPrice":1,"notionalUsd":55.82,"unrealizedPnl":-4.26},owned=owned,
        config=cfg,state=_live_state(now),portfolio=PortfolioState(1000,1000,.1,100,100,200),now=now)
    assert result["status"]=="TP nog niet bereikt" and result["netProfitUsd"]<0
    assert result["takeProfitTargetUsd"]>0 and result["blockReason"]

def test_stale_scheduler_is_warning_but_keeps_complete_net_tp_evidence():
    now=datetime(2026,8,14,18,0,tzinfo=timezone.utc);state=_live_state(now-timedelta(minutes=10))
    owned=_tp_owned("BEATUSDT","SHORT",17,.889,now)
    result=strategy2_position_tp_contract(row={"notionalUsd":11,"unrealizedPnl":4.11},owned=owned,
        config=Strategy2Config(mode="live"),state=state,portfolio=None,now=now)
    assert result["status"]=="TP bereikt" and result["netProfitUsd"] is not None
    assert result["scheduler"]["status"]=="STALE" and result["scheduler"]["warning"]

def test_blocked_management_leg_does_not_hide_another_tp_candidate():
    now=datetime(2026,8,14,18,0,tzinfo=timezone.utc);cfg=Strategy2Config(take_profit=.015)
    first=_tp_owned("BEATUSDT","SHORT",17,.889,now);second=_tp_owned("ENAUSDT","SHORT",227,.08814,now)
    positions=[{"symbol":"BEATUSDT","positionSide":"SHORT","positionAmt":17,"markPrice":.647,"notional":11,"unRealizedProfit":4.11},
        {"symbol":"ENAUSDT","positionSide":"SHORT","positionAmt":227,"markPrice":.08408,"notional":19.09,"unRealizedProfit":.92}]
    portfolio=PortfolioState(1000,1000,.1,100,100,200)
    selected=next_management_decision(cfg,portfolio,[first,second],positions,
        excluded_actions={("BEATUSDT","SHORT","FULL_TP")})
    assert selected and selected[0].symbol=="ENAUSDT" and selected[1].kind=="FULL_TP"

def test_most_urgent_profitable_position_is_first_management_candidate():
    now=datetime(2026,8,14,18,0,tzinfo=timezone.utc)
    beat=_tp_owned("BEATUSDT","SHORT",17,.889,now);ena=_tp_owned("ENAUSDT","SHORT",227,.08814,now)
    positions=[{"symbol":"BEATUSDT","positionSide":"SHORT","positionAmt":17,"markPrice":.647,"notional":11,"unRealizedProfit":4.11},
        {"symbol":"ENAUSDT","positionSide":"SHORT","positionAmt":227,"markPrice":.08408,"notional":19.09,"unRealizedProfit":.92}]
    assert most_urgent_profitable_owned(Strategy2Config(),[ena,beat],positions)==beat
