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
