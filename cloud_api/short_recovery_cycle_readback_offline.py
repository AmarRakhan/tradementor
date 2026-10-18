"""Read-only offline bridge: only complete mock executions may advance cycle."""
from decimal import Decimal,InvalidOperation
from short_recovery_inventory_preflight import refresh_mock_aster_inventory
from short_recovery_aster_readback_mock_adapter import inspect
from short_recovery_cycle_contract_offline import advance
from short_recovery_multidoc_mock import MultiDocDB

def advance_verified(*,db,transactional,cycle_ref,claim_refs,next_ref,client,next_cycle,event,step=0,control_ref=None):
    if type(db) is not MultiDocDB or getattr(client,'offline_mock_only',False) is not True:
        return 'BLOCKED_OFFLINE_READBACK_SCOPE'
    try:
        tx=db.transaction()
        cycle=cycle_ref.get(transaction=tx).to_dict()
        claims=[ref.get(transaction=tx).to_dict() for ref in claim_refs]
        if not isinstance(cycle,dict) or len(claims)!=5 or any(not isinstance(c,dict) for c in claims):
            return 'BLOCKED_CYCLE_CLAIMS'
        initial=Decimal(str(cycle['initialQty']))
        indices=range(step) if event=='CONFIRM_REDUCTION' else range(5)
        if event=='CONFIRM_REDUCTION' and not 1<=step<=4:return 'BLOCKED_STEP_SEQUENCE'
        if event not in ('CONFIRM_REDUCTION','CONFIRM_REHEDGE'):return 'BLOCKED_EVENT'
        for i in indices:
            claim=claims[i]
            if claim.get('state')!='CLOSED' or not claim.get('intentId') or not claim.get('orderId'):
                return 'BLOCKED_UNVERIFIED_FINAL_CLAIM'
            result=inspect(client,symbol=cycle['symbol'],client_order_id=claim['intentId'])
            if result.get('status')!='READBACK_PREVIEW' or result.get('orderStatus')!='FILLED':
                return 'BLOCKED_UNVERIFIED_EXECUTIONS'
            order=client.query_order(cycle['symbol'],claim['intentId'])
            if str(order.get('orderId'))!=str(claim['orderId']):return 'BLOCKED_ORDER_IDENTITY'
            if 'executedQty' not in order:return 'BLOCKED_MISSING_EXECUTED_QTY'
            qty=Decimal(str(claim['executedQty']))
            order_qty=Decimal(str(order['executedQty']))
            actual=sum((f['quantity'] for f in result['fills']),Decimal(0))
            expected=initial if i==4 else initial/4
            if any(not x.is_finite() for x in (qty,actual,order_qty)) or actual!=qty or qty!=order_qty or qty!=expected:
                return 'BLOCKED_EXECUTION_QUANTITY'
        if event=='CONFIRM_REHEDGE':
            from short_recovery_open_price_provenance_offline import weighted_open_price
            op=claims[4]
            price=weighted_open_price(client,symbol=cycle['symbol'],intent_id=op['intentId'],
                                      order_id=op['orderId'],executed_qty=op['executedQty'])
            if price is None:return 'BLOCKED_NEW_ANCHOR_EXECUTION_PROVENANCE'
            inventory=refresh_mock_aster_inventory(client=client,account=cycle['account'],symbol=cycle['symbol'],now_ms=10000)
            if inventory is None or inventory.get('openOrders')!=[]:
                return 'BLOCKED_REHEDGE_INVENTORY_UNVERIFIED'
            if Decimal(str(inventory['LONG']))!=initial or Decimal(str(inventory['SHORT']))!=initial:
                return 'BLOCKED_REHEDGE_INVENTORY_MISMATCH'
            # Optimistic readback is never an authorization: require unchanged
            # canonical state across the external GETs before transactional write.
            check=db.transaction()
            current=cycle_ref.get(transaction=check).to_dict()
            fresh=[ref.get(transaction=check).to_dict() for ref in claim_refs]
            if current!=cycle or fresh!=claims:return 'BLOCKED_READBACK_TOCTOU'
            return advance(db=db,transactional=transactional,cycle_ref=cycle_ref,
                           claim_refs=claim_refs,next_ref=next_ref,event=event,
                           next_cycle=next_cycle,next_anchor=price,control_ref=control_ref,
                           validated_cycle=cycle,validated_claims=claims)
        return advance(db=db,transactional=transactional,cycle_ref=cycle_ref,claim_refs=claim_refs,
                       next_ref=next_ref,event=event,step=step,next_cycle=next_cycle)
    except (KeyError,TypeError,ValueError,InvalidOperation,AttributeError):
        return 'BLOCKED_UNVERIFIED_EXECUTIONS'
