"""Offline minimum-carry claim reservation in existing canonical fence.

No exchange submission. Filter checks are previews; submit CAS rechecks the
bound quantity, and an external exchange pre-transport revalidation is required.
"""
from decimal import Decimal, InvalidOperation
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_minimum_order_preview_offline import preview_minimum_aware_reduction
from short_recovery_reduction import ReductionState
from short_recovery_contract import Plan
from short_recovery_standalone_offline import RECOVERY


def reserve_minimum_carry_offline(*,db,transactional,selector_ref,position_ref,
        control_ref,coordination_ref,claim_ref,account,symbol,cycle,
        mark,exchange_short_qty,minimum_qty,quantity_step,minimum_notional,
        executable_price):
    try:
        mark=Decimal(str(mark))
        if not mark.is_finite():return 'BLOCKED_MARK'
    except (InvalidOperation,ValueError,TypeError):return 'BLOCKED_MARK'
    @transactional
    def reserve(tx):
        selector=selector_ref.get(transaction=tx).to_dict()
        position=position_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        coordination=coordination_ref.get(transaction=tx).to_dict()
        claim=claim_ref.get(transaction=tx).to_dict()
        if not isinstance(selector,dict) or (selector.get('account'),selector.get('activeStrategy'),selector.get('offlineOnly'))!=(account,RECOVERY,True):
            return 'BLOCKED_STRATEGY'
        if not isinstance(control,dict) or control.get('account')!=account or control.get('enabled') is not True or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
            return 'BLOCKED_STOP'
        if not isinstance(position,dict) or (position.get('account'),position.get('symbol'),position.get('cycle'),position.get('offlineOnly'))!=(account,symbol,cycle,True) or position.get('pending') is not False or position.get('state') not in ('ADOPTED_OFFLINE','RECOVERY_ACTIVE_OFFLINE'):
            return 'BLOCKED_POSITION'
        if claim is not None:return 'BLOCKED_CLAIM_EXISTS'
        if not isinstance(coordination,dict) or coordination.get('recoveryFenceReservation') is not None or coordination.get('lease') is not None:
            return 'BLOCKED_SHARED_FENCE'
        try:
            plan=Plan(Decimal(str(position['anchor'])),Decimal(str(position['originalShortQty'])),
                Decimal(str(position['stepPct'])),position['steps'])
            closed=Decimal(str(position['confirmedClosed']))
            short=Decimal(str(exchange_short_qty))
            if not all(v.is_finite() for v in (closed,short)) or short!=plan.initial_short_qty-closed:
                return 'BLOCKED_INVENTORY'
            result=preview_minimum_aware_reduction(state=ReductionState(plan,closed,mark),
                exchange_short_qty=short,minimum_qty=minimum_qty,quantity_step=quantity_step,
                minimum_notional=minimum_notional,executable_price=executable_price)
        except (TypeError,ValueError,InvalidOperation,KeyError,ArithmeticError):
            return 'BLOCKED_INPUT'
        if result['status']!='PREVIEW_MINIMUM_VALID_REDUCE_ONLY':
            return result['status']
        step=result['reached_steps']
        intent_id=canonical_intent_id(account=account,symbol=symbol,cycle=cycle,
            side='SHORT',action='CLOSE',step=step)
        tx.set(claim_ref,{'account':account,'symbol':symbol,'cycle':cycle,
            'intentId':intent_id,'side':'SHORT','action':'CLOSE','step':step,
            'state':'RESERVED','minimumCarryQuantity':str(result['due_qty']),
            'minimumCarryOffline':True,'requiresFreshExchangeFilters':True,
            'financialSettlement':'UNRECONCILED'})
        tx.set(coordination_ref,{**coordination,'recoveryFenceReservation':{
            'account':account,'symbol':symbol,'cycle':cycle,'intentId':intent_id,
            'state':'RECOVERY_CLAIM_RESERVED'}})
        return 'MINIMUM_CARRY_RESERVED_OFFLINE'
    try:return reserve(db.transaction())
    except Exception:return 'BLOCKED_TRANSACTION'
