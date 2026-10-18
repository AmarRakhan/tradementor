"""Offline-only transactional cycle ledger; not wired to live Auto Hedge."""
from decimal import Decimal, InvalidOperation
from short_recovery_multidoc_mock import MultiDocDB

def advance(*, db, transactional, cycle_ref, claim_refs, next_ref=None, event, step=0, next_cycle=None, next_anchor=None, control_ref=None, validated_cycle=None, validated_claims=None):
    if type(db) is not MultiDocDB or event not in ('CONFIRM_REDUCTION','CONFIRM_REHEDGE'):
        return 'BLOCKED_OFFLINE_CYCLE_SCOPE'
    @transactional
    def apply(tx):
        cycle=cycle_ref.get(transaction=tx).to_dict()
        claims=[ref.get(transaction=tx).to_dict() for ref in claim_refs]
        nxt=next_ref.get(transaction=tx).to_dict() if next_ref is not None else None
        control=control_ref.get(transaction=tx).to_dict() if control_ref is not None else None
        if validated_cycle is not None and (cycle!=validated_cycle or claims!=validated_claims):return 'BLOCKED_READBACK_TOCTOU'
        if validated_cycle is not None and (not isinstance(control,dict) or control.get('account')!=cycle.get('account') or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False or control.get('enabled') is not True):return 'BLOCKED_CYCLE_EMERGENCY_STOP'
        if not isinstance(cycle,dict) or len(claims)!=5 or any(not isinstance(c,dict) for c in claims):return 'BLOCKED_CYCLE_CLAIMS'
        try:
            anchor=Decimal(str(cycle['anchor']));initial=Decimal(str(cycle['initialQty']))
            complete=int(cycle['confirmedSteps'])
        except (KeyError,ValueError,TypeError,InvalidOperation):return 'BLOCKED_CYCLE_STATE'
        if not anchor.is_finite() or anchor<=0 or not initial.is_finite() or initial<=0 or not 0<=complete<=4:return 'BLOCKED_CYCLE_STATE'
        if any((c.get('account'),c.get('symbol'),c.get('cycle'))!=(cycle.get('account'),cycle.get('symbol'),cycle.get('cycleId')) for c in claims):return 'BLOCKED_CLAIM_CYCLE_MISMATCH'
        if any(c.get('state')!='CLOSED' for c in claims[:complete]):return 'BLOCKED_UNCONFIRMED_REDUCTION'
        if event=='CONFIRM_REDUCTION':
            if step!=complete+1 or step>4:return 'BLOCKED_STEP_SEQUENCE'
            claim=claims[step-1]
            if claim.get('side')!='SHORT' or claim.get('action')!='CLOSE' or claim.get('step')!=step or claim.get('state')!='CLOSED' or not claim.get('orderId') or not claim.get('intentId'):
                return 'BLOCKED_UNCONFIRMED_REDUCTION'
            try:qty=Decimal(str(claim['executedQty']))
            except (KeyError,InvalidOperation,ValueError,TypeError):return 'BLOCKED_REDUCTION_QUANTITY'
            if not qty.is_finite() or qty!=initial/4:return 'BLOCKED_REDUCTION_QUANTITY'
            tx.set(cycle_ref,{**cycle,'confirmedSteps':step})
            return 'REDUCTION_CONFIRMED'
        if complete!=4 or next_ref is None or nxt is not None or not next_cycle or next_cycle==cycle['cycleId']:
            return 'BLOCKED_REHEDGE_NOT_FINAL'
        op=claims[4]
        if op.get('side')!='SHORT' or op.get('action')!='OPEN' or op.get('state')!='CLOSED' or not op.get('intentId') or not op.get('orderId'):
            return 'BLOCKED_REHEDGE_NOT_FINAL'
        try:qty=Decimal(str(op['executedQty']));new_anchor=Decimal(str(next_anchor))
        except (InvalidOperation,ValueError,TypeError,KeyError):return 'BLOCKED_NEW_ANCHOR'
        if not qty.is_finite() or qty!=initial or not new_anchor.is_finite() or new_anchor<=0:return 'BLOCKED_NEW_ANCHOR'
        tx.set(cycle_ref,{**cycle,'state':'REHEDGED','nextCycleId':next_cycle})
        tx.set(next_ref,{'account':cycle['account'],'symbol':cycle['symbol'],'cycleId':next_cycle,'anchor':str(new_anchor),'initialQty':str(qty),'confirmedSteps':0,'state':'ACTIVE'})
        return 'NEW_CYCLE_ATOMICALLY_CREATED'
    return apply(db.transaction())
