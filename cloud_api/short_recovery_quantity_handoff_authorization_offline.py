"""OFFLINE quantity-only SHORT-step handoff using existing canonical claim/fence.

Order-quantity finality is independent from PnL/fee/funding settlement.
No network or live Aster client. Financial TP/cycle settlement remains blocked.
"""
from decimal import Decimal, InvalidOperation
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_standalone_offline import RECOVERY
from short_recovery_standalone_execution_evidence_offline import inspect_terminal_short_close_offline


def handoff_verified_quantity_offline(*, mock_only, db, transactional, client,
        selector_ref, position_ref, previous_claim_ref, next_claim_ref,
        coordination_ref, control_ref, account, symbol, cycle, next_step,
        exchange_short_quantity):
    """One CAS transfers original canonical fence, never submits an order."""
    if mock_only is not True or getattr(client,'offline_mock_only',False) is not True:
        return 'BLOCKED_OFFLINE_ONLY'
    if type(next_step) is not int or next_step < 2:
        return 'BLOCKED_STEP'
    try:
        prev_id=canonical_intent_id(account=account,symbol=symbol,cycle=cycle,
            side='SHORT',action='CLOSE',step=next_step-1)
        next_id=canonical_intent_id(account=account,symbol=symbol,cycle=cycle,
            side='SHORT',action='CLOSE',step=next_step)
        short=Decimal(str(exchange_short_quantity))
        if not short.is_finite() or short<0:
            return 'BLOCKED_INVENTORY'
    except (ValueError,InvalidOperation,TypeError):
        return 'BLOCKED_INPUT'

    old=previous_claim_ref.get(transaction=db.transaction()).to_dict()
    pos=position_ref.get(transaction=db.transaction()).to_dict()
    if not isinstance(pos,dict) or pos.get('account')!=account or pos.get('symbol')!=symbol or pos.get('cycle')!=cycle:
        return 'BLOCKED_POSITION'
    try:
        initial=Decimal(str(pos['originalShortQty']))
        steps=pos['steps']
        if type(steps) is not int or not 2<=next_step<=steps or initial<=0 or not initial.is_finite():
            return 'BLOCKED_STEPS'
        per_step=initial/steps
        expected_short=initial-per_step*(next_step-1)
        if short!=expected_short:
            return 'BLOCKED_INVENTORY_MISMATCH'
    except (KeyError,InvalidOperation,ValueError,TypeError):
        return 'BLOCKED_POSITION'
    evidence=inspect_terminal_short_close_offline(
        client=client,account=account,symbol=symbol,cycle=cycle,
        step=next_step-1,claim=old,expected_quantity=per_step)
    if evidence.get('status')!='ORDER_EXECUTION_VERIFIED_UNSETTLED':
        return evidence.get('status','BLOCKED_ORDER_EVIDENCE')

    @transactional
    def commit(tx):
        selector=selector_ref.get(transaction=tx).to_dict()
        position=position_ref.get(transaction=tx).to_dict()
        previous=previous_claim_ref.get(transaction=tx).to_dict()
        following=next_claim_ref.get(transaction=tx).to_dict()
        coordination=coordination_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if not isinstance(selector,dict) or (selector.get('account'),selector.get('activeStrategy'),selector.get('offlineOnly'))!=(account,RECOVERY,True):
            return 'BLOCKED_STRATEGY'
        if not isinstance(control,dict) or control.get('account')!=account or control.get('enabled') is not True or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
            return 'BLOCKED_STOP'
        if not isinstance(position,dict) or position.get('offlineOnly') is not True or position.get('state') not in ('ADOPTED_OFFLINE','RECOVERY_ACTIVE_OFFLINE') or position.get('pending') is not True:
            return 'BLOCKED_POSITION_STATE'
        if (position.get('account'),position.get('symbol'),position.get('cycle'),position.get('steps'))!=(account,symbol,cycle,steps):
            return 'BLOCKED_POSITION_SCOPE'
        try:
            if Decimal(str(position['originalShortQty']))!=initial or Decimal(str(position['confirmedClosed']))!=initial-short:
                return 'BLOCKED_CUMULATIVE_QUANTITY'
        except (KeyError,ValueError,InvalidOperation,TypeError):
            return 'BLOCKED_QUANTITY'
        if previous!=old or not isinstance(previous,dict) or (previous.get('account'),previous.get('symbol'),previous.get('cycle'),previous.get('intentId'),previous.get('step'),previous.get('side'),previous.get('action'))!=(account,symbol,cycle,prev_id,next_step-1,'SHORT','CLOSE'):
            return 'BLOCKED_PREVIOUS_CLAIM_CHANGED'
        if previous.get('offlineOrderTerminalVerified') is not True or previous.get('offlineTerminalQty')!=str(per_step) or previous.get('offlineFundingStatus')!='UNRECONCILED' or previous.get('offlineNextClaimAuthorized') is not False:
            return 'BLOCKED_PREVIOUS_EXECUTION'
        if tuple(tuple(x) for x in previous.get('offlineTerminalExecutions',[]))!=evidence['executionFinancials']:
            return 'BLOCKED_EXECUTION_DRIFT'
        if following is not None:
            return 'BLOCKED_NEXT_CLAIM_EXISTS'
        fence=coordination.get('recoveryFenceReservation') if isinstance(coordination,dict) else None
        if not isinstance(fence,dict) or (fence.get('account'),fence.get('symbol'),fence.get('cycle'),fence.get('intentId'),fence.get('state'))!=(account,symbol,cycle,prev_id,'RECOVERY_SUBMITTING_RECONCILE_ONLY'):
            return 'BLOCKED_SHARED_FENCE'
        if coordination.get('lease') is not None:
            return 'BLOCKED_LEASE'
        # The existing canonical submit CAS is the only future transport path.
        tx.set(next_claim_ref,{'account':account,'symbol':symbol,'cycle':cycle,
            'intentId':next_id,'side':'SHORT','action':'CLOSE','step':next_step,
            'state':'RESERVED','previousIntentId':prev_id,'authorizationBasis':'TERMINAL_QUANTITY_OFFLINE',
            'financialSettlement':'UNRECONCILED'})
        tx.set(coordination_ref,{**coordination,'recoveryFenceReservation':{
            'account':account,'symbol':symbol,'cycle':cycle,'intentId':next_id,
            'previousIntentId':prev_id,'state':'RECOVERY_CLAIM_RESERVED'}})
        tx.set(position_ref,{**position,'pending':False})
        return 'QUANTITY_HANDOFF_RESERVED_OFFLINE'
    try:
        return commit(db.transaction())
    except Exception:
        return 'BLOCKED_TRANSACTION'
