from aster_history import closed_trade_from_fill, closed_trades_from_fills, realized_events_from_income, merge_realized_events, recent_trade_activity_from_fills, strategy_by_order_id_from_orders, trade_events_from_fills


def test_long_sell_is_confirmed_close_even_at_breakeven():
    row = closed_trade_from_fill({
        "id": 12, "symbol": "btcusdt", "positionSide": "LONG", "side": "SELL",
        "qty": "0.01", "price": "60000", "realizedPnl": "0", "time": 1_700_000_000_000,
    })
    assert row is not None
    assert row["side"] == "LONG"
    assert row["notionalUsd"] == 600
    assert row["exchangeTradeId"] == "12"


def test_opening_fill_is_not_returned():
    assert closed_trade_from_fill({
        "symbol": "BTCUSDT", "positionSide": "LONG", "side": "BUY",
        "qty": "0.01", "price": "60000", "realizedPnl": "0", "time": 1_700_000_000_000,
    }) is None


def test_short_buy_and_realized_fallback_are_sorted_newest_first():
    rows = closed_trades_from_fills([
        {"symbol": "ETHUSDT", "positionSide": "SHORT", "buyer": True, "qty": "1", "price": "3000", "realizedPnl": "4", "time": 1000},
        {"symbol": "SOLUSDT", "qty": "2", "price": "100", "realizedPnl": "-1", "time": 2000},
    ])
    assert [row["symbol"] for row in rows] == ["SOLUSDT", "ETHUSDT"]


def test_realized_ledger_ignores_commission_and_keeps_authoritative_daily_profit():
    rows = realized_events_from_income([
        {"symbol": "EIGENUSDT", "incomeType": "REALIZED_PNL", "income": "0.29", "time": 1_700_000_001_000, "tranId": 2},
        {"symbol": "THETAUSDT", "incomeType": "REALIZED_PNL", "income": "0.10", "time": 1_700_000_000_000, "tranId": 1},
        {"symbol": "EIGENUSDT", "incomeType": "COMMISSION", "income": "-0.01", "time": 1_700_000_002_000},
    ])
    assert [row["symbol"] for row in rows] == ["EIGENUSDT", "THETAUSDT"]
    assert round(sum(row["realizedPnlUsd"] for row in rows), 2) == 0.39


def test_durable_realized_ledger_never_loses_an_older_close_when_live_window_moves():
    older = [{"symbol": "OLDUSDT", "realizedPnlUsd": 1.0, "closedAt": "2026-08-10T10:00:00+00:00", "exchangeTransactionId": "1"}]
    newest = [{"symbol": "NEWUSDT", "realizedPnlUsd": 2.0, "closedAt": "2026-08-10T11:00:00+00:00", "exchangeTransactionId": "2"}]
    merged = merge_realized_events(older, newest, newest)
    assert len(merged) == 2
    assert sum(row["realizedPnlUsd"] for row in merged) == 3.0


def test_trade_events_reconstruct_long_entry_dcas_and_tp():
    fills = [
        {"id": "1", "symbol": "CAPUSDT", "positionSide": "LONG", "side": "BUY", "qty": "10", "price": "1.00", "time": 1000},
        {"id": "2", "symbol": "CAPUSDT", "positionSide": "LONG", "side": "BUY", "qty": "10", "price": ".98", "time": 2000},
        {"id": "3", "symbol": "CAPUSDT", "positionSide": "LONG", "side": "BUY", "qty": "10", "price": ".96", "time": 3000},
        {"id": "4", "symbol": "CAPUSDT", "positionSide": "LONG", "side": "SELL", "qty": "30", "price": "1.01", "time": 4000},
    ]
    events = trade_events_from_fills(fills, symbol="capusdt", position_side="long", closed_at_ms=4000)
    assert [event["kind"] for event in events] == ["entry", "dca", "dca", "close"]


def test_trade_events_mirror_short_and_keep_only_active_cycle():
    fills = [
        {"id": "old-open", "symbol": "BTCUSDT", "positionSide": "SHORT", "side": "SELL", "qty": "1", "price": "100", "time": 1000},
        {"id": "old-close", "symbol": "BTCUSDT", "positionSide": "SHORT", "side": "BUY", "qty": "1", "price": "90", "time": 2000},
        {"id": "new-open", "symbol": "BTCUSDT", "positionSide": "SHORT", "side": "SELL", "qty": "2", "price": "95", "time": 3000},
        {"id": "new-dca", "symbol": "BTCUSDT", "positionSide": "SHORT", "side": "SELL", "qty": "1", "price": "97", "time": 4000},
    ]
    events = trade_events_from_fills(fills, symbol="BTCUSDT", position_side="SHORT")
    assert [event["id"] for event in events] == ["new-open", "new-dca"]
    assert [event["kind"] for event in events] == ["entry", "dca"]


def test_recent_activity_combines_partial_fills_and_mirrors_hedge_sides():
    fills = [
        {"id": "t1", "orderId": "o1", "symbol": "BTCUSDT", "positionSide": "LONG", "side": "BUY", "qty": ".1", "price": "100", "time": 1000},
        {"id": "t2", "orderId": "o1", "symbol": "BTCUSDT", "positionSide": "LONG", "side": "BUY", "qty": ".1", "price": "102", "time": 1001},
        {"id": "t3", "orderId": "o2", "symbol": "ETHUSDT", "positionSide": "SHORT", "side": "SELL", "qty": "1", "price": "50", "time": 2000},
        {"id": "t4", "orderId": "o3", "symbol": "ETHUSDT", "positionSide": "SHORT", "side": "BUY", "qty": "1", "price": "45", "realizedPnl": "5", "time": 3000},
    ]
    activity = recent_trade_activity_from_fills(fills, active_positions=[
        {"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": ".2", "unRealizedProfit": "2"},
    ], strategy_by_intent={})
    assert len(activity["entries"]) == 2
    assert round(activity["entries"][1]["executedNotionalUsd"], 8) == 20.2
    assert activity["entries"][1]["unrealizedPnlUsd"] == 2
    assert activity["exits"][0]["side"] == "SHORT"
    assert activity["exits"][0]["realizedPnlUsd"] == 5
    assert activity["exits"][0]["strategy"] == "Niet aan strategie gekoppeld"


def test_recent_activity_attributes_strategy_from_aster_client_order_id():
    fills = [
        {"id": "t1", "orderId": "o1", "clientOrderId": "s2i-user-1", "symbol": "SOLUSDT", "positionSide": "LONG", "side": "BUY", "qty": "1", "price": "10", "time": 1000},
        {"id": "t2", "orderId": "o2", "clientOrderId": "s3-user-2", "symbol": "ETHUSDT", "positionSide": "SHORT", "side": "SELL", "qty": "1", "price": "20", "time": 2000},
    ]
    activity = recent_trade_activity_from_fills(fills)
    assert [row["strategy"] for row in activity["entries"]] == ["Strategy 3", "Strategy 2"]


def test_recent_activity_attributes_exchange_order_id_without_client_id():
    fills = [
        {"id":"fill-1","orderId":"exchange-77","symbol":"FILUSDT","positionSide":"SHORT",
         "side":"SELL","qty":"5","price":"2","time":3000},
    ]
    activity = recent_trade_activity_from_fills(
        fills, strategy_by_order_id={"exchange-77":"Dual Harvest Adaptive Shield"},
    )
    assert len(activity["entries"]) == 1
    assert activity["entries"][0]["executedNotionalUsd"] == 10
    assert activity["entries"][0]["strategy"] == "Dual Harvest Adaptive Shield"


def test_recent_activity_exit_inherits_proven_strategy_from_same_position_cycle():
    fills = [
        {"id":"entry-fill","orderId":"entry-order","symbol":"RAVEUSDT","positionSide":"SHORT",
         "side":"SELL","qty":"10","price":"3","time":1_000},
        {"id":"exit-fill","orderId":"exit-order","symbol":"RAVEUSDT","positionSide":"SHORT",
         "side":"BUY","qty":"10","price":"2.9","realizedPnl":"1","time":2_000},
    ]
    activity = recent_trade_activity_from_fills(
        fills, strategy_by_order_id={"entry-order":"Dual Harvest Adaptive Shield"},
    )
    assert activity["entries"][0]["strategy"] == "Dual Harvest Adaptive Shield"
    assert activity["exits"][0]["strategy"] == "Dual Harvest Adaptive Shield"


def test_recent_activity_exit_inherits_strategy3_client_id_from_same_position_cycle():
    fills = [
        {"id":"entry-fill","orderId":"entry-order","clientOrderId":"s3i-user-entry",
         "symbol":"RAVEUSDT","positionSide":"LONG","side":"BUY","qty":"10","price":"3","time":1_000},
        {"id":"exit-fill","orderId":"exit-order","symbol":"RAVEUSDT","positionSide":"LONG",
         "side":"SELL","qty":"10","price":"3.1","realizedPnl":"1","time":2_000},
    ]
    activity = recent_trade_activity_from_fills(fills)
    assert activity["entries"][0]["strategy"] == "Strategy 3"
    assert activity["exits"][0]["strategy"] == "Strategy 3"


def test_recent_activity_joins_fill_to_exact_aster_order_history_identity():
    fills = [
        {"id":"fill-1","orderId":"entry-order","symbol":"LDOUSDT","positionSide":"LONG",
         "side":"BUY","qty":"10","price":"1","time":1_000},
        {"id":"fill-2","orderId":"close-order","symbol":"LDOUSDT","positionSide":"LONG",
         "side":"SELL","qty":"10","price":"1.1","realizedPnl":"1","time":2_000},
    ]
    order_map = strategy_by_order_id_from_orders([
        {"orderId":"entry-order","clientOrderId":"s3-a1-open-long"},
        {"orderId":"close-order","clientOrderId":"s3-a1-close-long"},
        {"orderId":"unrelated","clientOrderId":"manual-order"},
    ])
    activity = recent_trade_activity_from_fills(fills, strategy_by_order_id=order_map)
    assert activity["entries"][0]["strategy"] == "Strategy 3"
    assert activity["exits"][0]["strategy"] == "Strategy 3"
    assert "unrelated" not in order_map


def test_recent_activity_does_not_inherit_across_closed_position_cycles():
    fills = [
        {"id":"old-entry","orderId":"old-order","symbol":"LINKUSDT","positionSide":"LONG",
         "side":"BUY","qty":"2","price":"10","time":1_000},
        {"id":"old-exit","orderId":"old-exit-order","symbol":"LINKUSDT","positionSide":"LONG",
         "side":"SELL","qty":"2","price":"11","time":2_000},
        {"id":"manual-entry","orderId":"manual-order","symbol":"LINKUSDT","positionSide":"LONG",
         "side":"BUY","qty":"1","price":"12","time":3_000},
        {"id":"manual-exit","orderId":"manual-exit-order","symbol":"LINKUSDT","positionSide":"LONG",
         "side":"SELL","qty":"1","price":"13","time":4_000},
    ]
    activity = recent_trade_activity_from_fills(
        fills, strategy_by_order_id={"old-order":"Dual Harvest Adaptive Shield"},
    )
    newest_exit, old_exit = activity["exits"]
    assert newest_exit["strategy"] == "Niet aan strategie gekoppeld"
    assert old_exit["strategy"] == "Dual Harvest Adaptive Shield"


def test_recent_activity_is_newest_first_even_when_aster_returns_shuffled_fills():
    fills = [
        {"id":"entry-middle","orderId":"2","symbol":"ETHUSDT","positionSide":"LONG","side":"BUY","qty":"1","price":"20","time":2_000},
        {"id":"exit-old","orderId":"3","symbol":"BTCUSDT","positionSide":"LONG","side":"SELL","qty":"1","price":"11","time":3_000},
        {"id":"entry-new","orderId":"4","symbol":"SOLUSDT","positionSide":"SHORT","side":"SELL","qty":"1","price":"30","time":4_000},
        {"id":"entry-old","orderId":"1","symbol":"BTCUSDT","positionSide":"LONG","side":"BUY","qty":"1","price":"10","time":1_000},
        {"id":"exit-new","orderId":"5","symbol":"SOLUSDT","positionSide":"SHORT","side":"BUY","qty":"1","price":"29","time":5_000},
    ]
    activity = recent_trade_activity_from_fills(fills)
    assert [row["id"] for row in activity["entries"]] == ["4", "2", "1"]
    assert [row["id"] for row in activity["exits"]] == ["5", "3"]
    assert [row["timestampMs"] for row in activity["entries"]] == [4_000, 2_000, 1_000]
    assert [row["timestampMs"] for row in activity["exits"]] == [5_000, 3_000]


def test_recent_activity_uses_stable_id_tiebreak_and_does_not_truncate_history():
    fills = [
        {"id": f"{index:03d}", "orderId": f"{index:03d}", "symbol": "BTCUSDT", "positionSide": "LONG",
         "side": "BUY", "qty": "1", "price": "10", "time": 1_000}
        for index in range(125)
    ]
    activity = recent_trade_activity_from_fills(fills)
    assert len(activity["entries"]) == 125
    assert activity["entries"][0]["id"] == "124"
    assert activity["entries"][-1]["id"] == "000"


def test_recent_activity_only_exposes_authoritative_exchange_percentage():
    fill = {"id": "1", "orderId": "1", "symbol": "SOLUSDT", "positionSide": "SHORT",
            "side": "SELL", "qty": "2", "price": "20", "time": 1_000}
    without_roe = recent_trade_activity_from_fills([fill], active_positions=[
        {"symbol": "SOLUSDT", "positionSide": "SHORT", "positionAmt": "2", "unRealizedProfit": "4"},
    ])["entries"][0]
    assert "returnPct" not in without_roe
    with_roe = recent_trade_activity_from_fills([fill], active_positions=[
        {"symbol": "SOLUSDT", "positionSide": "SHORT", "positionAmt": "2", "unRealizedProfit": "4", "roe": "0.18"},
    ])["entries"][0]
    assert with_roe["returnPct"] == 18
