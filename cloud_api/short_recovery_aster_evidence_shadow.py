"""Offline-only strict contract for mock Aster exchange readback evidence."""
from decimal import Decimal, InvalidOperation
class EvidenceError(ValueError): pass

def validate(raw, *, kind, account, symbol, intent_id, expected_order_id=None, seen_execution_ids=frozenset()):
    if not isinstance(raw,dict) or raw.get('source')!='ASTER_READBACK_VERIFIED_MOCK' or raw.get('confirmed') is not True:
        raise EvidenceError('unverified mock source')
    if any(raw.get(k)!=v for k,v in (('account',account),('symbol',symbol),('intentId',intent_id))):raise EvidenceError('scope')
    order=raw.get('orderId')
    if not isinstance(order,str) or not order.strip() or (expected_order_id and order!=expected_order_id):raise EvidenceError('order')
    if kind=='ACK':
        if raw.get('status') not in ('NEW','PARTIALLY_FILLED','FILLED'):raise EvidenceError('ack status')
    elif kind=='FILL':
        execution=raw.get('executionId')
        if not isinstance(execution,str) or not execution.strip():raise EvidenceError('execution')
        if execution in seen_execution_ids:return {'status':'ALREADY_APPLIED','orderId':order,'executionId':execution}
        try:quantity=Decimal(str(raw.get('quantity')))
        except (InvalidOperation,TypeError,ValueError) as exc:raise EvidenceError('quantity') from exc
        if not quantity.is_finite() or quantity<=0:raise EvidenceError('quantity')
        return {'status':'VERIFIED_MOCK_FILL','orderId':order,'executionId':execution,'quantity':quantity}
    elif kind in ('CANCEL_TERMINAL','NO_ORDER_TERMINAL'):
        if raw.get('noMoreFills') is not True or raw.get('terminalReadback') is not True:raise EvidenceError('finality')
        if kind=='CANCEL_TERMINAL' and raw.get('status') not in ('CANCELED','EXPIRED','REJECTED'):raise EvidenceError('terminal status')
        if kind=='NO_ORDER_TERMINAL' and raw.get('status')!='PROVEN_NOT_SUBMITTED':raise EvidenceError('no-order status')
    else:raise EvidenceError('kind')
    return {'status':'VERIFIED_MOCK_'+kind,'orderId':order}
