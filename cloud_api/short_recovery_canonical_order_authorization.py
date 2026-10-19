"""One canonical offline authorization entrypoint for hedge/recovery/rehedge intents.

Routes to existing transactional claim implementations. This is not an order
transport and must never authorize authenticated Aster requests.
"""
from short_recovery_lease_fence_offline import (
    reserve_normal_hedge_mock_only,
    reserve_verified_rehedge_mock_only,
)
from short_recovery_order_claim_shadow import reserve as reserve_recovery_claim
from short_recovery_order_claim_shadow import submit_once_offline

def authorize_offline_order(*, order_type, mock_only, **evidence):
    if mock_only is not True:
        return "BLOCKED_OFFLINE_SCOPE"
    if order_type == "AUTO_HEDGE_OPEN":
        return reserve_normal_hedge_mock_only(mock_only=True, **evidence)
    if order_type == "RECOVERY_SHORT_CLOSE":
        if evidence.get("side") != "SHORT" or evidence.get("action") != "CLOSE":
            return "BLOCKED_INTENT_SCOPE"
        return reserve_recovery_claim(**evidence)
    if order_type == "REHEDGE_SHORT_OPEN":
        return reserve_verified_rehedge_mock_only(mock_only=True, **evidence)
    return "BLOCKED_ORDER_TYPE"


def submit_recovery_offline(*, mock_only, coordination_ref, require_shared_fence=True, **evidence):
    """One fail-closed offline transport seam; no unfenced legacy fallback."""
    if mock_only is not True:
        return 'BLOCKED_OFFLINE_SCOPE'
    if coordination_ref is None:
        return 'BLOCKED_SHARED_FENCE_REQUIRED'
    return submit_once_offline(coordination_ref=coordination_ref,
        require_shared_fence=True, **evidence)

def transfer_confirmed_recovery_step_offline(*, mock_only, db, transactional,
        coordination_ref, previous_claim_ref, next_claim_ref, control_ref, account, symbol, cycle,
        previous_intent_id, next_intent_id, next_step, verified_financial_readback):
    """CAS handoff after complete terminal financial proof; never a submit right."""
    from short_recovery_order_claim_shadow import canonical_intent_id
    if mock_only is not True or verified_financial_readback is not True:
        return 'BLOCKED_TERMINAL_FINANCIAL_PROOF'
    if coordination_ref is None or previous_claim_ref is None or next_claim_ref is None or control_ref is None:
        return 'BLOCKED_SHARED_FENCE_REQUIRED'
    if isinstance(next_step,bool) or not isinstance(next_step,int) or next_step not in (2,3,4):
        return 'BLOCKED_NEXT_STEP'
    try:
        expected_previous=canonical_intent_id(account=account,symbol=symbol,cycle=cycle,
            side='SHORT',action='CLOSE',step=next_step-1)
        expected_next=canonical_intent_id(account=account,symbol=symbol,cycle=cycle,
            side='SHORT',action='CLOSE',step=next_step)
    except ValueError:
        return 'BLOCKED_CANONICAL_SCOPE'
    if previous_intent_id!=expected_previous or next_intent_id!=expected_next:
        return 'BLOCKED_CANONICAL_SCOPE'
    @transactional
    def handoff(tx):
        coord=coordination_ref.get(transaction=tx).to_dict()
        previous=previous_claim_ref.get(transaction=tx).to_dict()
        following=next_claim_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if not isinstance(coord,dict) or not isinstance(previous,dict) or following is not None:
            return 'BLOCKED_EVIDENCE_UNAVAILABLE'
        fence=coord.get('recoveryFenceReservation')
        if not isinstance(fence,dict) or (fence.get('account'),fence.get('symbol'),
            fence.get('cycle'),fence.get('intentId'))!=(account,symbol,cycle,previous_intent_id):
            return 'BLOCKED_COORDINATION_CLAIM_MISMATCH'
        if (previous.get('account'),previous.get('symbol'),previous.get('cycle'),
            previous.get('intentId'),previous.get('side'),previous.get('action'),
            previous.get('step'))!=(account,symbol,cycle,previous_intent_id,'SHORT','CLOSE',next_step-1):
            return 'BLOCKED_PRIOR_CLAIM_SCOPE'
        # A caller boolean is never sufficient: require durable, per-execution
        # provenance from the canonical financial reconciliation as well.
        financials=previous.get('executionFinancials')
        if (previous.get('state') != 'CLOSED' or
            not previous.get('orderId') or
            previous.get('fillsComplete') is not True or
            previous.get('incomeHistoryComplete') is not True or
            previous.get('financialVerified') is not True or
            previous.get('terminalVerified') is not True or
            not isinstance(financials,dict) or not financials):
            return 'BLOCKED_PRIOR_CLAIM_UNRESOLVED'
        from decimal import Decimal, InvalidOperation
        try:
            quantities=[]
            for values in financials.values():
                if not isinstance(values,(tuple,list)) or len(values)!=4:
                    return 'BLOCKED_FINANCIAL_PROVENANCE'
                numbers=[Decimal(str(v)) for v in values]
                if not all(n.is_finite() for n in numbers) or numbers[0]<=0 or numbers[2]<0:
                    return 'BLOCKED_FINANCIAL_PROVENANCE'
                quantities.append(numbers[0])
            if sum(quantities,Decimal(0))!=Decimal(str(previous['executedQty'])):
                return 'BLOCKED_FINANCIAL_PROVENANCE'
        except (InvalidOperation,TypeError,ValueError,KeyError):
            return 'BLOCKED_FINANCIAL_PROVENANCE'
        if (not isinstance(control,dict) or control.get('account')!=account
            or control.get('enabled') is not True or control.get('emergencyStop') is not False
            or control.get('closeAllActive') is not False):
            return 'BLOCKED_STOP'
        if isinstance(coord.get('lease'),dict) and coord['lease'].get('token'):
            return 'BLOCKED_LEASE_UNRESOLVED'
        tx.set(next_claim_ref,{'account':account,'symbol':symbol,'cycle':cycle,
            'intentId':next_intent_id,'side':'SHORT','action':'CLOSE',
            'step':next_step,'state':'RESERVED','previousIntentId':previous_intent_id})
        tx.set(coordination_ref,{**coord,'recoveryFenceReservation':{
            'account':account,'symbol':symbol,'cycle':cycle,'intentId':next_intent_id,
            'previousIntentId':previous_intent_id,'state':'RECOVERY_CLAIM_RESERVED'}})
        return 'HANDOFF_VERIFIED_OFFLINE'
    try:
        return handoff(db.transaction())
    except Exception:
        return 'BLOCKED_TRANSACTION_FAILURE'
