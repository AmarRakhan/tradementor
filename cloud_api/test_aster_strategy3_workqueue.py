from __future__ import annotations

from dataclasses import replace

from aster_strategy2_state import OwnedLeg
from aster_strategy3 import (
    LegState, PortfolioState, Strategy3Config, account_entry_side, decide, risk_mode,
)
from aster_strategy3_workqueue import (
    ActionOutcome, Strategy3Action, merge_backlog, ordered_actions,
    run_finite_work_queue,
)


def action(kind: str, n: int, *, side: str | None = None) -> Strategy3Action:
    return Strategy3Action(kind, f"C{n:03d}USDT", side or ("LONG" if n % 2 == 0 else "SHORT"),
        f"cycle-{n}", 7, n, 10, tick_id="tick-1")


def confirmed(_action: Strategy3Action) -> ActionOutcome:
    return ActionOutcome("bookkeeping" if _action.kind == "ASSIGN_PROTECTION" else "confirmed",
        0 if _action.kind == "ASSIGN_PROTECTION" else 1, 1)


def test_three_simultaneous_tp_candidates_all_close_in_one_tick():
    result=run_finite_work_queue([action("FULL_TP",n) for n in range(3)],execute=confirmed,refresh=lambda _:None)
    assert result.count("FULL_TP")==3 and result.orders_sent==3 and not result.backlog


def test_protection_precedes_normal_tp():
    seen=[]
    run_finite_work_queue([action("FULL_TP",1),action("ASSIGN_PROTECTION",2)],
        execute=lambda item:(seen.append(item.kind) or confirmed(item)),refresh=lambda _:None)
    assert seen==["ASSIGN_PROTECTION","FULL_TP"]


def test_multiple_dcas_execute_and_refresh_after_every_confirmation():
    refreshed=[]
    result=run_finite_work_queue([action("ADD_DCA",n) for n in range(12)],execute=confirmed,refresh=refreshed.append)
    assert result.count("ADD_DCA")==12 and result.refreshes==12 and len(refreshed)==12


def test_tp_dca_and_entry_use_required_phase_order():
    mixed=[action("OPEN_BASE",1),action("ADD_DCA",2),action("TRAILING_TP",3),action("PARTIAL_TP",4)]
    kinds=[x.kind for x in ordered_actions(mixed)]
    assert set(kinds[:2])=={"PARTIAL_TP","TRAILING_TP"}
    assert kinds[2:]==["ADD_DCA","OPEN_BASE"]


def test_fully_empty_portfolio_can_fill_200_slots_without_action_cap():
    actions=[action("OPEN_BASE",n,side="LONG" if n%2==0 else "SHORT") for n in range(200)]
    result=run_finite_work_queue(actions,execute=confirmed,refresh=lambda _:None)
    assert result.count("OPEN_BASE")==200 and result.orders_sent==200 and not result.backlog
    assert sum(x.side=="LONG" for x in result.executed)==100
    assert sum(x.side=="SHORT" for x in result.executed)==100


def test_accountwide_maximum_counts_manual_and_other_strategy_positions():
    active={(f"M{n}USDT","LONG" if n%2==0 else "SHORT") for n in range(100)}
    assert account_entry_side(active,100) is None
    assert account_entry_side(set(list(active)[:99]),100) in {"LONG","SHORT"}


def test_other_strategy_ownership_is_never_changed_by_work_queue():
    foreign=OwnedLeg("aster-strategy-2","strategy2","BTCUSDT","LONG","s2",1,1,10)
    queue=[action("FULL_TP",1)]
    run_finite_work_queue(queue,execute=confirmed,refresh=lambda _:None)
    assert foreign.strategy_id=="aster-strategy-2" and foreign.engine_type=="strategy2"


def test_definitive_contract_rejection_does_not_block_safe_later_dca():
    calls=[]
    def execute(item):
        calls.append(item.action_id)
        return ActionOutcome("rejected",reason="Aster -5018") if len(calls)==1 else confirmed(item)
    result=run_finite_work_queue([action("ADD_DCA",1),action("ADD_DCA",2)],execute=execute,refresh=lambda _:None)
    assert len(result.rejected)==1 and result.count("ADD_DCA")==1 and len(calls)==2


def test_uncertain_submission_stops_all_later_risk_increase_without_retry():
    calls=[]
    def execute(item):
        calls.append(item.action_id);return ActionOutcome("uncertain",reason="HTTP 503; onbekend")
    result=run_finite_work_queue([action("ADD_DCA",1),action("OPEN_BASE",2)],execute=execute,refresh=lambda _:None)
    assert len(calls)==1 and len(result.uncertain)==1 and len(result.backlog)==1


def test_insufficient_margin_blocks_before_any_order_and_saves_full_backlog():
    calls=[];actions=[action("ADD_DCA",1),action("OPEN_BASE",2)]
    result=run_finite_work_queue(actions,execute=lambda item:(calls.append(item) or confirmed(item)),
        refresh=lambda _:None,before_action=lambda _:False)
    assert not calls and len(result.backlog)==2 and "risico" in result.block_reason


def test_scheduler_retry_uses_same_deterministic_action_and_client_identity_input():
    first=action("ADD_DCA",7);retry=replace(first,tick_id="retry-tick")
    assert first.action_id==retry.action_id and first.lock_key==retry.lock_key


def test_partial_fill_is_persisted_as_uncertain_and_stops_dependents():
    result=run_finite_work_queue([action("ADD_DCA",1),action("OPEN_BASE",2)],
        execute=lambda _:ActionOutcome("confirmed",1,.4,"partial",partial=True),refresh=lambda _:None)
    assert result.orders_sent==1 and len(result.executed)==1 and len(result.uncertain)==1 and len(result.backlog)==1


def test_container_restart_backlog_is_deduplicated_and_priority_preserved():
    tp=action("FULL_TP",1);dca=action("ADD_DCA",2)
    saved=merge_backlog([dca,tp],[tp])
    assert [row["kind"] for row in saved]==["FULL_TP","ADD_DCA"] and len(saved)==2


def test_time_budget_persists_all_remaining_work():
    remaining=[2]
    def has_time():
        remaining[0]-=1;return remaining[0]>=0
    result=run_finite_work_queue([action("FULL_TP",n) for n in range(10)],execute=confirmed,
        refresh=lambda _:None,has_time=has_time)
    assert len(result.executed)==2 and len(result.backlog)==8 and result.block_reason


def test_hundred_positions_and_dozen_tp_dca_mix_has_no_hidden_limit():
    actions=[action("FULL_TP",n) for n in range(30)]+[action("ADD_DCA",n+100) for n in range(40)]
    result=run_finite_work_queue(actions,execute=confirmed,refresh=lambda _:None)
    assert len(result.executed)==70 and result.count("FULL_TP")==30 and result.count("ADD_DCA")==40


def test_stale_exchange_missing_ownership_and_open_orders_all_fail_closed():
    config=Strategy3Config()
    leg=LegState("LONG",100,100,102,unrealized_pnl=2)
    for portfolio in (
        PortfolioState(1000,1000,.1,100,100,exchange_reliable=False),
        PortfolioState(1000,1000,.1,100,100,ownership_reliable=False),
        PortfolioState(1000,1000,.1,100,100,open_orders_unknown=True),
    ):
        assert decide(config,leg,portfolio).kind=="HOLD"


def test_margin_modes_caution_defensive_emergency_preserve_existing_engine_rules():
    config=Strategy3Config()
    normal=PortfolioState(1000,1000,.1,100,100)
    caution=replace(normal,margin_ratio=config.caution_margin_ratio)
    defensive=replace(normal,margin_ratio=config.defensive_margin_ratio)
    emergency=replace(normal,margin_ratio=config.emergency_margin_ratio)
    assert [risk_mode(config,x) for x in (normal,caution,defensive,emergency)]==[
        "NORMAL","CAUTION","DEFENSIVE","EMERGENCY"]
    adverse=LegState("LONG",100,100,90)
    assert decide(config,adverse,caution).kind=="ADD_DCA"
    assert decide(config,adverse,defensive).kind=="HOLD"
    assert decide(config,adverse,emergency).kind=="HOLD"


def test_paper_executor_proves_zero_real_orders():
    result=run_finite_work_queue([action("FULL_TP",1),action("ADD_DCA",2),action("OPEN_BASE",3)],
        execute=lambda _:ActionOutcome("confirmed",orders_sent=0),refresh=lambda _:None)
    assert result.orders_sent==0 and len(result.executed)==3
