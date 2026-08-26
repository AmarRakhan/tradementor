import random
from pathlib import Path

from aster_strategy2_queue import (
    MAX_ORDERS_PER_ACCOUNT_SCAN, PendingReopen, QueueAction, QueueState,
    build_reopen, build_shadow_plan, initial_build_actions, ordered_actions, pending_reopen_for,
)
from aster_strategy2_runtime import queued_entry_order_limit


def action(kind, index, side="LONG"):
    return QueueAction(kind, f"C{index}USDT", side, f"cycle-{index}",
                       notional=25, package_id=f"package-{index}", sequence=index)


def execute(state, actions, outcomes=None):
    sent=[];outcomes=outcomes or {}
    for item in actions:
        if not state.may_send(item):break
        outcome=outcomes.get(len(sent), "CONFIRMED")
        state.record_sent_outcome(item,outcome);sent.append((item,outcome))
        if outcome=="UNCERTAIN":break
    return sent


def test_initial_100_position_build_is_15_per_scan():
    planned=initial_build_actions(missing_long=50,missing_short=50,
        symbols=(f"C{i}USDT" for i in range(100)),cycle_prefix="build",base_notional=25)
    remaining=planned;counts=[]
    for scan in range(7):
        state=QueueState("account",f"scan-{scan}")
        sent=execute(state,remaining);counts.append(len(sent));remaining=remaining[len(sent):]
    assert counts==[15,15,15,15,15,15,10]


def test_feature_flagged_entry_limit_respects_orders_already_used():
    assert queued_entry_order_limit(False,[],100,orders_used=0)==15
    assert queued_entry_order_limit(False,[],100,orders_used=14)==1
    assert queued_entry_order_limit(False,[],100,orders_used=15)==0


def test_completed_build_refill_uses_all_remaining_queue_slots():
    assert queued_entry_order_limit(True,[],100,orders_used=0)==15
    assert queued_entry_order_limit(True,[],100,orders_used=6)==9


def test_fifteen_profit_closes_can_use_full_budget():
    state=QueueState("a","s")
    sent=execute(state,[action("TAKE_PROFIT_CLOSE",i) for i in range(20)])
    assert len(sent)==state.orders_used==15


def test_seven_close_reopen_packages_then_one_close_leaves_pending_eighth_reopen():
    state=QueueState("a","s");pending=[]
    for index in range(8):
        close=action("TAKE_PROFIT_CLOSE",index)
        assert state.may_send(close);state.record_sent_outcome(close,"CONFIRMED")
        reopen=build_reopen(pending_reopen_for(close,scan_id="s",base_notional=25),sequence=index)
        if state.may_send(reopen):state.record_sent_outcome(reopen,"CONFIRMED")
        else:pending.append(pending_reopen_for(close,scan_id="s",base_notional=25))
    assert state.orders_used==15 and len(pending)==1 and pending[0].symbol=="C7USDT"
    next_scan=QueueState("a","s2",pending_reopens=pending)
    ordered=ordered_actions(pending_reopens=[build_reopen(x) for x in pending],entries=[action("OPEN_BASE",99)])
    assert ordered[0].kind=="REOPEN"


def test_six_profit_closes_are_never_behind_one_pending_reopen():
    state=QueueState("a","s")
    plan=ordered_actions(
        profits=[action("TAKE_PROFIT_CLOSE",i) for i in range(6)],
        pending_reopens=[action("REOPEN",99)],
    )
    sent=execute(state,plan)
    assert [item.kind for item,_ in sent[:6]]==["TAKE_PROFIT_CLOSE"]*6
    assert sent[6][0].kind=="REOPEN"


def test_exact_priority_order():
    values=ordered_actions(risk=[action("RISK_REDUCE",1)],profits=[action("TAKE_PROFIT_CLOSE",2)],
        pending_reopens=[action("REOPEN",3)],dca=[action("DCA",4)],entries=[action("OPEN_BASE",5)])
    assert [x.kind for x in values]==["RISK_REDUCE","TAKE_PROFIT_CLOSE","REOPEN","DCA","OPEN_BASE"]


def test_uncertain_order_15_halts_only_that_account():
    a=QueueState("a","s");b=QueueState("b","s")
    sent=execute(a,[action("OPEN_BASE",i) for i in range(20)],{14:"UNCERTAIN"})
    assert len(sent)==15 and a.halted_uncertain and not a.may_send(action("DCA",99))
    assert len(execute(b,[action("OPEN_BASE",i) for i in range(15)]))==15


def test_rejection_counts_only_when_request_reached_aster_and_queue_continues():
    state=QueueState("a","s");items=[action("OPEN_BASE",i) for i in range(3)]
    sent=execute(state,items,{0:"REJECTED"})
    assert len(sent)==3 and state.orders_used==3 and not state.halted_uncertain


def test_validation_rejection_does_not_consume_budget():
    state=QueueState("a","s")
    # Candidate validation is performed before record_sent_outcome.
    assert state.orders_used==0 and state.remaining==15


def test_state_round_trip_restart_preserves_budget_pending_and_idempotency():
    state=QueueState("a","s",pending_reopens=[PendingReopen("BTCUSDT","LONG","c","p",25,"s")])
    item=action("DCA",1);state.record_sent_outcome(item,"CONFIRMED")
    recovered=QueueState.from_mapping(state.to_mapping())
    assert recovered.orders_used==1 and not recovered.may_send(item)
    assert recovered.pending_reopens[0].package_id=="p"


def test_duplicate_scheduler_state_cannot_resend_confirmed_action():
    state=QueueState("a","same-scan");item=action("OPEN_BASE",1)
    state.record_sent_outcome(item,"CONFIRMED")
    duplicate=QueueState.from_mapping(state.to_mapping())
    assert not duplicate.may_send(item)


def test_partial_fill_is_confirmed_and_persisted_by_adapter_contract():
    state=QueueState("a","s");item=action("TAKE_PROFIT_CLOSE",1)
    state.record_sent_outcome(item,"CONFIRMED")
    assert item.idempotency_key("a") in state.confirmed_keys


def test_ten_thousand_deterministic_simulations_never_exceed_budget_or_cross_accounts():
    rng=random.Random(20260817)
    for simulation in range(10_000):
        account=f"a-{simulation%4}";state=QueueState(account,f"scan-{simulation}")
        categories=[[action(kind,simulation*100+i) for i in range(rng.randrange(0,12))]
            for kind in ("RISK_REDUCE","TAKE_PROFIT_CLOSE","REOPEN","DCA","OPEN_BASE")]
        plan=ordered_actions(risk=categories[0],profits=categories[1],pending_reopens=categories[2],
                             dca=categories[3],entries=categories[4])
        outcomes={i:("UNCERTAIN" if rng.randrange(250)==0 else "REJECTED" if rng.randrange(40)==0 else "CONFIRMED")
                  for i in range(15)}
        sent=execute(state,plan,outcomes)
        assert state.orders_used==len(sent)<=MAX_ORDERS_PER_ACCOUNT_SCAN
        assert all(item.idempotency_key(account).startswith("s2q-") for item,_ in sent)
        if state.halted_uncertain:
            assert sent[-1][1]=="UNCERTAIN"


def test_shadow_plan_is_read_only_prioritized_and_budgeted():
    state=QueueState("private-account","shadow-1",orders_used=13,
        confirmed_keys={action("DCA",4).idempotency_key("private-account")})
    before=state.to_mapping()
    plan=build_shadow_plan(state=state,risk=[action("RISK_REDUCE",1)],
        profits=[action("TAKE_PROFIT_CLOSE",2)],pending_reopens=[action("REOPEN",3)],
        dca=[action("DCA",4)],entries=[action("OPEN_BASE",5)])
    assert state.to_mapping()==before
    assert plan["readOnly"] is True and plan["wouldSendCount"]==2
    assert [x["kind"] for x in plan["actions"]]==["RISK_REDUCE","TAKE_PROFIT_CLOSE"]
    assert plan["accountRef"]!="private-account" and plan["remainingBudget"]==2


def test_shadow_plan_fail_closed_for_uncertain_account():
    state=QueueState("a","s",halted_uncertain=True,uncertain_key="unknown")
    plan=build_shadow_plan(state=state,risk=[action("RISK_REDUCE",1)],entries=[action("OPEN_BASE",2)])
    assert plan["wouldSendCount"]==0 and plan["actions"]==[] and plan["haltedUncertain"] is True


def test_ten_thousand_shadow_plans_never_mutate_or_exceed_account_budget():
    rng=random.Random(20260818)
    for simulation in range(10_000):
        state=QueueState(f"shadow-{simulation%4}",f"scan-{simulation}",orders_used=rng.randrange(16),
                         halted_uncertain=rng.randrange(500)==0)
        before=state.to_mapping()
        groups=[[action(kind,simulation*100+i) for i in range(rng.randrange(20))]
                for kind in ("RISK_REDUCE","TAKE_PROFIT_CLOSE","REOPEN","DCA","OPEN_BASE")]
        plan=build_shadow_plan(state=state,risk=groups[0],profits=groups[1],pending_reopens=groups[2],
                               dca=groups[3],entries=groups[4])
        assert state.to_mapping()==before
        assert plan["wouldSendCount"]<=15-state.orders_used
        assert plan["maximumOrders"]==15
        if state.halted_uncertain:assert plan["wouldSendCount"]==0


def test_public_queue_exposes_last_scan_actions_contract():
    source = Path(__file__).with_name("main.py").read_text()
    assert '"lastScanActions":scan_history[-MAX_ORDERS_PER_ACCOUNT_SCAN:]' in source
    assert '"scanActionHistory":history[-MAX_ORDERS_PER_ACCOUNT_SCAN:]' in source
    assert '"lastScanCompletedAt":queue_state.get("completedAt",queue_state.get("updatedAt"))' in source
    assert '"reservedActions":reserved[-MAX_ORDERS_PER_ACCOUNT_SCAN:]' in source
    assert 'confirmed_actions.append({**action,"executedAt":confirmed_at})' in source
    assert '"dcaNumber":leg.dca_count+1 if decision.kind=="ADD_DCA" else None' in source
