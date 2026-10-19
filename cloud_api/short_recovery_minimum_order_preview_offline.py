"""Offline exchange-minimum-aware Recovery reduction preview, never sends orders.

A too-small due quantity is carried forward to the next fixed-anchor trigger.
No artificial top-up, no cycle completion while residual SHORT remains.
"""
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from short_recovery_reduction import plan_reduction


def preview_minimum_aware_reduction(*, state, exchange_short_qty,
                                    minimum_qty, quantity_step, minimum_notional,
                                    executable_price, reduce_only_dust_exempt=False):
    if reduce_only_dust_exempt is not False:
        return {'status':'BLOCKED_UNVERIFIED_DUST_EXEMPTION'}
    decision=plan_reduction(state)
    if decision.get('status')!='PREVIEW_REDUCE_ONLY':
        return decision
    try:
        values=[Decimal(str(x)) for x in (exchange_short_qty,minimum_qty,
                     quantity_step,minimum_notional,executable_price)]
        remaining,min_qty,step,min_notional,price=values
        if (not all(v.is_finite() for v in values) or remaining<=0 or
            min_qty<=0 or step<=0 or min_notional<=0 or price<=0):
            return {'status':'BLOCKED_EXCHANGE_FILTER'}
        due=decision['due_qty']
        if due>remaining:
            return {'status':'BLOCKED_INVENTORY_MISMATCH'}
        # Never round up: that could over-close an unconfirmed SHORT position.
        executable=(due/step).to_integral_value(rounding=ROUND_DOWN)*step
        is_valid=(executable>=min_qty and executable*price>=min_notional)
        at_final=decision['reached_steps']==state.plan.steps
        if not is_valid:
            return {'status':'BLOCKED_FINAL_REMAINDER_UNDER_MINIMUM' if at_final
                    else 'WAIT_MINIMUM_CARRY_FORWARD',
                    'reached_steps':decision['reached_steps'],
                    'carried_due_qty':due,'ordersSent':0,
                    'mayTopUp':False,'newCycleAuthorized':False}
        if at_final and executable<remaining:
            return {'status':'BLOCKED_FINAL_REMAINDER_UNDER_MINIMUM',
                    'reached_steps':decision['reached_steps'],
                    'carried_due_qty':due,'ordersSent':0,
                    'mayTopUp':False,'newCycleAuthorized':False}
        return {'status':'PREVIEW_MINIMUM_VALID_REDUCE_ONLY',
                'reached_steps':decision['reached_steps'],
                'due_qty':executable,'remaining_after':remaining-executable,
                'requiresFreshExchangeFilters':True,
                'requiresCanonicalClaim':True,'ordersSent':0,
                'newCycleAuthorized':False}
    except (InvalidOperation,ValueError,TypeError,KeyError,ZeroDivisionError):
        return {'status':'BLOCKED_EXCHANGE_FILTER'}
