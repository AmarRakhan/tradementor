"""Derive offline rehedge finality from canonical claim and injected mock exchange GETs."""
from decimal import Decimal,InvalidOperation
from short_recovery_inventory_preflight import refresh_mock_aster_inventory
from short_recovery_aster_readback_mock_adapter import inspect

def verify(*, db,transactional,claim_ref,client,account,symbol,cycle,long_qty,now_ms):
    if getattr(client,'offline_mock_only',False) is not True:return False
    @transactional
    def read(tx):return claim_ref.get(transaction=tx).to_dict()
    try:
        claim=read(db.transaction())
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),claim.get('cycle'),claim.get('side'),claim.get('action'),claim.get('state'))!=(account,symbol,cycle,'SHORT','CLOSE','CLOSED'):
            return False
        cid=claim.get('intentId');oid=claim.get('orderId')
        if not cid or not oid:return False
        result=inspect(client,symbol=symbol,client_order_id=cid)
        if result.get('status')!='READBACK_PREVIEW' or result.get('orderStatus')!='FILLED':return False
        order=client.query_order(symbol,cid)
        if not isinstance(order,dict) or str(order.get('orderId'))!=str(oid) or order.get('status')!='FILLED':return False
        inventory=refresh_mock_aster_inventory(client=client,account=account,symbol=symbol,now_ms=now_ms)
        if inventory is None or inventory['openOrders']!=[]:return False
        long=Decimal(str(inventory['LONG']));short=Decimal(str(inventory['SHORT']))
        required=Decimal(str(long_qty));executed=Decimal(str(order['executedQty']))
        booked=Decimal(str(claim['executedQty']))
        filled=sum((x['quantity'] for x in result['fills']),Decimal(0))
        return (all(x.is_finite() for x in (long,short,required,executed,booked))
                and long>0 and long==required and short==0 and executed>0
                and executed==booked==filled)
    except (TypeError,ValueError,KeyError,InvalidOperation,AttributeError):return False
