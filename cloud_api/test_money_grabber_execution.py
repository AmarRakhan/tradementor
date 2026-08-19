from decimal import Decimal
import pytest

from aster_execution import PairExecutionPlan
from aster_gateway import PositionSide, build_hedge_order_payload
from money_grabber import Intent, ProtectedPair
from money_grabber_execution import execute_pair_close, execute_protection, execute_round_close


class Client:
    def __init__(self): self.intents=[]
    def submit_order_once(self,intent,**kwargs):
        self.intents.append(intent)
        return {"status":"FILLED","executedQty":str(intent.quantity),"orderId":len(self.intents)},False


def plan(symbol="BTCUSDT", quantity="1", notional="100"):
    return PairExecutionPlan(symbol,Decimal(quantity),Decimal(notional),10)


def protected_pair(): return ProtectedPair("a","r","BTCUSDT","LONG","LOCKED",100,100)


def test_protection_is_same_symbol_opposite_side_and_has_no_reduce_only_payload():
    client=Client();pair=ProtectedPair("a","r","BTCUSDT","LONG")
    intent=Intent("mg-protect-1","PAIR_PROTECTION_RISK_REDUCING","a","r","BTCUSDT","SHORT",50)
    execute_protection(client,intent=intent,pair=pair,quantity=Decimal(".5"),
        hedge_mode_confirmed=True,ownership_reconciled=True,orders_known=True,margin_sufficient=True)
    order=client.intents[0]
    payload=build_hedge_order_payload(order,hedge_mode_confirmed=True,risk_approved=True)
    assert payload["symbol"]=="BTCUSDT" and payload["positionSide"]=="SHORT"
    assert payload["side"]=="SELL" and "reduceOnly" not in payload


def test_protection_cannot_be_used_as_wrong_symbol_or_direction_entry():
    client=Client();pair=ProtectedPair("a","r","BTCUSDT","LONG")
    for symbol,side in (("ETHUSDT","SHORT"),("BTCUSDT","LONG")):
        intent=Intent("mg-protect-1","PAIR_PROTECTION_RISK_REDUCING","a","r",symbol,side,50)
        with pytest.raises(ValueError): execute_protection(client,intent=intent,pair=pair,quantity=Decimal(".5"),
            hedge_mode_confirmed=True,ownership_reconciled=True,orders_known=True,margin_sufficient=True)
    assert client.intents==[]


def test_pair_close_sends_close_plus_each_position_side_without_reduce_only():
    client=Client();pair=protected_pair()
    intent=Intent("mg-pair-close","CLOSE_PROTECTED_PAIR","a","r","BTCUSDT",target_notional=200,reduce_only=True)
    execute_pair_close(client,intent=intent,pair=pair,original_plan=plan(),protection_plan=plan(),exchange_reconciled=True)
    payloads=[build_hedge_order_payload(x,hedge_mode_confirmed=True,risk_approved=True) for x in client.intents]
    assert [x["positionSide"] for x in payloads]==["LONG","SHORT"]
    assert [x["side"] for x in payloads]==["SELL","BUY"]
    assert all("reduceOnly" not in x for x in payloads)


def test_round_close_is_blocked_until_orders_cancelled_and_reconciled():
    intent=Intent("mg-round-close","CLOSE_ALL_ROUND","a","r",reduce_only=True)
    with pytest.raises(ValueError): execute_round_close(Client(),intent=intent,plans=[(plan(),PositionSide.LONG)],exchange_reconciled=True,orders_cancelled=False)
