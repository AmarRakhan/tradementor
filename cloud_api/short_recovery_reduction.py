"""Pure order-free reduction planner. Exchange executor integration remains gated.

Plans reduce-only intents but never sends an order. The existing reconciler must
skip deliberate partial hedge ownership before this can be enabled.
"""
from decimal import Decimal
from dataclasses import dataclass
from short_recovery_contract import Plan, D

@dataclass(frozen=True)
class ReductionState:
    plan: Plan
    confirmed_closed: Decimal
    mark: Decimal
    pending: bool = False
    cycle_active: bool = True
    verified: bool = True

def plan_reduction(state: ReductionState):
    p=state.plan
    if not state.cycle_active or not state.verified: return {"status":"BLOCKED"}
    if state.pending: return {"status":"WAIT_PENDING"}
    if state.confirmed_closed < 0 or state.confirmed_closed > p.initial_short_qty:
        return {"status":"BLOCKED_BAD_STATE"}
    reached=sum(state.mark <= p.trigger(n) for n in range(1,p.steps+1))
    target=p.cumulative_target_closed(reached)
    due=max(D(0),target-state.confirmed_closed)
    if due==0:
        return {"status":"WAIT_OR_HOLD","reached_steps":reached,"due_qty":D(0)}
    return {"status":"PREVIEW_REDUCE_ONLY","reached_steps":reached,"due_qty":due,
            "requires_exchange_revalidation":True,"requires_atomic_order_claim":True,
            "requires_confirmed_fill":True}

def preview_after_fill(state: ReductionState, confirmed_fill_qty):
    qty=D(confirmed_fill_qty)
    if qty <= 0: raise ValueError("no confirmed fill")
    if state.confirmed_closed+qty>state.plan.initial_short_qty:
        raise ValueError("oversell")
    return ReductionState(state.plan,state.confirmed_closed+qty,state.mark,
                          pending=False,cycle_active=state.cycle_active,verified=state.verified)

def rehedge_permission(state: ReductionState, *, remaining_exchange_short_qty,
                       long_qty, net_exit_due=False, pending=False):
    if net_exit_due: return "EXIT_INSTEAD"
    if pending or state.pending: return "WAIT_PENDING"
    if long_qty<=0: return "BLOCKED_NO_LONG"
    if state.confirmed_closed != state.plan.initial_short_qty: return "BLOCKED_NOT_FINAL"
    if D(remaining_exchange_short_qty)!=0: return "BLOCKED_SHORT_NOT_ZERO"
    return "PREVIEW_REHEDGE_1_TO_1"
