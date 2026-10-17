"""Offline-only injected Aster readback inspection; no live client creation."""
from decimal import Decimal,InvalidOperation

def inspect(client, *, symbol, client_order_id):
    if not symbol or not client_order_id:return {'status':'BLOCKED_INPUT'}
    try:
        order=client.query_order(symbol,client_order_id)
        fills=client.user_trades(symbol,limit=500)
    except Exception:return {'status':'BLOCKED_READBACK_UNAVAILABLE'}
    if not isinstance(order,dict) or not order:return {'status':'BLOCKED_ORDER_UNPROVEN'}
    if order.get('symbol')!=symbol or order.get('clientOrderId')!=client_order_id or not order.get('orderId'):
        return {'status':'BLOCKED_ORDER_MISMATCH'}
    if not isinstance(fills,list) or any(not isinstance(x,dict) for x in fills):return {'status':'BLOCKED_FILLS_UNPROVEN'}
    matched=[x for x in fills if str(x.get('orderId'))==str(order['orderId']) and x.get('symbol')==symbol]
    seen=set();output=[]
    for x in matched:
        execution=str(x.get('id') or '')
        try:q=Decimal(str(x.get('qty')))
        except (InvalidOperation,ValueError,TypeError):return {'status':'BLOCKED_BAD_FILL'}
        if not execution or not q.is_finite() or q<=0:return {'status':'BLOCKED_BAD_FILL'}
        if execution in seen:continue
        seen.add(execution);output.append({'executionId':execution,'quantity':q,'orderId':str(order['orderId'])})
    return {'status':'READBACK_PREVIEW','orderStatus':order.get('status'),'fills':output,
            'terminalVerified':False,'ordersSent':0}
