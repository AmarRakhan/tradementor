"""HTTP-level fake of the Aster futures REST API for end-to-end tests of Close Profits 2.0.

It plugs into the REAL aster_gateway.AsterV3Client through httpx's `transport` hook, so the real request building,
real response classification (503 -> AsterSubmissionUncertain, 4xx -> AsterApiError, read timeout, ...), real
execute_leg_once and the real close route run unchanged. Nothing here talks to the network or needs credentials.
Scriptable per symbol: ok | partial_fill | ack_new | reject | http503_after_accept | http503_unknown | timeout_after_accept;
latency; position-endpoint reflection lag. Every unmocked path is recorded in `unmocked` (tests assert it stays empty)."""
from __future__ import annotations

import json
import threading
import time
from urllib.parse import parse_qsl

import httpx


class FakeAster:
    def __init__(self):
        self.lock = threading.RLock()
        self.pos, self.entry, self.mark = {}, {}, {}
        self.minq, self.step = {}, {}
        self.modes, self.delay, self.lag = {}, {}, {}
        self._pending = []
        self.orders = []          # accepted orders: {symbol, side, positionSide, qty, cid, t0, t1, executed, status}
        self.rows_by_cid = {}
        self.unmocked = []
        self.requests = []
        self.on_order_start = None   # callable(symbol) run at the start of every order POST (worker/close concurrency hooks)
        self.on_position_read = None
        self._id = 0

    # ---- world -------------------------------------------------------------------------------------------
    def add(self, symbol, side, qty, mark=100.0, entry=None, minimum=0.001, step=0.001):
        self.pos[(symbol, side)] = float(qty)
        self.mark[symbol] = float(mark)
        self.entry[(symbol, side)] = entry if entry is not None else (mark + 5 if side == "SHORT" else mark - 5)
        self.minq[symbol], self.step[symbol] = minimum, step

    def transport(self):
        return httpx.MockTransport(self.handle)

    def accepted(self, side=None, symbol=None):
        return [o for o in self.orders if (side is None or o["positionSide"] == side) and (symbol is None or o["symbol"] == symbol)]

    # ---- http --------------------------------------------------------------------------------------------
    @staticmethod
    def _json(payload, status=200):
        return httpx.Response(status, content=json.dumps(payload).encode(), headers={"content-type": "application/json"})

    def _position_rows(self):
        with self.lock:
            shown = dict(self.pos)
            still = []
            for item in self._pending:
                if item[0] > 0:
                    shown[(item[1], item[2])] = item[3]
                    item[0] -= 1
                    still.append(item)
            self._pending = still
            rows = []
            for (symbol, side), qty in shown.items():
                if qty <= 0:
                    continue
                mark = self.mark[symbol]
                diff = (self.entry[(symbol, side)] - mark) if side == "SHORT" else (mark - self.entry[(symbol, side)])
                rows.append({"symbol": symbol, "positionSide": side, "positionAmt": repr(-qty if side == "SHORT" else qty),
                             "entryPrice": str(self.entry[(symbol, side)]), "markPrice": str(mark), "leverage": "5",
                             "liquidationPrice": "0", "marginType": "cross", "notional": str(qty * mark),
                             "unRealizedProfit": repr(diff * qty), "isolatedMargin": "0", "updateTime": int(time.time() * 1000)})
            return rows

    def _exchange_info(self):
        return {"timezone": "UTC", "serverTime": int(time.time() * 1000), "symbols": [
            {"symbol": s, "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT", "baseAsset": s[:-4],
             "pricePrecision": 4, "quantityPrecision": 3, "filters": [
                {"filterType": "LOT_SIZE", "minQty": str(self.minq[s]), "maxQty": "1000000", "stepSize": str(self.step[s])},
                {"filterType": "MARKET_LOT_SIZE", "minQty": str(self.minq[s]), "maxQty": "1000000", "stepSize": str(self.step[s])},
                {"filterType": "PRICE_FILTER", "minPrice": "0.0001", "maxPrice": "1000000", "tickSize": "0.0001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"}]} for s in sorted(self.mark)]}

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        with self.lock:
            self.requests.append((request.method, path))
        if request.method == "GET":
            params = dict(parse_qsl(request.url.query.decode() if isinstance(request.url.query, bytes) else str(request.url.query)))
        else:
            params = dict(parse_qsl(request.content.decode()))
        if path == "/fapi/v3/positionRisk":
            if self.on_position_read:
                self.on_position_read()
            rows = self._position_rows()
            if params.get("symbol"):
                rows = [r for r in rows if r["symbol"] == params["symbol"]]
            return self._json(rows)
        if path == "/fapi/v3/exchangeInfo":
            return self._json(self._exchange_info())
        if path == "/fapi/v3/positionSide/dual":
            return self._json({"dualSidePosition": True})
        if path == "/fapi/v3/openOrders":
            return self._json([])
        if path == "/fapi/v3/ticker/price":
            return self._json([{"symbol": s, "price": str(p)} for s, p in self.mark.items()])
        if path == "/fapi/v3/order" and request.method == "GET":
            row = self.rows_by_cid.get(params.get("origClientOrderId", ""))
            if not row:
                return self._json({"code": -2013, "msg": "Order does not exist."}, 400)
            return self._json({"orderId": row["id"], "clientOrderId": row["cid"], "symbol": row["symbol"],
                               "status": row["status"], "executedQty": str(row["executed"]), "origQty": str(row["qty"])})
        if path == "/fapi/v3/order" and request.method == "POST":
            return self._order(request, params)
        with self.lock:
            self.unmocked.append((request.method, path))
        return self._json({"code": -1, "msg": f"unmocked {path}"}, 404)

    def _order(self, request, params):
        symbol, side, ps = params["symbol"], params["side"], params["positionSide"]
        qty, cid = float(params["quantity"]), params["newClientOrderId"]
        if self.on_order_start:
            self.on_order_start(symbol)
        delay = self.delay.get(symbol, 0.0)
        t0 = time.monotonic()
        if delay:
            time.sleep(delay)
        mode = self.modes.get(symbol, "ok")
        with self.lock:
            if mode == "reject":
                return self._json({"code": -2019, "msg": "Margin is insufficient."}, 400)
            if mode == "http503_unknown":
                return self._json({"code": -1007, "msg": "Timeout waiting for response from backend server."}, 503)
            if cid in self.rows_by_cid:
                return self._json({"code": -4015, "msg": "Client order id is not valid."}, 400)
            self._id += 1
            reducing = (side == "BUY" and ps == "SHORT") or (side == "SELL" and ps == "LONG")
            executed, status = qty, "FILLED"
            if mode == "partial_fill":
                executed, status = qty * 0.4, "PARTIALLY_FILLED"
            if mode == "ack_new":
                executed, status = 0.0, "NEW"
            if executed:
                new_qty = max(0.0, self.pos.get((symbol, ps), 0.0) - executed) if reducing else self.pos.get((symbol, ps), 0.0) + executed
                lag = self.lag.get(symbol, 0)
                if lag:
                    self._pending.append([lag, symbol, ps, self.pos.get((symbol, ps), 0.0), new_qty])
                self.pos[(symbol, ps)] = new_qty
            row = {"id": self._id, "cid": cid, "symbol": symbol, "side": side, "positionSide": ps, "qty": qty,
                   "executed": executed, "status": status, "t0": t0, "t1": time.monotonic()}
            self.orders.append(row)
            self.rows_by_cid[cid] = row
        if mode == "timeout_after_accept":
            raise httpx.ReadTimeout("read timeout after Aster accepted the order", request=request)
        if mode == "http503_after_accept":
            return self._json({"code": -1007, "msg": "Timeout waiting for response from backend server."}, 503)
        return self._json({"orderId": row["id"], "clientOrderId": cid, "symbol": symbol, "status": status,
                           "executedQty": str(executed), "origQty": str(qty)})
