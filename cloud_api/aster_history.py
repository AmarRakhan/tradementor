"""Normalization helpers for Aster's authoritative futures fill history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and abs(result) != float("inf") else 0.0


def _is_closing_fill(fill: dict[str, Any]) -> bool:
    position_side = str(fill.get("positionSide", "")).upper()
    order_side = str(fill.get("side", "")).upper()
    if not order_side and "buyer" in fill:
        order_side = "BUY" if bool(fill.get("buyer")) else "SELL"
    return (
        (position_side == "LONG" and order_side == "SELL")
        or (position_side == "SHORT" and order_side == "BUY")
        or abs(_number(fill.get("realizedPnl", fill.get("realizedProfit")))) > 0
    )


def closed_trade_from_fill(fill: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one confirmed closing fill into the dashboard contract."""
    if not _is_closing_fill(fill):
        return None
    timestamp = int(_number(fill.get("time", fill.get("updateTime"))))
    if timestamp <= 0:
        return None
    price = _number(fill.get("price"))
    quantity = abs(_number(fill.get("qty", fill.get("quantity"))))
    quote_quantity = abs(_number(fill.get("quoteQty", fill.get("quoteQuantity"))))
    trade_id = str(fill.get("id", fill.get("tradeId", "")))
    return {
        "symbol": str(fill.get("symbol", "")).upper(),
        "side": str(fill.get("positionSide", "")).upper() or "UNKNOWN",
        "notionalUsd": quote_quantity or quantity * price,
        "exitPrice": price,
        "realizedPnlUsd": _number(fill.get("realizedPnl", fill.get("realizedProfit"))),
        "closedAt": datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).isoformat(),
        "source": "aster-fill",
        "exchangeTradeId": trade_id,
    }


def closed_trades_from_fills(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for fill in fills:
        row = closed_trade_from_fill(fill)
        if row is None:
            continue
        closed_at_ms = int(_number(fill.get("time", fill.get("updateTime"))))
        cycle = trade_events_from_fills(
            fills, symbol=str(row.get("symbol", "")), position_side=str(row.get("side", "")),
            closed_at_ms=closed_at_ms,
        )
        opening = next((event for event in cycle if event.get("kind") == "entry"), None)
        if opening:
            row["openedAt"] = opening["at"]
            row["entryPrice"] = opening["price"]
            row["dcaCount"] = sum(1 for event in cycle if event.get("kind") == "dca")
        rows.append(row)
    rows.sort(key=lambda row: str(row["closedAt"]), reverse=True)
    return rows


def realized_events_from_income(income: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize Aster's authoritative REALIZED_PNL ledger for daily totals."""
    rows: list[dict[str, Any]] = []
    for item in income:
        if str(item.get("incomeType", "")).upper() != "REALIZED_PNL":
            continue
        timestamp = int(_number(item.get("time")))
        if timestamp <= 0:
            continue
        rows.append({
            "symbol": str(item.get("symbol", "")).upper(),
            "realizedPnlUsd": _number(item.get("income")),
            "closedAt": datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).isoformat(),
            "exchangeTransactionId": str(item.get("tranId", item.get("id", ""))),
            "source": "aster-realized-ledger",
        })
    rows.sort(key=lambda row: str(row["closedAt"]), reverse=True)
    return rows


def merge_realized_events(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge durable and freshly fetched ledger rows without losing older events."""
    merged: dict[str, dict[str, Any]] = {}
    for rows in groups:
        for row in rows:
            transaction_id = str(row.get("exchangeTransactionId", "")).strip()
            key = f"transaction:{transaction_id}" if transaction_id else "|".join(
                str(row.get(field, "")) for field in ("symbol", "closedAt", "realizedPnlUsd")
            )
            merged[key] = row
    return sorted(merged.values(), key=lambda row: str(row.get("closedAt", "")), reverse=True)


def strategy_by_order_id_from_orders(
    orders: list[dict[str, Any]], strategy_by_intent: dict[str, str] | None = None,
) -> dict[str, str]:
    """Join Aster order ids to proven strategy client ids without inference."""
    strategy_by_intent = strategy_by_intent or {}
    result: dict[str, str] = {}
    for raw in orders:
        if not isinstance(raw, dict):
            continue
        order_id = str(raw.get("orderId", raw.get("orderID", ""))).strip()
        client_order_id = str(raw.get(
            "clientOrderId", raw.get("clientOrderID", raw.get("origClientOrderId", "")),
        )).strip()
        if not order_id or not client_order_id:
            continue
        strategy = strategy_by_intent.get(client_order_id, "")
        lowered = client_order_id.lower()
        if not strategy and lowered.startswith(("s3-", "s3i-", "s3h-", "s3r-")):
            strategy = "Strategy 3"
        elif not strategy and lowered.startswith(("s2-", "s2i-", "s2h-", "s2r-")):
            strategy = "Strategy 2"
        elif not strategy and lowered.startswith(("s1-", "s1i-", "aster-")):
            strategy = "Strategy 1"
        if strategy:
            result[order_id] = strategy
    return result


def recent_trade_activity_from_fills(
    fills: list[dict[str, Any]], *, active_positions: list[dict[str, Any]] | None = None,
    strategy_by_intent: dict[str, str] | None = None,
    strategy_by_order_id: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return a read-only view of Aster-confirmed buy/sell activity.

    Partial fills belonging to the same Aster order are combined. Strategy
    attribution is metadata only and never changes exchange state.
    """
    strategy_by_intent = strategy_by_intent or {}
    strategy_by_order_id = strategy_by_order_id or {}

    def fill_strategy(raw: dict[str, Any]) -> str:
        order_id = str(raw.get("orderId", raw.get("orderID", raw.get("id", raw.get("tradeId", "")))))
        client_order_id = str(raw.get("clientOrderId", raw.get("clientOrderID", "")))
        strategy = strategy_by_order_id.get(order_id, "") or strategy_by_intent.get(client_order_id, "")
        lowered = client_order_id.lower()
        if not strategy and lowered.startswith(("s3-", "s3i-", "s3h-", "s3r-")):
            strategy = "Strategy 3"
        elif not strategy and lowered.startswith(("s2-", "s2i-", "s2h-", "s2r-")):
            strategy = "Strategy 2"
        elif not strategy and lowered.startswith(("s1-", "s1i-", "aster-")):
            strategy = "Strategy 1"
        return strategy

    # Aster can omit the client-order id from a closing fill. Walk each
    # uninterrupted position cycle in exchange-time order so a close can
    # inherit the already proven strategy of its opening/DCA fill. A cycle
    # without proof remains deliberately unattributed.
    cycle_strategy_by_fill: dict[int, str] = {}
    cycles: dict[tuple[str, str], dict[str, Any]] = {}
    ordered_fills = sorted(
        (raw for raw in fills if isinstance(raw, dict)),
        key=lambda raw: int(_number(raw.get("time", raw.get("updateTime")))),
    )
    for raw in ordered_fills:
        symbol = str(raw.get("symbol", "")).upper()
        side = str(raw.get("positionSide", "")).upper()
        order_side = str(raw.get("side", "")).upper()
        if not order_side and "buyer" in raw:
            order_side = "BUY" if bool(raw.get("buyer")) else "SELL"
        quantity = abs(_number(raw.get("qty", raw.get("quantity"))))
        if not symbol or side not in {"LONG", "SHORT"} or order_side not in {"BUY", "SELL"} or quantity <= 0:
            continue
        increases = (side == "LONG" and order_side == "BUY") or (side == "SHORT" and order_side == "SELL")
        key = (symbol, side)
        cycle = cycles.setdefault(key, {"exposure": 0.0, "strategy": ""})
        explicit = fill_strategy(raw)
        if increases:
            if _number(cycle.get("exposure")) <= 1e-12:
                cycle = {"exposure": 0.0, "strategy": explicit}
                cycles[key] = cycle
            elif explicit and cycle.get("strategy") and explicit != cycle.get("strategy"):
                cycle["strategy"] = ""
            elif explicit:
                cycle["strategy"] = explicit
            cycle["exposure"] = _number(cycle.get("exposure")) + quantity
        elif _number(cycle.get("exposure")) > 1e-12:
            cycle["exposure"] = max(0.0, _number(cycle.get("exposure")) - quantity)
        inherited = explicit or str(cycle.get("strategy", ""))
        if inherited:
            cycle_strategy_by_fill[id(raw)] = inherited
        if not increases and _number(cycle.get("exposure")) <= 1e-12:
            cycles.pop(key, None)

    positions: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in active_positions or []:
        symbol = str(raw.get("symbol", "")).upper()
        side = str(raw.get("positionSide", raw.get("side", ""))).upper()
        if symbol and side in {"LONG", "SHORT"}:
            positions[(symbol, side)] = raw

    grouped: dict[str, dict[str, Any]] = {}
    for raw in fills:
        symbol = str(raw.get("symbol", "")).upper()
        side = str(raw.get("positionSide", "")).upper()
        order_side = str(raw.get("side", "")).upper()
        if not order_side and "buyer" in raw:
            order_side = "BUY" if bool(raw.get("buyer")) else "SELL"
        timestamp = int(_number(raw.get("time", raw.get("updateTime"))))
        price = _number(raw.get("price"))
        quantity = abs(_number(raw.get("qty", raw.get("quantity"))))
        if not symbol or side not in {"LONG", "SHORT"} or order_side not in {"BUY", "SELL"}:
            continue
        if timestamp <= 0 or price <= 0 or quantity <= 0:
            continue
        increases = (side == "LONG" and order_side == "BUY") or (side == "SHORT" and order_side == "SELL")
        order_id = str(raw.get("orderId", raw.get("orderID", raw.get("id", raw.get("tradeId", "")))))
        client_order_id = str(raw.get("clientOrderId", raw.get("clientOrderID", "")))
        strategy = fill_strategy(raw) or cycle_strategy_by_fill.get(id(raw), "")
        key = f"{symbol}|{side}|{order_side}|{order_id or timestamp}"
        row = grouped.setdefault(key, {
            "id": order_id or key, "symbol": symbol, "side": side,
            "orderSide": order_side, "action": "ENTRY" if increases else "EXIT",
            "quantity": 0.0, "executedNotionalUsd": 0.0, "realizedPnlUsd": 0.0,
            "commissionUsd": 0.0, "timestampMs": timestamp, "source": "aster-fill",
            "strategy": strategy or "Niet aan strategie gekoppeld", "clientOrderId": client_order_id,
        })
        row["quantity"] += quantity
        row["executedNotionalUsd"] += quantity * price
        row["realizedPnlUsd"] += _number(raw.get("realizedPnl", raw.get("realizedProfit")))
        row["commissionUsd"] += abs(_number(raw.get("commission")))
        row["timestampMs"] = max(int(row["timestampMs"]), timestamp)

    entries: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    for row in grouped.values():
        quantity = _number(row.get("quantity"))
        notional = _number(row.get("executedNotionalUsd"))
        timestamp = int(row.get("timestampMs", 0))
        row["averagePrice"] = notional / quantity if quantity > 0 else 0.0
        row["executedAt"] = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).isoformat()
        if row["action"] == "ENTRY":
            position = positions.get((str(row["symbol"]), str(row["side"])))
            if position:
                position_qty = abs(_number(position.get("positionAmt", position.get("quantity"))))
                position_pnl = _number(position.get("unRealizedProfit", position.get("unrealizedPnl")))
                allocation = min(1.0, quantity / position_qty) if position_qty > 0 else 0.0
                row["unrealizedPnlUsd"] = position_pnl * allocation
                row["currentValueUsd"] = notional + row["unrealizedPnlUsd"]
            else:
                row["unrealizedPnlUsd"] = None
                row["currentValueUsd"] = None
            entries.append(row)
        else:
            row["costBasisUsd"] = notional - _number(row.get("realizedPnlUsd"))
            row["closedValueUsd"] = notional
            exits.append(row)
    sorter = lambda row: int(row.get("timestampMs", 0))
    entries.sort(key=sorter, reverse=True)
    exits.sort(key=sorter, reverse=True)
    return {"entries": entries[:20], "exits": exits[:20]}


def trade_events_from_fills(
    fills: list[dict[str, Any]], *, symbol: str, position_side: str, closed_at_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Reconstruct one position cycle solely from confirmed Aster fills."""
    wanted_symbol, wanted_side = symbol.upper(), position_side.upper()
    if wanted_side not in {"LONG", "SHORT"}:
        return []
    relevant = []
    for raw in fills:
        if str(raw.get("symbol", "")).upper() != wanted_symbol or str(raw.get("positionSide", "")).upper() != wanted_side:
            continue
        timestamp = int(_number(raw.get("time", raw.get("updateTime"))))
        price = _number(raw.get("price"))
        quantity = abs(_number(raw.get("qty", raw.get("quantity"))))
        if timestamp <= 0 or price <= 0 or quantity <= 0:
            continue
        order_side = str(raw.get("side", "")).upper()
        if not order_side and "buyer" in raw:
            order_side = "BUY" if bool(raw.get("buyer")) else "SELL"
        increases = (wanted_side == "LONG" and order_side == "BUY") or (wanted_side == "SHORT" and order_side == "SELL")
        closes = (wanted_side == "LONG" and order_side == "SELL") or (wanted_side == "SHORT" and order_side == "BUY")
        if increases or closes:
            relevant.append((timestamp, str(raw.get("id", raw.get("tradeId", ""))), price, quantity, increases))
    relevant.sort(key=lambda item: (item[0], item[1]))

    cycles: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    exposure = 0.0
    increase_count = 0
    for timestamp, trade_id, price, quantity, increases in relevant:
        if increases:
            if exposure <= 1e-12:
                current, increase_count = [], 0
            kind, action = ("entry" if increase_count == 0 else "dca"), "increase"
            increase_count += 1
            exposure += quantity
        else:
            if exposure <= 1e-12:
                continue
            kind, action = "close", "close"
            exposure = max(0.0, exposure - quantity)
        current.append({
            "id": trade_id or f"{wanted_symbol}:{wanted_side}:{timestamp}:{len(current)}",
            "symbol": wanted_symbol, "side": wanted_side, "kind": kind, "action": action,
            "price": price, "quantity": quantity, "notionalUsd": price * quantity,
            "notional": price * quantity,
            "dcaNumber": increase_count - 1 if kind == "dca" else None,
            "exchange": "Aster",
            "at": datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).isoformat(), "timestampMs": timestamp,
        })
        if closed_at_ms is not None and not increases and abs(timestamp - closed_at_ms) <= 2_000:
            return list(current)
        if exposure <= 1e-12:
            cycles.append(list(current)); current, increase_count = [], 0
    if closed_at_ms is not None:
        return min(cycles, key=lambda cycle: abs(int(cycle[-1]["timestampMs"]) - closed_at_ms)) if cycles else []
    return list(current)
