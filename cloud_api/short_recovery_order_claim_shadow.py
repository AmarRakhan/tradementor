"""Offline order-intent reservation; intentionally never sends orders."""
from short_recovery_firestore_mock import decode
import hashlib
import re

def canonical_intent_id(*,account,symbol,cycle,side,action,step):
    """Deterministic Aster-safe ID for an independently persisted claim scope.

    The same action+step reuses one ID across retries/restarts; distinct steps
    must never reuse it. Not authorization to submit.
    """
    if (not all(isinstance(x,str) and x for x in (account,symbol,cycle))
            or side not in ("LONG","SHORT") or action not in ("OPEN","CLOSE")
            or isinstance(step,bool) or not isinstance(step,int) or step<0):
        raise ValueError("BLOCKED_INTENT_SCOPE")
    key="\x1f".join((account,symbol,cycle,side,action,str(step)))
    return "sr2-"+hashlib.sha256(key.encode()).hexdigest()[:30]


def reserve(*,db,transactional,marker_ref,owner_ref,ledger_ref,claim_ref,account,symbol,cycle,intent_id,now,lease_seconds=45,control_ref=None,side=None,action=None,step=None):
    if not all((account,symbol,cycle,intent_id)) or lease_seconds<=0:return 'BLOCKED_INPUT'
    if side is not None or action is not None or step is not None:
        try: expected=canonical_intent_id(account=account,symbol=symbol,cycle=cycle,side=side,action=action,step=step)
        except ValueError:return 'BLOCKED_INTENT_SCOPE'
        if intent_id!=expected:return 'BLOCKED_INTENT_ID'
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
                          'state':'RESERVED','reservedAt':now,'leaseUntil':now+lease_seconds,
                          'side':side,'action':action,'step':step})
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

def submit_once_offline(*, db, transactional, claim_ref, control_ref, account, symbol, cycle,
                        intent, account_close_guard, submit_mock):
    """Atomic single submit right; only caller-supplied mock transport is permitted.

    A crash after SUBMITTING is UNKNOWN, never an entitlement to retry. This
    function is deliberately not wired into live Auto Hedge or network clients.
    """
    if not callable(submit_mock) or not callable(account_close_guard) or control_ref is None:
        return 'BLOCKED_GUARD_UNAVAILABLE'
    if not getattr(intent, 'intent_id', None) or intent.symbol != symbol:
        return 'BLOCKED_INTENT_SCOPE'
    try:
        account_close_guard()
    except Exception:
        return 'BLOCKED_ACCOUNT_PRE_SUBMIT_GUARD'
    @transactional
    def acquire(tx):
        claim=claim_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),claim.get('cycle'),claim.get('intentId'))!=(account,symbol,cycle,intent.intent_id) or claim.get('state')!='RESERVED':
            return 'BLOCKED_CLAIM_NOT_RESERVED'
        if claim.get('side') not in ('LONG','SHORT') or claim.get('action') not in ('OPEN','CLOSE') or not isinstance(claim.get('step'),int):
            return 'BLOCKED_CANONICAL_CLAIM'
        if canonical_intent_id(account=account,symbol=symbol,cycle=cycle,side=claim['side'],action=claim['action'],step=claim['step'])!=intent.intent_id:
            return 'BLOCKED_CANONICAL_CLAIM'
        if getattr(intent.position_side,'value',None)!=claim['side'] or intent.action!=claim['action']:
            return 'BLOCKED_SIDE_ACTION'
        if not isinstance(control,dict) or control.get('account')!=account or control.get('enabled') is not True or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
            return 'BLOCKED_RECOVERY_DISABLED_OR_STOPPED'
        tx.set(claim_ref,{**claim,'state':'SUBMITTING'})
        return 'SUBMITTING_LOCKED'
    outcome=acquire(db.transaction())
    if outcome!='SUBMITTING_LOCKED':return outcome
    # Once the transaction commits, failure/timeout must never unlock the claim.
    try:
        submit_mock(intent)
    except Exception:
        return 'UNKNOWN_RECONCILE_ONLY'
    return 'SUBMITTED_RECONCILE_ONLY'

def lock_pair_submit_offline(*, db, transactional, long_claim_ref, short_claim_ref, control_ref,
                             account, symbol, cycle, long_intent, short_intent, account_close_guard):
    """Atomically take both pair-close submit rights, without sending orders.

    Crash after the lock is UNKNOWN for *both* sides; replay cannot reacquire.
    This is not an atomic exchange fill nor proof of net profit.
    """
    if not callable(account_close_guard) or long_claim_ref is None or short_claim_ref is None or long_claim_ref is short_claim_ref:
        return 'BLOCKED_PAIR_CLAIM_SCOPE'
    try:
        account_close_guard()
    except Exception:
        return 'BLOCKED_ACCOUNT_PRE_SUBMIT_GUARD'
    @transactional
    def acquire(tx):
        long_claim=long_claim_ref.get(transaction=tx).to_dict()
        short_claim=short_claim_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if not isinstance(control,dict) or control.get('account')!=account or control.get('enabled') is not True or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
            return 'BLOCKED_RECOVERY_DISABLED_OR_STOPPED'
        for side,claim,intent in [('LONG',long_claim,long_intent),('SHORT',short_claim,short_intent)]:
            if (not isinstance(claim,dict) or claim.get('state')!='RESERVED'
                or (claim.get('account'),claim.get('symbol'),claim.get('cycle'))!=(account,symbol,cycle)
                or claim.get('side')!=side or claim.get('action')!='CLOSE'
                or isinstance(claim.get('step'),bool) or not isinstance(claim.get('step'),int)
                or claim.get('intentId')!=getattr(intent,'intent_id',None)
                or getattr(intent,'symbol',None)!=symbol or getattr(intent,'action',None)!='CLOSE'
                or getattr(getattr(intent,'position_side',None),'value',None)!=side
                or claim.get('intentId')!=canonical_intent_id(account=account,symbol=symbol,cycle=cycle,side=side,action='CLOSE',step=claim['step'])):
                return 'BLOCKED_PAIR_SIDE_CLAIMS'
        tx.set(long_claim_ref,{**long_claim,'state':'SUBMITTING'})
        tx.set(short_claim_ref,{**short_claim,'state':'SUBMITTING'})
        return 'PAIR_SUBMITTING_LOCKED'
    return acquire(db.transaction())

def persist_mock_submit_ack(*,db,transactional,claim_ref,account,symbol,cycle,intent,response):
    """Persist a matching mock Aster ACK once; uncertainty stays SUBMITTING."""
    if not isinstance(response,dict) or str(response.get('clientOrderId',''))!=intent.intent_id or not response.get('orderId'):
        return 'BLOCKED_ACK_MISMATCH'
    @transactional
    def save(tx):
        row=claim_ref.get(transaction=tx).to_dict()
        if not isinstance(row,dict) or (row.get('account'),row.get('symbol'),row.get('cycle'),row.get('intentId'))!=(account,symbol,cycle,intent.intent_id) or row.get('state')!='SUBMITTING':
            return 'BLOCKED_ACK_CLAIM'
        if row.get('orderId') and str(row['orderId'])!=str(response['orderId']):return 'BLOCKED_ACK_ORDER_REBIND'
        tx.set(claim_ref,{**row,'orderId':str(response['orderId']),'positionSide':intent.position_side.value,'state':'ACKED'})
        return 'ACKED_PERSISTED'
    return save(db.transaction())

def submit_locked_pair_mock_offline(*, db, transactional, long_claim_ref, short_claim_ref,
                                    control_ref, account, symbol, cycle, long_intent, short_intent,
                                    account_close_guard, submit_mock):
    """Mock-only two-leg transport after atomic pair lock. Never retries a leg.

    If either POST outcome is uncertain, retains both SUBMITTING claims; only
    authoritative per-side readback may resolve, never a blind second POST.
    """
    if not callable(submit_mock):return ('BLOCKED_MOCK_TRANSPORT',)
    locked=lock_pair_submit_offline(db=db,transactional=transactional,
        long_claim_ref=long_claim_ref,short_claim_ref=short_claim_ref,control_ref=control_ref,
        account=account,symbol=symbol,cycle=cycle,long_intent=long_intent,
        short_intent=short_intent,account_close_guard=account_close_guard)
    if locked!='PAIR_SUBMITTING_LOCKED':return (locked,)
    results=[]
    for intent in (long_intent,short_intent):
        @transactional
        def check_current_stop(tx):
            row=control_ref.get(transaction=tx).to_dict()
            return isinstance(row,dict) and row.get('account')==account and row.get('enabled') is True and row.get('emergencyStop') is False and row.get('closeAllActive') is False
        if not check_current_stop(db.transaction()):
            results.append('BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
            break
        try:
            account_close_guard()
            response=submit_mock(intent)
            ref=long_claim_ref if intent.position_side.value=='LONG' else short_claim_ref
            ack=persist_mock_submit_ack(db=db,transactional=transactional,claim_ref=ref,
                account=account,symbol=symbol,cycle=cycle,intent=intent,response=response)
            if ack!='ACKED_PERSISTED':
                results.append(ack)
                break
        except Exception:
            results.append('UNKNOWN_RECONCILE_ONLY')
            break
        results.append('SUBMITTED_RECONCILE_ONLY')
    return tuple(results)
