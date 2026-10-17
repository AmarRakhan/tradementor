"""Mock-only adapter: construct safe SHORT reduction proposals, never submit orders."""
from decimal import Decimal
from short_recovery_mock import mock_scan

def preview_mock_executor(cycle, mark, settings, *, exchange_short, long_qty, net_tp=False, claims_busy=False):
    if claims_busy: return {"status":"BLOCKED_CLAIM_BUSY","ordersSent":0}
    status, qty = mock_scan(cycle,mark,settings,exchange_short=exchange_short,long_qty=long_qty,net_tp=net_tp)
    if status=="MOCK_REDUCE":
        return {"status":"MOCK_REDUCE_ONLY","side":"SHORT","action":"CLOSE",
                "quantity":str(qty),"requiresFill":True,"requiresClaim":True,"ordersSent":0}
    if status=="REHEDGE_PREVIEW":
        return {"status":"MOCK_REHEDGE_AFTER_FINAL","side":"SHORT","action":"OPEN",
                "quantity":str(qty),"requiresFill":True,"requiresClaim":True,"ordersSent":0}
    return {"status":status,"ordersSent":0}

def preview_canonical_executor(*, reconciled, symbol, long_qty, short_qty, net_evidence_verified=False,
                               ownership_verified=False, claim_reserved=False, stop_clear=False):
    """Map canonical bridge decisions to guarded Aster intent shapes, WITHOUT submitting.

    This function is only a staging contract, not an authorization or runtime.
    The actual executor must independently revalidate inventory, risk, claims,
    order readback, costs and account stop immediately before POST.
    """
    from short_recovery_mock import d
    from aster_gateway import AsterOrderIntent, PositionSide
    def blocked(reason):return {'status':reason,'ordersSent':0,'intents':()}
    if not all((ownership_verified,claim_reserved,stop_clear)):
        return blocked('BLOCKED_GATES')
    pair=reconciled.get('recovery_previews',{}).get(symbol)
    if not isinstance(pair,dict):return blocked('BLOCKED_NO_CANONICAL_PAIR')
    if symbol not in reconciled.get('skip_symbols',set()):return blocked('BLOCKED_LEGACY_RECONCILER')
    try:long=d(long_qty);short=d(short_qty)
    except (TypeError,ValueError):return blocked('BLOCKED_QUANTITY')
    if long<=0 or short<0:return blocked('BLOCKED_QUANTITY')
    status=pair.get('status')
    if status=='EXIT_PAIR_PRIORITY':
        if not net_evidence_verified:return blocked('BLOCKED_NET_EVIDENCE')
        if short<=0:return blocked('BLOCKED_NO_SHORT_PAIR')
        intents=(AsterOrderIntent('shadow-pair-long',symbol,PositionSide.LONG,long,'CLOSE'),
                 AsterOrderIntent('shadow-pair-short',symbol,PositionSide.SHORT,short,'CLOSE'))
        return {'status':'PREVIEW_PAIR_CLOSE_REQUIRES_ATOMIC_CLAIMS','ordersSent':0,'intents':intents}
    if status!='SHADOW_ONLY':return blocked('BLOCKED_STATE')
    reduction=pair.get('reduction',{})
    if reduction.get('status')=='PREVIEW_REDUCE_ONLY':
        qty=d(reduction['due_qty'])
        if qty<=0 or qty>short:return blocked('BLOCKED_EXCHANGE_QUANTITY')
        return {'status':'PREVIEW_SHORT_REDUCE','ordersSent':0,
                'intents':(AsterOrderIntent('shadow-short-reduce',symbol,PositionSide.SHORT,qty,'CLOSE'),)}
    if pair.get('rehedge')=='PREVIEW_REHEDGE_1_TO_1':
        if short!=0:return blocked('BLOCKED_SHORT_NOT_ZERO')
        return {'status':'PREVIEW_REHEDGE_REQUIRES_FINAL_READBACK','ordersSent':0,
                'intents':(AsterOrderIntent('shadow-rehedge',symbol,PositionSide.SHORT,long,'OPEN'),)}
    return blocked('HOLD_OR_PENDING')
