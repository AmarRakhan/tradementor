"""Conservative mock-only execution-price provenance, NOT funding evidence."""
from decimal import Decimal, InvalidOperation

def weighted_open_price(client, *, symbol, intent_id, order_id, executed_qty, page_size=500):
    if getattr(client,'offline_mock_only',False) is not True:return None
    try:
        order=client.query_order(symbol,intent_id)
        if (not isinstance(order,dict) or order.get('symbol')!=symbol or
            order.get('clientOrderId')!=intent_id or str(order.get('orderId'))!=str(order_id) or
            order.get('status')!='FILLED'):return None
        target=Decimal(str(executed_qty))
        if 'executedQty' not in order or Decimal(str(order['executedQty']))!=target or not target.is_finite() or target<=0:return None
        cursor=None;seen=set();qty=Decimal(0);notional=Decimal(0)
        for _ in range(20):
            kw={'limit':page_size}
            if cursor is not None:kw['from_id']=cursor
            page=client.user_trades(symbol,**kw)
            if not isinstance(page,list) or len(page)>page_size:return None
            ids=[]
            for row in page:
                if not isinstance(row,dict):return None
                eid=int(row['id'])
                if eid<0 or eid in seen or (cursor is not None and eid<cursor) or (ids and eid<=ids[-1]):return None
                seen.add(eid);ids.append(eid)
                if row.get('symbol')==symbol and str(row.get('orderId'))==str(order_id):
                    q=Decimal(str(row['qty']));price=Decimal(str(row['price']))
                    if not q.is_finite() or q<=0 or not price.is_finite() or price<=0:return None
                    qty+=q;notional+=q*price
            if len(page)<page_size:
                if qty!=target:return None
                return notional/qty
            if not ids:return None
            cursor=ids[-1]+1
        return None
    except (KeyError,ValueError,TypeError,InvalidOperation,AttributeError):return None
