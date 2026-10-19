"""Read-only, offline-only bridge between standalone decisions and canonical claims.

NO orders, reserve, submit, retries or financial settlement in this module.
This is only a prerequisite, never a transport authorization. A future
transactional executor must recheck the strategy selector INSIDE its submit CAS.
"""
from decimal import Decimal, InvalidOperation
from short_recovery_standalone_offline import RECOVERY
from short_recovery_order_claim_shadow import canonical_intent_id


def check_standalone_canonical_claim_offline(*, db, transactional, selector_ref,
        position_ref, claim_ref, control_ref, coordination_ref, account, symbol,
        cycle, action, step, quantity):
    """Check one already-reserved canonical claim without changing any document."""
    if action not in ('CLOSE','OPEN') or action == 'OPEN' and step != 0:
        return 'BLOCKED_INTENT_SCOPE'
    try:
        intent_id = canonical_intent_id(account=account, symbol=symbol,
            cycle=cycle, side='SHORT', action=action, step=step)
        qty=Decimal(str(quantity))
        if not qty.is_finite() or qty<=0:
            return 'BLOCKED_QUANTITY'
    except (TypeError,ValueError,InvalidOperation):
        return 'BLOCKED_INTENT_SCOPE'
    @transactional
    def check(tx):
        selector=selector_ref.get(transaction=tx).to_dict()
        position=position_ref.get(transaction=tx).to_dict()
        claim=claim_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        coordination=coordination_ref.get(transaction=tx).to_dict()
        if not isinstance(selector,dict) or (selector.get('account'),selector.get('activeStrategy'),selector.get('offlineOnly'))!=(account,RECOVERY,True):
            return 'BLOCKED_STRATEGY_NOT_ACTIVE'
        if (not isinstance(position,dict) or
            (position.get('account'),position.get('symbol'),position.get('offlineOnly'))!=(account,symbol,True)):
            return 'BLOCKED_POSITION_OWNERSHIP'
        if (not isinstance(control,dict) or control.get('account')!=account or
            control.get('enabled') is not True or control.get('emergencyStop') is not False or
            control.get('closeAllActive') is not False):
            return 'BLOCKED_CONTROL'
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),
            claim.get('cycle'),claim.get('intentId'),claim.get('side'),
            claim.get('action'),claim.get('step'),claim.get('state'))!=(account,symbol,
                cycle,intent_id,'SHORT',action,step,'RESERVED'):
            return 'BLOCKED_CANONICAL_CLAIM'
        fence=coordination.get('recoveryFenceReservation') if isinstance(coordination,dict) else None
        if not isinstance(fence,dict) or (fence.get('account'),fence.get('symbol'),
                fence.get('cycle'),fence.get('intentId'))!=(account,symbol,cycle,intent_id):
            return 'BLOCKED_SHARED_FENCE'
        if action=='CLOSE':
            if fence.get('state')!='RECOVERY_CLAIM_RESERVED':
                return 'BLOCKED_SHARED_FENCE'
            if isinstance(coordination.get('lease'),dict):
                return 'BLOCKED_UNRESOLVED_LEASE'
            if position.get('cycle')!=cycle:
                return 'BLOCKED_POSITION_CYCLE'
        else:
            if fence.get('state')!='REHEDGE_MOCK_SUBMITTING' or fence.get('previousCycle')!=position.get('cycle') or position.get('cycle')==cycle:
                return 'BLOCKED_REHEDGE_CYCLE'
            # The existing rehedge reconciler validates the lease and final
            # exchange readback. This bridge never upgrades that evidence.
            return 'REHEDGE_CLAIM_SCOPE_MATCHED_NOT_AUTHORIZED'
        return 'CLAIM_SCOPE_MATCHED_NOT_AUTHORIZED'
    try:
        return check(db.transaction())
    except Exception:
        return 'BLOCKED_TRANSACTION'
