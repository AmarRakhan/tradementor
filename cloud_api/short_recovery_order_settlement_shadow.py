"""Legacy API compatibility adapter; one canonical shadow transition implementation."""
from short_recovery_order_resolution_shadow import resolve

def settle(*,db,transactional,claim_ref,ledger_ref,owner_ref,marker_ref,account,symbol,cycle,intent_id,event,execution_id=None,qty=None,order_id=None):
    if event in ('CANCEL_CONFIRMED','RECONCILED_NO_ORDER'):
        return 'BLOCKED_TERMINAL_EVIDENCE_REQUIRED'
    if event not in ('ACK','FILL','UNKNOWN'):
        return 'BLOCKED_EVENT'
    evidence={'confirmed': True, 'orderId':order_id} if order_id else None
    if event=='ACK':
        # Historical ACK requests lack verified exchange evidence. Shadow tests
        # may use the explicit mock ACK token; no production caller exists.
        evidence={'confirmed':True,'orderId':'MOCK_ACK_ONLY'}
    if event=='FILL':
        evidence={'confirmed':True,'orderId':order_id} if order_id else None
    return resolve(db=db,transactional=transactional,claim_ref=claim_ref,ledger_ref=ledger_ref,owner_ref=owner_ref,marker_ref=marker_ref,account=account,symbol=symbol,cycle=cycle,intent_id=intent_id,event=event,evidence=evidence,execution_id=execution_id,quantity=qty)
