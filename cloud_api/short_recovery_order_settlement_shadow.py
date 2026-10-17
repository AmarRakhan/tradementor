"""Order-free mock settlement: all claim/ledger transitions share one transaction."""
from decimal import Decimal
from short_recovery_firestore_mock import decode,encode

def settle(*,db,transactional,claim_ref,ledger_ref,owner_ref,marker_ref,account,symbol,cycle,intent_id,event,execution_id=None,qty=None,order_id=None):
    if event not in {'ACK','FILL','UNKNOWN','CANCEL_CONFIRMED','RECONCILED_NO_ORDER'}:return 'BLOCKED_EVENT'
    @transactional
    def apply(tx):
        marker=marker_ref.get(transaction=tx).to_dict()
        owner=owner_ref.get(transaction=tx).to_dict()
        stock=ledger_ref.get(transaction=tx).to_dict()
        claim=claim_ref.get(transaction=tx).to_dict()
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),claim.get('cycle'),claim.get('intentId'))!=(account,symbol,cycle,intent_id):return 'BLOCKED_CLAIM'
        if not isinstance(marker,dict) or (marker.get('account'),marker.get('symbol'),marker.get('cycleId'),marker.get('state'))!=(account,symbol,cycle,'SUSPECT'):return 'BLOCKED_MARKER'
        if not isinstance(owner,dict) or (owner.get('account'),owner.get('symbol'),owner.get('cycleId'))!=(account,symbol,cycle) or owner.get('ownershipVerified') is not True:return 'BLOCKED_OWNER'
        if not isinstance(stock,dict) or (stock.get('account'),stock.get('symbol'))!=(account,symbol):return 'BLOCKED_LEDGER'
        state=claim.get('state','RESERVED')
        if state in ('CLOSED','CANCELLED','NO_ORDER'):
            return 'ALREADY_TERMINAL'
        if event=='UNKNOWN':
            tx.set(claim_ref,{**claim,'state':'UNKNOWN'});return 'BLOCKED_UNKNOWN'
        if event=='ACK':
            if state=='UNKNOWN':return 'BLOCKED_UNKNOWN'
            tx.set(claim_ref,{**claim,'state':'ACKED'});return 'ACKED'
        if event=='FILL':
            if state not in ('ACKED','PARTIAL') or not execution_id or not order_id or qty is None:return 'BLOCKED_UNCONFIRMED'
            from short_recovery_ledger import Fill
            ledger=decode(stock)
            if execution_id in ledger.seen:return 'ALREADY_APPLIED'
            quantity=Decimal(str(qty));remaining=ledger.allocations[0].remaining
            if quantity<=0 or quantity>remaining:return 'BLOCKED_QTY'
            updated=ledger.apply(Fill(account,symbol,execution_id,order_id,quantity,Decimal(0),Decimal(0)),((ledger.allocations[0].zone_id,cycle,quantity),))
            next_state='CLOSED' if updated.allocations[0].remaining==0 else 'PARTIAL'
            tx.set(ledger_ref,encode(updated));tx.set(claim_ref,{**claim,'state':next_state,'orderId':order_id})
            return 'FILL_APPLIED'
        if event in ('CANCEL_CONFIRMED','RECONCILED_NO_ORDER'):
            # These legacy event types carry no independently validated terminal evidence.
            return 'BLOCKED_TERMINAL_EVIDENCE_REQUIRED'
        return 'BLOCKED'
    return apply(db.transaction())
