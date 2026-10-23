from decimal import Decimal

import profit_sweep_close_scan as scan
from profit_sweep_close_scan import contribution_for, group_close_orders, scan_and_book_closes

NOW = 1_792_800_000_000  # fixed "now" in ms
DAY_START = scan.local_day_start_ms(NOW)


class Snap:
    def __init__(self, data): self._data = dict(data)
    def to_dict(self): return dict(self._data)


class Doc:
    def __init__(self): self.data = {}
    def get(self, transaction=None): return Snap(self.data)
    def set(self, value, merge=False):
        if merge: self.data.update(value)
        else: self.data = dict(value)


class Query:
    def __init__(self, docs, field, value): self.docs, self.field, self.value = docs, field, value
    def limit(self, _n): return self
    def stream(self): return [Snap(d.data) for d in self.docs.values() if d.data.get(self.field) == self.value]


class Coll:
    def __init__(self): self.docs = {}
    def document(self, key): return self.docs.setdefault(key, Doc())
    def where(self, field, op, value):
        assert op == "=="
        return Query(self.docs, field, value)


class UserRef:
    def __init__(self): self.cols = {}
    def collection(self, key): return self.cols.setdefault(key, Coll())
    def state(self): return self.collection("asterProfitSweepState").document("current").data
    def orders(self): return {k: d.data for k, d in self.collection("asterProfitSweepOrders").docs.items()}


def fill(order, pnl, fee, t, symbol="BTCUSDT", fid=None, side="LONG"):
    return {"id": fid or f"{order}-{t}", "orderId": order, "symbol": symbol, "positionSide": side,
            "realizedPnl": str(pnl), "commission": str(-abs(Decimal(str(fee)))), "commissionAsset": "USDT", "time": t,
            "qty": "1", "price": "1"}


class Client:
    def __init__(self, fills):
        self.fills = fills
    def income_history(self, *, income_type, start_time, end_time, limit):
        return [{"symbol": f["symbol"], "income": f["realizedPnl"], "time": f["time"]}
                for f in self.fills if start_time <= f["time"] <= end_time and Decimal(f["realizedPnl"]) != 0]
    def user_trades(self, symbol, *, start_time, end_time, limit):
        return [f for f in self.fills if f["symbol"] == symbol and start_time <= f["time"] <= end_time]


def run(user, client, now=NOW):
    return scan_and_book_closes(user_ref=user, client=client, percent=Decimal("5"), asset="USDT",
                                minimum=Decimal("1"), now_ms=now)


def test_five_percent_of_net_profit_for_each_green_close():
    t = DAY_START + 60_000
    orders = group_close_orders([fill("1", "10", "0.05", t)], until_ms=t + 1)
    assert orders[0].net == Decimal("9.90")              # 10 - close fee - estimated entry fee
    assert contribution_for(orders[0].net, Decimal("5")) == Decimal("0.495")


def test_opening_fills_and_losing_closes_are_not_saved():
    t = DAY_START + 60_000
    user = UserRef()
    client = Client([
        fill("1", "0", "0.05", t),                      # opening fill
        fill("2", "-3", "0.05", t + 1),                 # red close
        fill("3", "0.04", "0.05", t + 2),               # green before fees, red after
        fill("4", "20", "0.10", t + 3),                 # green
    ])
    result = run(user, client)
    assert result["booked"] == 1
    assert Decimal(user.state()["pendingSavings"]) == Decimal("0.99")   # 5% of 19.80
    assert user.orders()["BTCUSDT_2"]["status"] == "SKIPPED_NONPOSITIVE"
    assert "BTCUSDT_1" not in user.orders()


def test_multi_fill_order_is_one_close_and_booked_once_across_scans():
    t = DAY_START + 60_000
    user = UserRef()
    client = Client([fill("9", "6", "0.02", t, fid="a"), fill("9", "4", "0.03", t, fid="b")])
    run(user, client)
    run(user, client, now=NOW + 60_000)
    run(user, client, now=NOW + 120_000)
    assert Decimal(user.state()["pendingSavings"]) == Decimal("0.495")   # 5% of (10 - 0.05 - 0.05)
    assert user.orders()["BTCUSDT_9"]["fillCount"] == 2


def test_close_already_booked_by_old_hook_is_never_counted_twice():
    t = DAY_START + 60_000
    user = UserRef()
    user.collection("asterProfitSweeps").document("old").set({"exchangeOrderId": "5", "bufferBooked": True})
    user.state().update({"pendingSavings": "0.3"})
    run(user, Client([fill("5", "10", "0.05", t), fill("6", "10", "0.05", t + 5)]))
    assert user.orders()["BTCUSDT_5"]["status"] == "BOOKED_BY_LEGACY_HOOK"
    assert Decimal(user.state()["pendingSavings"]) == Decimal("0.3") + Decimal("0.495")


def test_unsettled_fills_wait_for_the_next_scan():
    user = UserRef()
    fresh = NOW - 2_000                                   # younger than the settle window
    client = Client([fill("7", "10", "0.05", fresh)])
    run(user, client)
    assert "BTCUSDT_7" not in user.orders()
    run(user, client, now=NOW + 60_000)
    assert user.orders()["BTCUSDT_7"]["status"] == "BOOKED"


def test_first_scan_backfills_todays_missed_closes_only():
    user = UserRef()
    client = Client([fill("y", "50", "0.05", DAY_START - 3_600_000), fill("t", "13.70", "0.05", DAY_START + 5_000)])
    run(user, client)
    assert "BTCUSDT_y" not in user.orders()
    assert Decimal(user.state()["pendingSavings"]) == Decimal("0.68")    # 5% of 13.60


def test_many_small_closes_add_up_to_a_one_dollar_block():
    user = UserRef()
    fills = [fill(str(i), "2.10", "0.05", DAY_START + 10_000 + i, symbol=sym)
             for i, sym in enumerate(["BTCUSDT", "ETHUSDT", "SOLUSDT", "NEARUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT", "LTCUSDT", "AVAXUSDT"])]
    run(user, Client(fills))
    assert Decimal(user.state()["pendingSavings"]) == Decimal("1.00")    # 10 x 5% of 2.00


def test_profit_pot_reconcile_books_closes_then_drains(monkeypatch):
    import profit_sweep_live as live
    user = UserRef()
    user.collection("executionControls").document("aster").set(
        {"profitSweep": {"enabled": True, "sweepPercent": 5, "transferAsset": "USDT", "minimumTransfer": 1}})
    seen = {}
    monkeypatch.setattr(scan, "_now_ms", lambda: NOW)
    monkeypatch.setattr(live, "drain_profit_savings_buffer",
                        lambda prepared, client, max_blocks: seen.update(pending=user.state().get("pendingSavings")) or {"status": "BUFFERED"})
    result = live.reconcile_profit_savings_buffer(uid="u", user_ref=user,
                                                  client=Client([fill("1", "40.20", "0.10", DAY_START + 5_000)]))
    assert result["closeScan"]["booked"] == 1
    assert Decimal(seen["pending"]) == Decimal("2")                      # 5% of 40.00, ready to move as 2 x $1
