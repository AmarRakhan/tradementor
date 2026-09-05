from aster_history import trade_events_from_fills
def f(symbol,ps,side,id,price,qty,t): return {"symbol":symbol,"positionSide":ps,"side":side,"id":id,"price":str(price),"qty":str(qty),"time":t}
def test_short_sell_increases():
    e=trade_events_from_fills([f("BNBUSDT","SHORT","SELL","s1",600,.1,1000),f("BNBUSDT","SHORT","SELL","s2",602,.1,2000),f("BNBUSDT","SHORT","SELL","s3",604,.1,3000)],symbol="BNBUSDT",position_side="SHORT")
    assert [x["kind"] for x in e]==["entry","dca","dca"] and [x["dcaNumber"] for x in e]==[None,1,2]
def test_long_buy_increases():
    e=trade_events_from_fills([f("BNBUSDT","LONG","BUY","l1",600,.1,1000),f("BNBUSDT","LONG","BUY","l2",598,.1,2000),f("BNBUSDT","LONG","BUY","l3",596,.1,3000)],symbol="BNBUSDT",position_side="LONG")
    assert [x["kind"] for x in e]==["entry","dca","dca"] and [x["dcaNumber"] for x in e]==[None,1,2]
def test_long_short_same_pair_isolated():
    fills=[f("BNBUSDT","LONG","BUY","l1",600,.1,1000),f("BNBUSDT","SHORT","SELL","s1",600,.1,1100),f("BNBUSDT","LONG","BUY","l2",598,.1,2000),f("BNBUSDT","SHORT","SELL","s2",602,.1,2100)]
    l=trade_events_from_fills(fills,symbol="BNBUSDT",position_side="LONG"); sh=trade_events_from_fills(fills,symbol="BNBUSDT",position_side="SHORT")
    assert [x["id"] for x in l]==["l1","l2"] and [x["id"] for x in sh]==["s1","s2"]
def test_manual_exchange_increase_reconstructed_as_dca():
    e=trade_events_from_fills([f("BNBUSDT","SHORT","SELL","bot-entry",600,.1,1000),f("BNBUSDT","SHORT","SELL","bot-dca",602,.1,2000),f("BNBUSDT","SHORT","SELL","manual-add",604,.1,3000)],symbol="BNBUSDT",position_side="SHORT")
    assert [x["kind"] for x in e]==["entry","dca","dca"] and e[-1]["id"]=="manual-add" and e[-1]["dcaNumber"]==2
