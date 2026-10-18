"""Offline, exchange-shaped side inventory preflight; no Aster client or POST."""
from decimal import Decimal, InvalidOperation

def check_inventory(*, intents, symbol, readback, account=None, now_ms=None):
    if not isinstance(readback,dict) or readback.get('symbol')!=symbol or readback.get('verified') is not True:
        return 'BLOCKED_INVENTORY_UNVERIFIED'
    if account is not None:
        if (readback is None or readback.get('account')!=account or readback.get('hedgeMode') is not True
                or readback.get('openOrders') != [] or type(now_ms) is not int
                or type(readback.get('timestampMs')) is not int
                or not 0 <= now_ms-readback['timestampMs'] <= 5000):
            return 'BLOCKED_INVENTORY_STALE_OR_SCOPE'
    try:
        long=Decimal(str(readback['LONG']));short=Decimal(str(readback['SHORT']))
        if any(not q.is_finite() or q<0 for q in (long,short)):
            return 'BLOCKED_INVENTORY_INVALID'
        for intent in intents:
            if intent.symbol!=symbol:return 'BLOCKED_INVENTORY_SCOPE'
            qty=Decimal(str(intent.quantity))
            if not qty.is_finite() or qty<=0:return 'BLOCKED_INVENTORY_INVALID'
            side=intent.position_side.value
            available={'LONG':long,'SHORT':short}.get(side)
            if available is None:return 'BLOCKED_INVENTORY_SCOPE'
            if intent.action=='CLOSE' and qty>available:return 'BLOCKED_INVENTORY_OVER_CLOSE'
            if intent.action=='OPEN' and (side!='SHORT' or short!=0 or qty!=long):
                return 'BLOCKED_REHEDGE_PARITY'
            if intent.action not in ('CLOSE','OPEN'):return 'BLOCKED_INVENTORY_SCOPE'
    except (TypeError,ValueError,KeyError,InvalidOperation,AttributeError):
        return 'BLOCKED_INVENTORY_INVALID'
    return 'INVENTORY_VERIFIED'

def refresh_mock_aster_inventory(*, client, account, symbol, now_ms):
    """Offline only: obtain a fresh, scoped side inventory from an injected mock client."""
    if getattr(client,'offline_mock_only',False) is not True:
        return None
    try:
        identity=client.account_information()
        rows=client.position_risk(symbol)
        orders=client.open_orders(symbol)
        if (not isinstance(identity,dict) or identity.get('account')!=account
                or identity.get('hedgeMode') is not True or not isinstance(rows,list)
                or not isinstance(orders,list)):
            return None
        result={'LONG':None,'SHORT':None}
        for row in rows:
            if not isinstance(row,dict) or row.get('symbol')!=symbol:
                return None
            side=row.get('positionSide')
            if side not in result or result[side] is not None:
                return None
            result[side]=row.get('positionAmt')
        if None in result.values():return None
        return dict(result,account=account,symbol=symbol,verified=True,hedgeMode=True,
                    openOrders=orders,timestampMs=now_ms)
    except Exception:
        return None
