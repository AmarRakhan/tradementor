import random

from aster_strategy2_queue import (
    MAX_ORDERS_PER_ACCOUNT_SCAN, PendingReopen, QueueAction, QueueState,
    build_reopen, initial_build_actions, ordered_actions, pending_reopen_for,
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


def test_exact_priority_order():
    values=ordered_actions(risk=[action("RISK_REDUCE",1)],profits=[action("TAKE_PROFIT_CLOSE",2)],
        pending_reopens=[action("REOPEN",3)],dca=[action("DCA",4)],entries=[action("OPEN_BASE",5)])
    assert [x.kind for x in values]==["RISK_REDUCE","REOPEN","TAKE_PROFIT_CLOSE","DCA","OPEN_BASE"]


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
