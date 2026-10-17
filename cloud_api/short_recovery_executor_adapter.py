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
