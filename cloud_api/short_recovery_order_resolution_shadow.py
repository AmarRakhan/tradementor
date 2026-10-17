"""Offline confirmed order-resolution seam. Evidence is supplied by a mock, not exchange."""
from decimal import Decimal
from short_recovery_firestore_mock import decode, encode
from short_recovery_ledger import Fill

def resolve(*, db, transactional, claim_ref, ledger_ref, marker_ref, owner_ref, account, symbol, cycle, intent_id, event, evidence=None, execution_id=None, quantity=None):
    allowed={'UNKNOWN','LATE_ACK','LATE_FILL','CANCEL_REQUESTED','CANCEL_TERMINAL','NO_ORDER_TERMINAL','ACK','FILL'}
    if event not in allowed:return 'BLOCKED_EVENT'
    @transactional
    def step(tx):
        claim=claim_ref.get(transaction=tx).to_dict()
        marker=marker_ref.get(transaction=tx).to_dict()
        owner=owner_ref.get(transaction=tx).to_dict()
        raw=ledger_ref.get(transaction=tx).to_dict()
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),claim.get('cycle'),claim.get('intentId'))!=(account,symbol,cycle,intent_id):return 'BLOCKED_CLAIM'
        if not isinstance(marker,dict) or (marker.get('account'),marker.get('symbol'),marker.get('cycleId'),marker.get('state'))!=(account,symbol,cycle,'SUSPECT'):return 'BLOCKED_MARKER'
        if not isinstance(owner,dict) or (owner.get('account'),owner.get('symbol'),owner.get('cycleId'),owner.get('ownershipVerified'))!=(account,symbol,cycle,True):return 'BLOCKED_OWNER'
        if not isinstance(raw,dict) or (raw.get('account'),raw.get('symbol'))!=(account,symbol):return 'BLOCKED_LEDGER'
        state=claim.get('state','RESERVED'); ledger=decode(raw)
        if event=='UNKNOWN':
            if state in ('CANCELLED','NO_ORDER','CLOSED'):return 'ALREADY_TERMINAL'
            tx.set(claim_ref,{**claim,'state':'UNKNOWN'});return 'BLOCKED_UNKNOWN'
        if event=='CANCEL_REQUESTED':
            if state in ('CANCELLED','NO_ORDER','CLOSED'):return 'ALREADY_TERMINAL'
            tx.set(claim_ref,{**claim,'state':'CANCEL_PENDING'});return 'WAIT_TERMINAL'
        if event=='ACK':
            if state in ('UNKNOWN','CANCEL_PENDING','CANCELLED','NO_ORDER','CLOSED'):return 'BLOCKED_UNKNOWN'
            if not isinstance(evidence,dict) or evidence.get('confirmed') is not True or not evidence.get('orderId'):return 'BLOCKED_NO_EVIDENCE'
            tx.set(claim_ref,{**claim,'state':'ACKED','orderId':evidence['orderId']});return 'ACKED'
        if event=='LATE_ACK':
            if not isinstance(evidence,dict) or evidence.get('confirmed') is not True or not evidence.get('orderId'):return 'BLOCKED_NO_EVIDENCE'
            if state in ('CANCELLED','NO_ORDER','CLOSED'):return 'BLOCKED_TERMINAL_CONFLICT'
            tx.set(claim_ref,{**claim,'state':'ACKED','orderId':evidence['orderId']});return 'ACKED_RECOVERED'
        if event=='FILL' and state in ('CLOSED','CANCELLED','NO_ORDER'):return 'ALREADY_TERMINAL'
        if event=='FILL' and state not in ('ACKED','PARTIAL'):return 'BLOCKED_UNCONFIRMED'
        if event in ('LATE_FILL','FILL'):
            if not isinstance(evidence,dict) or evidence.get('confirmed') is not True or not evidence.get('orderId') or not execution_id or quantity is None:return 'BLOCKED_NO_EVIDENCE'
            if state in ('CANCELLED','NO_ORDER','CLOSED'):return 'BLOCKED_TERMINAL_CONFLICT'
            if claim.get('orderId') and claim['orderId']!=evidence['orderId']:return 'BLOCKED_ORDER_MISMATCH'
            if execution_id in ledger.seen:return 'ALREADY_APPLIED'
            q=Decimal(str(quantity));allocation=ledger.allocations[0]
            if not q.is_finite() or q<=0 or q>allocation.remaining or allocation.cycle_id!=cycle:return 'BLOCKED_QUANTITY'
            updated=ledger.apply(Fill(account,symbol,execution_id,evidence['orderId'],q,Decimal(0),Decimal(0)),((allocation.zone_id,cycle,q),))
            tx.set(ledger_ref,encode(updated))
            tx.set(claim_ref,{**claim,'state':'CLOSED' if updated.allocations[0].remaining==0 else 'PARTIAL','orderId':evidence['orderId']})
            return 'FILL_APPLIED'
        if event in ('CANCEL_TERMINAL','NO_ORDER_TERMINAL'):
            if not isinstance(evidence,dict) or evidence.get('confirmed') is not True or evidence.get('noMoreFills') is not True or evidence.get('intentId')!=intent_id:
                return 'BLOCKED_NOT_TERMINAL'
            if state in ('CANCELLED','NO_ORDER','CLOSED'):return 'ALREADY_TERMINAL'
            if event=='NO_ORDER_TERMINAL' and (state not in ('RESERVED','UNKNOWN') or ledger.seen):return 'BLOCKED_NO_ORDER_CONFLICT'
            tx.set(claim_ref,{**claim,'state':'CANCELLED' if event=='CANCEL_TERMINAL' else 'NO_ORDER'})
            return 'TERMINAL_VERIFIED'
    return step(db.transaction())
