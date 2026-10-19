"""Offline-only CAS handoff checkpoint; deliberately NOT a submission right.

A confirmed individual SHORT close may produce one canonical *WAITING* next
claim, but may never reserve it for transport without the existing financial
authorization. Funding stays unreconciled and is not a profit/budget input.
"""
from decimal import Decimal, InvalidOperation
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_standalone_offline import RECOVERY


def stage_next_short_step_offline(*, db, transactional, selector_ref,
        position_ref, prior_claim_ref, next_claim_ref, coordination_ref,
        control_ref, account, symbol, cycle, next_step):
    if type(next_step) is not int or next_step < 2:
        return 'BLOCKED_STEP'
    try:
        previous_id = canonical_intent_id(account=account,symbol=symbol,
            cycle=cycle,side='SHORT',action='CLOSE',step=next_step-1)
        next_id = canonical_intent_id(account=account,symbol=symbol,
            cycle=cycle,side='SHORT',action='CLOSE',step=next_step)
    except (ValueError,TypeError):
        return 'BLOCKED_SCOPE'

    @transactional
    def stage(tx):
        selector=selector_ref.get(transaction=tx).to_dict()
        position=position_ref.get(transaction=tx).to_dict()
        previous=prior_claim_ref.get(transaction=tx).to_dict()
        next_claim=next_claim_ref.get(transaction=tx).to_dict()
        coordination=coordination_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if (not isinstance(selector,dict) or
            (selector.get('account'),selector.get('activeStrategy'),selector.get('offlineOnly'))
            != (account,RECOVERY,True)):
            return 'BLOCKED_STRATEGY'
        if (not isinstance(control,dict) or control.get('account')!=account
            or control.get('enabled') is not True
            or control.get('emergencyStop') is not False
            or control.get('closeAllActive') is not False):
            return 'BLOCKED_STOP'
        if (not isinstance(position,dict) or
            (position.get('account'),position.get('symbol'),position.get('cycle'),
             position.get('offlineOnly'))!=(account,symbol,cycle,True)):
            return 'BLOCKED_POSITION'
        if type(position.get('steps')) is not int or not 2<=next_step<=position['steps']:
            return 'BLOCKED_STEP'
        if (not isinstance(previous,dict) or
            (previous.get('account'),previous.get('symbol'),previous.get('cycle'),
             previous.get('intentId'),previous.get('side'),previous.get('action'),
             previous.get('step')) !=
            (account,symbol,cycle,previous_id,'SHORT','CLOSE',next_step-1) or
            previous.get('offlineOrderTerminalVerified') is not True or
            previous.get('offlineFundingStatus')!='UNRECONCILED' or
            previous.get('offlineFinancialSettlement')!='PENDING' or
            previous.get('offlineNextClaimAuthorized') is not False):
            return 'BLOCKED_PRIOR_EXECUTION'
        if (not isinstance(previous.get('offlineTerminalExecutions'),list) or
            not previous['offlineTerminalExecutions']):
            return 'BLOCKED_EXECUTION_MISSING'
        try:
            recorded=Decimal(str(previous['offlineTerminalQty']))
            initial=Decimal(str(position['originalShortQty']))
            closed=Decimal(str(position['confirmedClosed']))
            required=initial*Decimal(next_step-1)/Decimal(position['steps'])
            if (not all(x.is_finite() for x in (recorded,initial,closed)) or
                initial<=0 or recorded<=0 or closed!=required or
                recorded!=initial/Decimal(position['steps'])):
                return 'BLOCKED_CUMULATIVE_QUANTITY'
        except (TypeError,KeyError,ValueError,InvalidOperation,ZeroDivisionError):
            return 'BLOCKED_QUANTITY'
        fence=coordination.get('recoveryFenceReservation') if isinstance(coordination,dict) else None
        if (not isinstance(fence,dict) or
            (fence.get('account'),fence.get('symbol'),fence.get('cycle'),
             fence.get('intentId'))!=(account,symbol,cycle,previous_id) or
            fence.get('state')!='RECOVERY_SUBMITTING_RECONCILE_ONLY' or
            isinstance(coordination.get('lease'),dict)):
            return 'BLOCKED_COORDINATION'
        expected_next={'account':account,'symbol':symbol,'cycle':cycle,
            'intentId':next_id,'side':'SHORT','action':'CLOSE',
            'step':next_step,'state':'WAIT_FINANCIAL_AUTHORIZATION',
            'previousIntentId':previous_id,'offlineOnly':True,
            'nextClaimAuthorized':False}
        if next_claim is not None:
            return ('ALREADY_STAGED_NO_SUBMIT_RIGHT' if next_claim==expected_next
                    else 'BLOCKED_NEXT_CLAIM_EXISTS')
        tx.set(next_claim_ref,expected_next)
        # Do NOT transfer the fence or clear pending: neither state grants
        # any new order rights. This checkpoint is an audit observation.
        return 'STAGED_WAITING_NO_SUBMIT_RIGHT'
    try:
        return stage(db.transaction())
    except Exception:
        return 'BLOCKED_TRANSACTION'
