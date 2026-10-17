"""Offline-only injected Aster readback inspection; no live client creation."""
from decimal import Decimal,InvalidOperation

def inspect(client, *, symbol, client_order_id, page_size=500, max_pages=20):
    if not symbol or not client_order_id or not isinstance(page_size,int) or not 1<=page_size<=1000 or not isinstance(max_pages,int) or max_pages<1:return {'status':'BLOCKED_INPUT'}
    try:
        order=client.query_order(symbol,client_order_id)
        fills=[];cursor=None
        for _ in range(max_pages):
            args={'limit':page_size}
            if cursor is not None:args['from_id']=cursor
            page=client.user_trades(symbol,**args)
            if not isinstance(page,list) or any(not isinstance(x,dict) for x in page):return {'status':'BLOCKED_FILLS_UNPROVEN'}
            if len(page)>page_size:return {'status':'BLOCKED_FILL_PAGE_OVERFLOW'}
            ids=[]
            for row in page:
                try:
                    identity=int(row['id'])
                    if identity<0 or (cursor is not None and identity<cursor):raise ValueError()
                except (KeyError,ValueError,TypeError):
                    if len(page)==page_size or cursor is not None:return {'status':'BLOCKED_FILL_CURSOR'}
                    ids=[];break
                ids.append(identity)
            if ids and len(ids)!=len(set(ids)):return {'status':'BLOCKED_DUPLICATE_EXECUTION','terminalVerified':False,'ordersSent':0}
            if ids and ids!=sorted(ids):return {'status':'BLOCKED_FILL_CURSOR'}
            fills.extend(page)
            if len(page)<page_size:break
            if not ids:return {'status':'BLOCKED_FILL_CURSOR'}
            cursor=ids[-1]+1
        else:return {'status':'BLOCKED_INCOMPLETE_FILL_PAGE','terminalVerified':False,'ordersSent':0}
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
        money={}
        for key,field in (('realizedPnl','realizedPnl'),('commission','fee')):
            if key not in x:return {'status':'BLOCKED_MISSING_FINANCIAL_EVIDENCE'}
            try: amount=Decimal(str(x[key]))
            except (InvalidOperation,ValueError,TypeError):return {'status':'BLOCKED_BAD_FILL'}
            if not amount.is_finite() or (field=='fee' and amount<0):return {'status':'BLOCKED_BAD_FILL'}
            money[field]=amount
        # Aster fill rows alone do not establish order/cycle funding.
        if 'funding' in x:
            try: money['funding']=Decimal(str(x['funding']))
            except (InvalidOperation,ValueError,TypeError):return {'status':'BLOCKED_BAD_FILL'}
            if not money['funding'].is_finite():return {'status':'BLOCKED_BAD_FILL'}
        else: money['funding']=None
        if execution in seen:return {'status':'BLOCKED_DUPLICATE_EXECUTION','terminalVerified':False,'ordersSent':0}
        seen.add(execution);output.append({'executionId':execution,'quantity':q,'orderId':str(order['orderId']),**money})
    try:executed=Decimal(str(order['executedQty'])) if 'executedQty' in order else None
    except (InvalidOperation,ValueError,TypeError):return {'status':'BLOCKED_EXECUTED_QUANTITY'}
    if executed is not None and (not executed.is_finite() or executed<0 or sum((r['quantity'] for r in output),Decimal(0))!=executed):return {'status':'BLOCKED_EXECUTION_INCOMPLETE'}
    if order.get('status') not in ('FILLED','CANCELED','EXPIRED','REJECTED','PARTIALLY_FILLED','NEW'):return {'status':'BLOCKED_ORDER_STATUS','terminalVerified':False,'ordersSent':0}
    return {'status':'READBACK_PREVIEW','orderStatus':order.get('status'),'fills':output,
            'terminalVerified':False,'ordersSent':0}
