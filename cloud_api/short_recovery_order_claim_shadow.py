"""Offline order-intent reservation; intentionally never sends orders."""
from short_recovery_firestore_mock import decode
import hashlib
import re
from datetime import datetime, timezone

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


def reserve(*,db,transactional,marker_ref,owner_ref,ledger_ref,claim_ref,account,symbol,cycle,intent_id,now,lease_seconds=45,control_ref=None,side=None,action=None,step=None,coordination_ref=None):
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
        coordination=coordination_ref.get(transaction=tx).to_dict() if coordination_ref is not None else None
        if coordination_ref is not None:
            if not isinstance(coordination,dict) or coordination.get('recoveryFenceReservation') is not None:
                return 'BLOCKED_ACCOUNT_FENCE_RESERVED'
            lease=coordination.get('lease')
            if lease is not None:
                if not isinstance(lease,dict) or not lease.get('token'):
                    return 'BLOCKED_ACCOUNT_LEASE_UNVERIFIED'
                until=lease.get('until')
                # Missing, malformed or naive expiry never authorizes a claim.
                if not isinstance(until,datetime) or until.tzinfo is None:
                    return 'BLOCKED_ACCOUNT_LEASE_UNVERIFIED'
                current=datetime.now(timezone.utc)
                if until.astimezone(timezone.utc)>current:
                    return 'BLOCKED_ACCOUNT_COORDINATION_BUSY'
                # An expired lease does not prove no in-flight exchange POST.
                return 'BLOCKED_ACCOUNT_LEASE_STALE_RECONCILE'
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
        if coordination_ref is not None:
            # Same transaction and document as the Auto Hedge fence. A competing
            # hedge reservation must fail its read-set CAS and subsequently see
            # this durable claim marker. Never auto-clear after a timeout.
            tx.set(coordination_ref,{**coordination,'recoveryFenceReservation':{
                'account':account,'symbol':symbol,'cycle':cycle,'intentId':intent_id,
                'state':'RECOVERY_CLAIM_RESERVED','reservedAt':now}})
        return 'RESERVED_SHADOW'
    return attempt(db.transaction())

def pre_submit_check(*, db, transactional, claim_ref, control_ref, account, symbol, cycle, intent_id, account_close_guard, coordination_ref=None):
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
        if coordination_ref is not None:
            coordination=coordination_ref.get(transaction=tx).to_dict()
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),claim.get('cycle'),claim.get('intentId'))!=(account,symbol,cycle,intent_id) or claim.get('state')!='RESERVED':
            return 'BLOCKED_CLAIM_NOT_RESERVED'
        if coordination_ref is not None:
            fence=coordination.get('recoveryFenceReservation') if isinstance(coordination,dict) else None
            if not isinstance(fence,dict) or (fence.get('account'),fence.get('symbol'),fence.get('cycle'),fence.get('intentId')) != (account,symbol,cycle,intent_id):
                return 'BLOCKED_COORDINATION_CLAIM_MISMATCH'
            is_rehedge=(isinstance(claim,dict) and claim.get('side')=='SHORT' and claim.get('action')=='OPEN' and claim.get('step')==0)
            if is_rehedge:
                if (fence.get('state')!='REHEDGE_MOCK_SUBMITTING' or
                        not fence.get('previousCycle') or fence.get('previousCycle')==cycle or
                        not fence.get('leaseToken')):
                    return 'BLOCKED_COORDINATION_CLAIM_MISMATCH'
                lease=coordination.get('lease')
                if not isinstance(lease,dict) or lease.get('token')!=fence.get('leaseToken'):
                    return 'BLOCKED_COORDINATION_LEASE_UNRESOLVED'
                from datetime import datetime,timezone
                expiry=lease.get('until')
                if not isinstance(expiry,datetime) or expiry.tzinfo is None or expiry.astimezone(timezone.utc)<=datetime.now(timezone.utc):
                    return 'BLOCKED_COORDINATION_LEASE_EXPIRED'
            else:
                if fence.get('state')!='RECOVERY_CLAIM_RESERVED':
                    return 'BLOCKED_COORDINATION_CLAIM_MISMATCH'
                if isinstance(coordination.get('lease'),dict) and coordination['lease'].get('token'):
                    return 'BLOCKED_COORDINATION_LEASE_UNRESOLVED'
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

class OfflinePreTransportBlocked(Exception):
    """Mock inventory failed before exchange transport; claim remains locked."""

def record_mock_transport_origin(*,db,transactional,claim_ref,account,symbol,cycle,intent,origin):
    """Persist evidence only; SUBMITTING remains locked and never retryable."""
    @transactional
    def save(tx):
        row=claim_ref.get(transaction=tx).to_dict()
        if not isinstance(row,dict) or row.get('state')!='SUBMITTING' or (
                row.get('account'),row.get('symbol'),row.get('cycle'),row.get('intentId'))!=(account,symbol,cycle,intent.intent_id):
            return 'BLOCKED_ORIGIN_SCOPE'
        tx.set(claim_ref,{**row,'offlineTransportOrigin':origin})
        return 'ORIGIN_PERSISTED'
    return save(db.transaction())

def submit_once_offline(*, db, transactional, claim_ref, control_ref, account, symbol, cycle,
                        intent, account_close_guard, submit_mock, coordination_ref=None, require_shared_fence=False,
                        standalone_selector_ref=None, pre_transport_check=None):
    """Atomic single submit right; only caller-supplied mock transport is permitted.

    A crash after SUBMITTING is UNKNOWN, never an entitlement to retry. This
    function is deliberately not wired into live Auto Hedge or network clients.
    """
    if require_shared_fence is True and coordination_ref is None:
        return 'BLOCKED_SHARED_FENCE_REQUIRED'
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
        if coordination_ref is not None:
            coordination=coordination_ref.get(transaction=tx).to_dict()
        # Recheck strategy INSIDE the same CAS as the canonical order right.
        selector=(standalone_selector_ref.get(transaction=tx).to_dict()
                  if standalone_selector_ref is not None else None)
        if standalone_selector_ref is not None and (
                not isinstance(selector,dict) or selector.get('account')!=account or
                selector.get('activeStrategy')!='AUTO_HEDGE_SHORT_RECOVERY_2' or
                selector.get('offlineOnly') is not True):
            return 'BLOCKED_STRATEGY_NOT_ACTIVE'
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),claim.get('cycle'),claim.get('intentId'))!=(account,symbol,cycle,intent.intent_id) or claim.get('state')!='RESERVED':
            return 'BLOCKED_CLAIM_NOT_RESERVED'
        if coordination_ref is not None:
            fence=coordination.get('recoveryFenceReservation') if isinstance(coordination,dict) else None
            if not isinstance(fence,dict) or (fence.get('account'),fence.get('symbol'),fence.get('cycle'),fence.get('intentId'))!=(account,symbol,cycle,intent.intent_id):
                return 'BLOCKED_COORDINATION_CLAIM_MISMATCH'
            rehedge_open=(getattr(intent.position_side,'value',None)=='SHORT' and intent.action=='OPEN')
            if rehedge_open:
                if (fence.get('state')!='REHEDGE_MOCK_SUBMITTING' or not fence.get('previousCycle') or
                    fence.get('previousCycle')==cycle or not fence.get('leaseToken')):
                    return 'BLOCKED_COORDINATION_CLAIM_MISMATCH'
                lease=coordination.get('lease')
                if not isinstance(lease,dict) or lease.get('token')!=fence['leaseToken']:
                    return 'BLOCKED_COORDINATION_LEASE_UNRESOLVED'
                from datetime import datetime,timezone
                expiry=lease.get('until')
                if not isinstance(expiry,datetime) or expiry.tzinfo is None or expiry.astimezone(timezone.utc)<=datetime.now(timezone.utc):
                    return 'BLOCKED_COORDINATION_LEASE_EXPIRED'
            else:
                if fence.get('state')!='RECOVERY_CLAIM_RESERVED':
                    return 'BLOCKED_COORDINATION_CLAIM_MISMATCH'
                if isinstance(coordination.get('lease'),dict) and coordination['lease'].get('token'):
                    return 'BLOCKED_COORDINATION_LEASE_UNRESOLVED'
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),claim.get('cycle'),claim.get('intentId'))!=(account,symbol,cycle,intent.intent_id) or claim.get('state')!='RESERVED':
            return 'BLOCKED_CLAIM_NOT_RESERVED'
        if claim.get('side') not in ('LONG','SHORT') or claim.get('action') not in ('OPEN','CLOSE') or not isinstance(claim.get('step'),int):
            return 'BLOCKED_CANONICAL_CLAIM'
        if canonical_intent_id(account=account,symbol=symbol,cycle=cycle,side=claim['side'],action=claim['action'],step=claim['step'])!=intent.intent_id:
            return 'BLOCKED_CANONICAL_CLAIM'
        if getattr(intent.position_side,'value',None)!=claim['side'] or intent.action!=claim['action']:
            return 'BLOCKED_SIDE_ACTION'
        if 'minimumCarryQuantity' in claim:
            from decimal import Decimal, InvalidOperation
            try:
                expected=Decimal(str(claim['minimumCarryQuantity']))
                actual=Decimal(str(intent.quantity))
                if (not expected.is_finite() or not actual.is_finite() or
                    expected<=0 or actual!=expected or claim['side']!='SHORT' or
                    claim['action']!='CLOSE' or claim.get('minimumCarryOffline') is not True):
                    return 'BLOCKED_MINIMUM_CARRY_QUANTITY'
            except (InvalidOperation, ValueError, TypeError, AttributeError):
                return 'BLOCKED_MINIMUM_CARRY_QUANTITY'
        if not isinstance(control,dict) or control.get('account')!=account or control.get('enabled') is not True or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
            return 'BLOCKED_RECOVERY_DISABLED_OR_STOPPED'
        tx.set(claim_ref,{**claim,'state':'SUBMITTING'})
        if coordination_ref is not None:
            tx.set(coordination_ref,{**coordination,'recoveryFenceReservation':{
                **fence,'state':'REHEDGE_SUBMITTING_RECONCILE_ONLY' if rehedge_open else 'RECOVERY_SUBMITTING_RECONCILE_ONLY'}})
        return ('SUBMITTING_LOCKED', claim.get('requiresFreshExchangeFilters') is True)
    outcome=acquire(db.transaction())
    if not isinstance(outcome, tuple) or outcome[0]!='SUBMITTING_LOCKED':return outcome
    # Revalidate immediately before offline transport. Any uncertainty leaves
    # SUBMITTING fenced for explicit readback/reconciliation, never retry.
    if pre_transport_check is not None or outcome[1]:
        try:
            if not callable(pre_transport_check) or pre_transport_check(intent) is not True:
                raise OfflinePreTransportBlocked()
        except Exception:
            record_mock_transport_origin(db=db,transactional=transactional,claim_ref=claim_ref,
                account=account,symbol=symbol,cycle=cycle,intent=intent,
                origin='BEFORE_TRANSPORT_BLOCKED')
            return 'BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY'
    # Once the transaction commits, failure/timeout must never unlock the claim.
    try:
        submit_mock(intent)
    except OfflinePreTransportBlocked:
        record_mock_transport_origin(db=db,transactional=transactional,claim_ref=claim_ref,account=account,symbol=symbol,cycle=cycle,intent=intent,origin='BEFORE_TRANSPORT_BLOCKED')
        return 'BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY'
    except Exception:
        record_mock_transport_origin(db=db,transactional=transactional,claim_ref=claim_ref,account=account,symbol=symbol,cycle=cycle,intent=intent,origin='TRANSPORT_OUTCOME_UNKNOWN')
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
        except OfflinePreTransportBlocked:
            ref=long_claim_ref if intent.position_side.value=='LONG' else short_claim_ref
            record_mock_transport_origin(db=db,transactional=transactional,claim_ref=ref,account=account,symbol=symbol,cycle=cycle,intent=intent,origin='BEFORE_TRANSPORT_BLOCKED')
            results.append('BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY')
            break
        except Exception:
            ref=long_claim_ref if intent.position_side.value=='LONG' else short_claim_ref
            record_mock_transport_origin(db=db,transactional=transactional,claim_ref=ref,account=account,symbol=symbol,cycle=cycle,intent=intent,origin='TRANSPORT_OUTCOME_UNKNOWN')
            results.append('UNKNOWN_RECONCILE_ONLY')
            break
        results.append('SUBMITTED_RECONCILE_ONLY')
    return tuple(results)

def classify_locked_mock_claim(*,db,transactional,claim_ref,account,symbol,cycle,intent_id):
    """Offline restart readback classification; never unlocks or resubmits."""
    @transactional
    def read(tx):
        row=claim_ref.get(transaction=tx).to_dict()
        if not isinstance(row,dict) or (row.get('account'),row.get('symbol'),row.get('cycle'),row.get('intentId'))!=(account,symbol,cycle,intent_id):
            return 'BLOCKED_CLAIM_SCOPE'
        if row.get('state')=='ACKED' and row.get('orderId'):
            return 'ACKED_READBACK_ONLY'
        if row.get('state')!='SUBMITTING':
            return 'BLOCKED_NOT_LOCKED'
        kind=row.get('offlineTransportOrigin')
        if kind=='BEFORE_TRANSPORT_BLOCKED':return 'PRETRANSPORT_BLOCKED_NO_RETRY'
        if kind=='TRANSPORT_OUTCOME_UNKNOWN':return 'UNKNOWN_EXCHANGE_READBACK_REQUIRED'
        return 'UNKNOWN_ORIGIN_READBACK_REQUIRED'
    return read(db.transaction())

def reconcile_locked_mock_order_readback(*, db, transactional, claim_ref, account, symbol, cycle, intent_id, client):
    """Offline-only restart readback. Never releases a claim or submits an order."""
    classification=classify_locked_mock_claim(db=db,transactional=transactional,
        claim_ref=claim_ref,account=account,symbol=symbol,cycle=cycle,intent_id=intent_id)
    if classification not in ('PRETRANSPORT_BLOCKED_NO_RETRY','UNKNOWN_EXCHANGE_READBACK_REQUIRED','UNKNOWN_ORIGIN_READBACK_REQUIRED'):
        return classification
    if getattr(client,'offline_mock_only',False) is not True:return 'BLOCKED_MOCK_CLIENT_REQUIRED'
    try:
        order=client.query_order(symbol,intent_id)
    except Exception:return 'UNKNOWN_EXCHANGE_READBACK_REQUIRED'
    if not isinstance(order,dict) or not order:
        return 'NO_ORDER_UNPROVEN_CLAIM_LOCKED'
    if order.get('symbol')!=symbol or order.get('clientOrderId')!=intent_id or not order.get('orderId'):
        return 'BLOCKED_ORDER_IDENTITY'
    from short_recovery_aster_readback_mock_adapter import inspect
    result=inspect(client,symbol=symbol,client_order_id=intent_id)
    if result.get('status')!='READBACK_PREVIEW':return result.get('status','BLOCKED_READBACK')
    @transactional
    def save(tx):
        row=claim_ref.get(transaction=tx).to_dict()
        if (not isinstance(row,dict) or row.get('state')!='SUBMITTING' or
            (row.get('account'),row.get('symbol'),row.get('cycle'),row.get('intentId'))!=(account,symbol,cycle,intent_id)):
            return 'BLOCKED_CLAIM_CHANGED'
        if row.get('orderId') and str(row['orderId'])!=str(order['orderId']):return 'BLOCKED_ORDER_REBIND'
        side=row.get('positionSide') or row.get('side')
        if side not in ('LONG','SHORT') or row.get('side',side)!=side:
            return 'BLOCKED_SIDE_IDENTITY'
        tx.set(claim_ref,{**row,'orderId':str(order['orderId']),
            'positionSide':side,'state':'ACKED','offlineReadbackStatus':result['orderStatus']})
        if result['fills']:
            return ('PARTIAL_FILLS_NEED_FINANCIAL_PROOF' if result['orderStatus']=='PARTIALLY_FILLED'
                    else 'TERMINAL_FILLS_NEED_FINANCIAL_PROOF' if result['orderStatus']=='FILLED'
                    else 'UNRESOLVED_FILLS_NEED_FINANCIAL_PROOF')
        return 'LATE_ACK_READBACK_ONLY'
    return save(db.transaction())
