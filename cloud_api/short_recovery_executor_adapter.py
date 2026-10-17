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
                               ownership_verified=False, claim_reserved=False, stop_clear=False, intent_ids=None):
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
    if not isinstance(intent_ids,dict):return blocked('BLOCKED_INTENT_IDS')
    def claim_id(side,action):
        key=side+'_'+action
        value=intent_ids.get(key)
        if not isinstance(value,str) or not value or value.startswith('shadow-'):
            return None
        return value
    status=pair.get('status')
    if status=='EXIT_PAIR_PRIORITY':
        if not net_evidence_verified:return blocked('BLOCKED_NET_EVIDENCE')
        if short<=0:return blocked('BLOCKED_NO_SHORT_PAIR')
        if not claim_id('LONG','CLOSE') or not claim_id('SHORT','CLOSE'):return blocked('BLOCKED_INTENT_IDS')
        intents=(AsterOrderIntent(claim_id('LONG','CLOSE'),symbol,PositionSide.LONG,long,'CLOSE'),
                 AsterOrderIntent(claim_id('SHORT','CLOSE'),symbol,PositionSide.SHORT,short,'CLOSE'))
        return {'status':'PREVIEW_PAIR_CLOSE_REQUIRES_ATOMIC_CLAIMS','ordersSent':0,'intents':intents}
    if status!='SHADOW_ONLY':return blocked('BLOCKED_STATE')
    reduction=pair.get('reduction',{})
    if reduction.get('status')=='PREVIEW_REDUCE_ONLY':
        qty=d(reduction['due_qty'])
        if qty<=0 or qty>short:return blocked('BLOCKED_EXCHANGE_QUANTITY')
        if not claim_id('SHORT','CLOSE'):return blocked('BLOCKED_INTENT_IDS')
        return {'status':'PREVIEW_SHORT_REDUCE','ordersSent':0,
                'intents':(AsterOrderIntent(claim_id('SHORT','CLOSE'),symbol,PositionSide.SHORT,qty,'CLOSE'),)}
    if pair.get('rehedge')=='PREVIEW_REHEDGE_1_TO_1':
        if short!=0:return blocked('BLOCKED_SHORT_NOT_ZERO')
        if not claim_id('SHORT','OPEN'):return blocked('BLOCKED_INTENT_IDS')
        return {'status':'PREVIEW_REHEDGE_REQUIRES_FINAL_READBACK','ordersSent':0,
                'intents':(AsterOrderIntent(claim_id('SHORT','OPEN'),symbol,PositionSide.SHORT,long,'OPEN'),)}
    return blocked('HOLD_OR_PENDING')

def verify_pair_exit_settlement(*, long_order, short_order, required_long, required_short):
    """Fail-closed offline pair-exit readback gate; no order placement or state writes.

    Both sides must be individually terminal, fully filled and have independently
    confirmed costs. A partial/unknown side is NEVER a completed pair exit.
    """
    from short_recovery_mock import d
    def blocked(reason):return {'status':reason,'pairClosed':False,'ordersSent':0}
    if not isinstance(long_order,dict) or not isinstance(short_order,dict):return blocked('BLOCKED_MISSING_SIDE')
    try:
        required=(d(required_long),d(required_short))
        actual=(d(long_order['executedQty']),d(short_order['executedQty']))
    except (KeyError,TypeError,ValueError):return blocked('BLOCKED_QUANTITY_EVIDENCE')
    if any(x<=0 for x in required) or any(x<0 for x in actual):return blocked('BLOCKED_QUANTITY_EVIDENCE')
    for side,row,qty,filled in zip(('LONG','SHORT'),(long_order,short_order),required,actual):
        if row.get('positionSide')!=side or row.get('action')!='CLOSE' or not row.get('orderId'):
            return blocked('BLOCKED_SIDE_IDENTITY')
        if row.get('status')!='FILLED' or row.get('terminalVerified') is not True:
            return blocked('BLOCKED_NOT_TERMINAL')
        if filled!=qty:return blocked('BLOCKED_PARTIAL_OR_MISMATCH')
        if not all(row.get(k) is True for k in ('fillsComplete','financialVerified','fundingOwnershipVerified','incomeHistoryComplete')):
            return blocked('BLOCKED_FINANCIAL_EVIDENCE')
    return {'status':'PAIR_EXIT_SETTLED_SHADOW','pairClosed':True,'ordersSent':0}

def pair_exit_recovery_gate(*, long_order, short_order, required_long, required_short,
                            claim_states, funding_proof=False, stop_active=False):
    """Offline readback/claim resolution: hold uncertainty, never authorize a retry.

    A stopped account may still reconcile existing claims, but it cannot issue
    another close order from this helper. Funding proof is independent of fills.
    """
    gate=verify_pair_exit_settlement(long_order=long_order,short_order=short_order,
                                     required_long=required_long,required_short=required_short)
    if not isinstance(claim_states,dict) or set(claim_states)!={'LONG','SHORT'}:
        return {'status':'BLOCKED_CLAIM_PROOF','pairClosed':False,'ordersSent':0,'retryAllowed':False}
    if any(s not in ('CLOSED','UNKNOWN','PARTIAL','CANCEL_PENDING','ACKED') for s in claim_states.values()):
        return {'status':'BLOCKED_CLAIM_STATE','pairClosed':False,'ordersSent':0,'retryAllowed':False}
    if gate['pairClosed'] and not stop_active and funding_proof and all(s=='CLOSED' for s in claim_states.values()):
        return {'status':'PAIR_CLOSED_VERIFIED_SHADOW','pairClosed':True,'ordersSent':0,'retryAllowed':False}
    return {'status':'RECONCILE_ONLY_STOPPED' if stop_active else 'RECONCILE_ONLY_UNCERTAIN',
            'pairClosed':False,'ordersSent':0,'retryAllowed':False}
