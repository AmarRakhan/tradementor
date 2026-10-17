"""Offline order-intent reservation; intentionally never sends orders."""
from short_recovery_firestore_mock import decode

def reserve(*,db,transactional,marker_ref,owner_ref,ledger_ref,claim_ref,account,symbol,cycle,intent_id,now,lease_seconds=45,control_ref=None):
    if not all((account,symbol,cycle,intent_id)) or lease_seconds<=0:return 'BLOCKED_INPUT'
    if control_ref is None:return 'BLOCKED_CONTROL_UNAVAILABLE'
    @transactional
    def attempt(tx):
        marker=marker_ref.get(transaction=tx).to_dict()
        owner=owner_ref.get(transaction=tx).to_dict()
        stock=ledger_ref.get(transaction=tx).to_dict()
        claim=claim_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if not isinstance(marker,dict) or (marker.get('account'),marker.get('symbol'),marker.get('cycleId'),marker.get('state'))!=(account,symbol,cycle,'SUSPECT'):
            return 'BLOCKED_MARKER'
        if not isinstance(owner,dict) or (owner.get('account'),owner.get('symbol'),owner.get('cycleId'))!=(account,symbol,cycle) or owner.get('ownerSide')!='SHORT' or owner.get('ownershipVerified') is not True or owner.get('cycleConfirmed') is not True or owner.get('state') not in ('PARTIAL','FINAL_PENDING'):
            return 'BLOCKED_OWNER'
        if not isinstance(stock,dict) or (stock.get('account'),stock.get('symbol'))!=(account,symbol) or not any(a.cycle_id==cycle and a.remaining>0 for a in decode(stock).allocations):
            return 'BLOCKED_LEDGER'
        if claim is not None:
            if (claim.get('account'),claim.get('symbol'),claim.get('cycle'))!=(account,symbol,cycle):return 'BLOCKED_CLAIM_SCOPE'
            if claim.get('intentId')==intent_id:
                # Existing claims are evidence to reconcile, not new authorization.
                # A disabled/stopped account must never receive a fresh GO.
                if not isinstance(control,dict) or control.get('account')!=account or control.get('enabled') is not True or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
                    return 'BLOCKED_RECOVERY_DISABLED_OR_STOPPED'
                return 'ALREADY_RESERVED'
            # A stale lease is NOT proof an exchange submission did not happen.
            return 'BLOCKED_UNRESOLVED_CLAIM'
        if not isinstance(control,dict) or control.get('account')!=account or control.get('enabled') is not True or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
            return 'BLOCKED_RECOVERY_DISABLED_OR_STOPPED'
        tx.set(claim_ref,{'account':account,'symbol':symbol,'cycle':cycle,'intentId':intent_id,
                          'state':'RESERVED','reservedAt':now,'leaseUntil':now+lease_seconds})
        return 'RESERVED_SHADOW'
    return attempt(db.transaction())

def pre_submit_check(*, db, transactional, claim_ref, control_ref, account, symbol, cycle, intent_id, account_close_guard):
    """Offline pre-submit revalidation; never sends an order.

    The caller-supplied guard must be the established account pre-submit guard.
    This check does not constitute an atomic guarantee across check -> submit.
    """
    if not callable(account_close_guard) or control_ref is None:
        return 'BLOCKED_GUARD_UNAVAILABLE'
    @transactional
    def check(tx):
        claim=claim_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),claim.get('cycle'),claim.get('intentId'))!=(account,symbol,cycle,intent_id) or claim.get('state')!='RESERVED':
            return 'BLOCKED_CLAIM_NOT_RESERVED'
        if not isinstance(control,dict) or control.get('account')!=account or control.get('enabled') is not True or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
            return 'BLOCKED_RECOVERY_DISABLED_OR_STOPPED'
        return 'PREFLIGHT_SHADOW_ONLY'
    result=check(db.transaction())
    if result!='PREFLIGHT_SHADOW_ONLY':return result
    try:
        account_close_guard()
    except Exception:
        return 'BLOCKED_ACCOUNT_PRE_SUBMIT_GUARD'
    return 'PREFLIGHT_SHADOW_ONLY'
