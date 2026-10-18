"""Offline, exchange-shaped side inventory preflight; no Aster client or POST."""
from decimal import Decimal, InvalidOperation

def check_inventory(*, intents, symbol, readback):
    if not isinstance(readback,dict) or readback.get('symbol')!=symbol or readback.get('verified') is not True:
        return 'BLOCKED_INVENTORY_UNVERIFIED'
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
