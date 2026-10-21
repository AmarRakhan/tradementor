"""Pure, offline planner for manual Close Profits percentages. No exchange calls."""
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN, InvalidOperation

PERCENTAGES = {25, 50, 75, 100}
MIN_PROFIT = Decimal("0.50")


def filters_from_aster_exchange_info(exchange_info):
    """Use canonical Aster contract normalization, never guessed lot sizes."""
    from aster_gateway import ContractRules
    results = {}
    for item in exchange_info.get("symbols", []):
        if not isinstance(item, dict) or str(item.get("status", "")).upper() != "TRADING":
            continue
        rules = ContractRules.from_exchange_info(item)
        results[rules.symbol] = {
            "stepSize": str(rules.market_quantity_step),
            "minQty": str(max(rules.market_min_quantity, rules.min_quantity)),
            "minNotional": str(rules.min_notional),
            "maxQty": str(rules.market_max_quantity),
        }
    return results


def _dec(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def build_profit_close_plan(rows, percentage, filters=None, *, closing_fee_rate="0", hedge_links=None, include_short_below_minimum=False):
    """Return candidate legs and individual skips. Pair links map symbols to True only when verified."""
    if percentage not in PERCENTAGES:
        raise ValueError("percentage must be 25, 50, 75 or 100")
    filters = filters or {}
    hedge_links = hedge_links or {}
    positions = {}
    for row in rows:
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", row.get("side", ""))).upper()
        qty = _dec(row.get("positionAmt", row.get("quantity")))
        pnl = _dec(row.get("unRealizedProfit", row.get("unrealizedPnl")))
        mark = _dec(row.get("markPrice"))
        if symbol and side in {"LONG", "SHORT"} and qty is not None and qty != 0:
            positions[(symbol, side)] = {"symbol": symbol, "side": side, "quantity": abs(qty), "pnl": pnl, "mark": mark}
    selected, skipped = [], []
    visited = set()
    fee_rate = _dec(closing_fee_rate)
    if fee_rate is None or fee_rate < 0:
        raise ValueError("invalid closing fee rate")
    # Evaluate LONG first so a linked pair cannot be partially selected because
    # the exchange happened to return its SHORT row first.
    ordered = sorted(positions.items(), key=lambda item: (item[0][0], 0 if item[0][1] == "LONG" else 1))
    for key, leg in ordered:
        if key in visited:
            continue
        symbol, side = key
        opposite = positions.get((symbol, "SHORT" if side == "LONG" else "LONG"))
        linked = bool(opposite and hedge_links.get(symbol) is True)
        if side == "LONG" and opposite and not linked:
            skipped.append({"symbol": symbol, "side": side, "reason": "hedge_relationship_unverified"})
            continue
        legs = [leg]
        if side == "LONG" and linked:
            legs = [leg, opposite]
            pair_profit = None if any(x["pnl"] is None or x["mark"] is None for x in legs) else sum((x["pnl"] - x["quantity"] * x["mark"] * fee_rate) for x in legs)
            if pair_profit is None or pair_profit <= 0:
                # LONG is protected; let an independently profitable SHORT be
                # evaluated on its own during the next iteration.
                skipped.append({"symbol": symbol, "side": "LONG", "reason": "pair_net_not_positive"})
                continue
        elif leg["pnl"] is None or leg["pnl"] <= MIN_PROFIT:
            skipped.append({"symbol": symbol, "side": side, "reason": "profit_not_above_0_50"})
            continue
        proposed = []
        for part in legs:
            rules = filters.get(part["symbol"])
            step = _dec((rules or {}).get("stepSize"))
            minimum = _dec((rules or {}).get("minQty"))
            min_notional = _dec((rules or {}).get("minNotional", "0"))
            max_qty = _dec((rules or {}).get("maxQty", "0"))
            if not rules or step is None or step <= 0 or minimum is None or minimum <= 0 or part["mark"] is None or part["mark"] <= 0 or min_notional is None:
                proposed.append((None, part, "filters_unverified"))
                continue
            quantity = (part["quantity"] * Decimal(percentage) / 100 / step).to_integral_value(rounding=ROUND_DOWN) * step
            if quantity < minimum or quantity * part["mark"] < min_notional or quantity <= 0 or (max_qty is not None and max_qty > 0 and quantity > max_qty):
                proposed.append((None, part, "below_exchange_minimum"))
                continue
            proposed.append((quantity, part, None))
        if linked and side == "LONG" and any(err for _, _, err in proposed):
            skipped.append({"symbol": symbol, "side": "PAIR", "reason": "paired_order_not_eligible"})
            continue
        if linked and side == "LONG":
            visited.add((symbol, "SHORT"))
        for quantity, part, err in proposed:
            if err == "below_exchange_minimum" and include_short_below_minimum and part["side"] == "SHORT" and side == "SHORT":
                # Read-only preview: retain profitable SHORT for the existing per-position
                # close route to issue its own authoritative minimum-size validation.
                selected.append({"symbol": symbol, "side": "SHORT", "quantity": str(part["quantity"]), "percentage": percentage, "paired": False, "minimumWarning": err})
            elif err:
                skipped.append({"symbol": symbol, "side": part["side"], "reason": err})
            else:
                selected.append({"symbol": symbol, "side": part["side"], "quantity": str(quantity), "percentage": percentage, "paired": linked and side == "LONG"})
    return {"percentage": percentage, "selected": selected, "skipped": skipped}
