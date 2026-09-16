"""Pure Profit Sweep transfer accounting and safety helpers.

No exchange or Firestore I/O belongs here.  A sweep is derived only from a
fully reconstructed, flat Aster position cycle.  Incomplete evidence fails
closed, because moving too little is preferable to moving principal.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
from typing import Any

from profit_sweep import sweep_contribution

SUPPORTED_SETTLEMENT_ASSETS = frozenset({"USDT", "USDC"})
EPSILON = Decimal("0.000000000001")


class ProfitSweepTransferError(ValueError):
    pass


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, TypeError, ValueError):
        raise ProfitSweepTransferError("Ongeldige numerieke Aster-historie")
    if not result.is_finite():
        raise ProfitSweepTransferError("Niet-eindige numerieke Aster-historie")
    return result


def _timestamp_ms(row: dict[str, Any]) -> int:
    try:
        return int(row.get("time", row.get("timestamp", 0)) or 0)
    except (TypeError, ValueError):
        return 0


def _trade_id(row: dict[str, Any]) -> str:
    for key in ("id", "tradeId", "orderId"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def settlement_asset(symbol: str) -> str:
    upper = str(symbol or "").strip().upper()
    for asset in SUPPORTED_SETTLEMENT_ASSETS:
        if upper.endswith(asset):
            return asset
    raise ProfitSweepTransferError("Profit Sweep ondersteunt alleen USDT/USDC-settlement")


def deterministic_transfer_id(uid: str, closure_id: str) -> str:
    digest = hashlib.sha256(f"{uid}|{closure_id}".encode()).hexdigest()[:28]
    return f"tmps-{digest}"


@dataclass(frozen=True)
class ClosedCycle:
    closure_id: str
    symbol: str
    side: str
    asset: str
    opened_at_ms: int
    closed_at_ms: int
    gross_realized_profit: Decimal
    proven_costs: Decimal
    net_realized_profit: Decimal
    reliable: bool
    reason: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "closureId": self.closure_id,
            "symbol": self.symbol,
            "side": self.side,
            "asset": self.asset,
            "openedAtMs": self.opened_at_ms,
            "closedAtMs": self.closed_at_ms,
            "grossRealizedProfit": str(self.gross_realized_profit),
            "provenCosts": str(self.proven_costs),
            "netRealizedProfit": str(self.net_realized_profit),
            "reliable": self.reliable,
            "reason": self.reason,
        }


def _fill_direction(row: dict[str, Any]) -> str:
    raw = str(row.get("side", "")).upper().strip()
    if raw in {"BUY", "SELL"}:
        return raw
    buyer = row.get("buyer")
    if buyer is True:
        return "BUY"
    if buyer is False:
        return "SELL"
    return ""


def _is_opening(position_side: str, order_side: str) -> bool:
    return (position_side == "LONG" and order_side == "BUY") or (position_side == "SHORT" and order_side == "SELL")


def _cycle_costs(
    rows: list[dict[str, Any]],
    *,
    asset: str,
    symbol: str,
    opened_at_ms: int,
    closed_at_ms: int,
    income_rows: list[dict[str, Any]],
) -> tuple[Decimal, bool, str]:
    costs = Decimal("0")
    for row in rows:
        commission = abs(_decimal(row.get("commission", 0)))
        if commission <= 0:
            continue
        commission_asset = str(row.get("commissionAsset", "")).upper().strip()
        if commission_asset != asset:
            return costs, False, "Commissie is niet betrouwbaar in settlement-valuta gewaardeerd"
        costs += commission

    # Negative funding is a real trading cost. Positive funding is deliberately
    # ignored, making the net-profit number a conservative lower bound.
    for row in income_rows:
        if str(row.get("symbol", "")).upper().strip() != symbol:
            continue
        at = _timestamp_ms(row)
        if at < opened_at_ms or at > closed_at_ms:
            continue
        kind = str(row.get("incomeType", row.get("type", ""))).upper().strip()
        if kind not in {"FUNDING_FEE", "FUNDING"}:
            continue
        amount = _decimal(row.get("income", row.get("amount", 0)))
        if amount >= 0:
            continue
        cost_asset = str(row.get("asset", asset)).upper().strip() or asset
        if cost_asset != asset:
            return costs, False, "Funding is niet betrouwbaar in settlement-valuta gewaardeerd"
        costs += abs(amount)
    return costs, True, ""


def reconstruct_closed_cycles(
    fills: list[dict[str, Any]],
    income_rows: list[dict[str, Any]],
    *,
    armed_at_ms: int,
) -> list[ClosedCycle]:
    """Reconstruct complete LONG/SHORT cycles and return only post-arm closures.

    A cycle is eligible only when its opening fill is present and the tracked
    position returns fully to zero. Partial closes therefore never move money.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in fills:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", "")).upper().strip()
        if not symbol or side not in {"LONG", "SHORT"}:
            continue
        grouped.setdefault((symbol, side), []).append(row)

    events: list[ClosedCycle] = []
    for (symbol, side), rows in grouped.items():
        rows = sorted(rows, key=lambda row: (_timestamp_ms(row), _trade_id(row)))
        quantity = Decimal("0")
        cycle_rows: list[dict[str, Any]] = []
        opened_at = 0
        reliable = True
        reason = ""
        for row in rows:
            at = _timestamp_ms(row)
            direction = _fill_direction(row)
            qty = abs(_decimal(row.get("qty", row.get("quantity", 0))))
            if at <= 0 or direction not in {"BUY", "SELL"} or qty <= 0:
                # Bad evidence inside a tracked cycle invalidates it.
                if cycle_rows:
                    reliable = False
                    reason = "Fillhistorie bevat een onvolledig record"
                continue
            opening = _is_opening(side, direction)
            if opening:
                if quantity <= EPSILON:
                    quantity = Decimal("0")
                    cycle_rows = []
                    opened_at = at
                    reliable = True
                    reason = ""
                quantity += qty
                cycle_rows.append(row)
                continue

            # A close without a visible opening means the 7-day/1000-row history
            # is incomplete. Never infer principal/cost basis from it.
            if quantity <= EPSILON or not cycle_rows:
                quantity = Decimal("0")
                cycle_rows = []
                opened_at = 0
                reliable = False
                reason = "Openingsfill ontbreekt uit Aster-historie"
                continue
            cycle_rows.append(row)
            if qty > quantity + EPSILON:
                quantity = Decimal("0")
                cycle_rows = []
                opened_at = 0
                reliable = False
                reason = "Sluitfill is groter dan de gereconstrueerde positie"
                continue
            quantity -= qty
            if quantity > EPSILON:
                continue

            closed_at = at
            if closed_at < int(armed_at_ms):
                quantity = Decimal("0")
                cycle_rows = []
                opened_at = 0
                continue
            asset = settlement_asset(symbol)
            gross = Decimal("0")
            closing_ids: list[str] = []
            pnl_reliable = reliable
            pnl_reason = reason
            for cycle_row in cycle_rows:
                if not _is_opening(side, _fill_direction(cycle_row)):
                    if "realizedPnl" not in cycle_row and "realizedProfit" not in cycle_row:
                        pnl_reliable = False
                        pnl_reason = "Sluitfill mist gerealiseerde PnL"
                    gross += _decimal(cycle_row.get("realizedPnl", cycle_row.get("realizedProfit", 0)))
                    closing_ids.append(_trade_id(cycle_row))
            costs, costs_reliable, costs_reason = _cycle_costs(
                cycle_rows, asset=asset, symbol=symbol,
                opened_at_ms=opened_at, closed_at_ms=closed_at, income_rows=income_rows,
            )
            pnl_reliable = pnl_reliable and costs_reliable
            if not costs_reliable:
                pnl_reason = costs_reason
            identity = "|".join(closing_ids) or str(closed_at)
            closure_id = hashlib.sha256(f"{symbol}|{side}|{opened_at}|{closed_at}|{identity}".encode()).hexdigest()
            net = gross - costs
            events.append(ClosedCycle(
                closure_id=closure_id, symbol=symbol, side=side, asset=asset,
                opened_at_ms=opened_at, closed_at_ms=closed_at,
                gross_realized_profit=gross, proven_costs=costs,
                net_realized_profit=net, reliable=pnl_reliable, reason=pnl_reason,
            ))
            quantity = Decimal("0")
            cycle_rows = []
            opened_at = 0
            reliable = True
            reason = ""
    return sorted(events, key=lambda event: event.closed_at_ms)


def sweep_amount_for_cycle(event: ClosedCycle, sweep_percent: Any) -> Decimal:
    if not event.reliable:
        return Decimal("0")
    return sweep_contribution(event.net_realized_profit, sweep_percent, enabled=True)


@dataclass(frozen=True)
class MarginDecision:
    allowed: bool
    available_before: Decimal
    available_after: Decimal
    required_remaining: Decimal
    reason: str


def margin_decision(
    *,
    contribution: Any,
    available_balance: Any,
    maintenance_margin: Any,
    emergency_trigger_reserve: Any,
    protection_reserve: Any = 0,
    release_rehedge_reserve: Any = 0,
) -> MarginDecision:
    amount = max(Decimal("0"), _decimal(contribution))
    available = max(Decimal("0"), _decimal(available_balance))
    required = max(
        Decimal("0"),
        _decimal(emergency_trigger_reserve),
        _decimal(protection_reserve),
        _decimal(release_rehedge_reserve),
        max(Decimal("0"), _decimal(maintenance_margin)) * Decimal("2"),
    )
    after = available - amount
    if amount <= 0:
        return MarginDecision(False, available, after, required, "Geen positieve Profit Pot-bijdrage")
    if after < required:
        return MarginDecision(False, available, after, required, "Futures-marginreserve gaat vóór sparen")
    return MarginDecision(True, available, after, required, "Profit Pot-transfer past binnen de marginreserve")
