"""Persistent multi-pair Aster Hedge Mode state reconciliation."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0




def _position_return_pct(row: dict[str, Any]) -> float:
    for key in ("returnPct", "roePct", "roiPct"):
        if row.get(key) not in (None, ""):
            return _number(row.get(key))
    pnl = _number(row.get("unRealizedProfit", row.get("unrealizedProfit")))
    margin = _number(row.get("positionInitialMargin", row.get("initialMargin")))
    if margin > 0:
        return pnl / margin * 100
    quantity = abs(_number(row.get("positionAmt")))
    entry = _number(row.get("entryPrice"))
    leverage = max(1, int(_number(row.get("leverage")) or 1))
    derived_margin = quantity * entry / leverage
    return pnl / derived_margin * 100 if derived_margin > 0 else 0.0

def account_values(usdt: dict[str, Any], positions: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    """Normalize Aster balance variants to equity, wallet, available and PnL."""
    available = _number(usdt.get("availableBalance", usdt.get("available")))
    unrealized = _number(usdt.get("crossUnPnl", usdt.get("unrealizedProfit")))
    wallet = max(
        _number(usdt.get("balance")), _number(usdt.get("crossWalletBalance")),
        _number(usdt.get("walletBalance")), _number(usdt.get("totalWalletBalance")),
    )
    active = [row for row in positions if abs(_number(row.get("positionAmt"))) > 0]
    position_margin = sum(_number(row.get("positionInitialMargin", row.get("initialMargin"))) for row in active)
    if wallet <= 0:
        wallet = available + position_margin
    equity = wallet + unrealized
    if not active:
        equity = max(equity, available)
    return equity, wallet, available, unrealized


def account_information_values(account: dict[str, Any]) -> tuple[float, float, float, float, float]:
    """Read Aster's own equity, wallet, available, PnL and maintenance totals."""
    wallet = _number(account.get("totalWalletBalance"))
    available = _number(account.get("availableBalance"))
    unrealized = _number(account.get("totalUnrealizedProfit"))
    equity = _number(account.get("totalMarginBalance")) or wallet + unrealized
    maintenance = _number(account.get("totalMaintMargin"))
    return equity, wallet, available, unrealized, maintenance


def dashboard_snapshot(account: dict[str, Any], positions: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the dashboard snapshot from Aster's current account-information response."""
    equity, wallet, available, unrealized, maintenance = account_information_values(account)
    active = [row for row in positions if abs(_number(row.get("positionAmt"))) > 0]
    active_trade_capital = sum(
        _number(row.get("positionInitialMargin", row.get("initialMargin")))
        for row in active
    )
    if active and active_trade_capital <= 0:
        active_trade_capital = _number(account.get("totalInitialMargin"))
    return {
        "equity": equity,
        "walletBalance": wallet,
        "availableBalance": available,
        "unrealizedPnl": unrealized,
        "activePositions": len(active),
        "activeTradeCapital": active_trade_capital,
        "maintenanceMargin": maintenance,
        "marginRatio": maintenance / equity if equity > 0 else (1.0 if active else 0.0),
        "financialDataContract": {
            "version": 1,
            "sourceOfTruth": "ASTER_API",
            "direct": {
                "equity": "totalMarginBalance",
                "availableBalance": "availableBalance",
                "unrealizedPnl": "totalUnrealizedProfit",
                "maintenanceMargin": "totalMaintMargin",
                "positionUnrealizedPnl": "unRealizedProfit",
                "positionLiquidationPrice": "liquidationPrice",
            },
            "aggregated": {
                "activePositions": "count(positionAmt != 0)",
                "activeTradeCapital": "sum(positionInitialMargin) for active positions",
            },
            "calculated": {
                "marginRatio": "totalMaintMargin / totalMarginBalance",
                "positionDisplayReturnPct": "Aster returnPct/roePct/roiPct or unRealizedProfit / effective initial margin * 100",
            },
            "positionDisplayReturnIsTakeProfitStatus": False,
        },
        "positions": [{
            "symbol": str(row.get("symbol", "")),
            "side": str(row.get("positionSide", "")),
            "quantity": abs(_number(row.get("positionAmt"))),
            "notionalUsd": abs(_number(row.get("positionAmt"))) * _number(row.get("markPrice")),
            "entryPrice": _number(row.get("entryPrice")),
            "markPrice": _number(row.get("markPrice")),
            "liquidationPrice": _number(row.get("liquidationPrice")),
            "unrealizedPnl": _number(row.get("unRealizedProfit", row.get("unrealizedProfit"))),
            "initialMarginUsd": _number(row.get("positionInitialMargin", row.get("initialMargin"))),
            "dataSource": "ASTER_API",
            "leverage": max(1, int(_number(row.get("leverage")) or 1)),
            **({"returnPct": _number(row.get("returnPct"))} if row.get("returnPct") not in (None, "") else {}),
            **({"roePct": _number(row.get("roePct"))} if row.get("roePct") not in (None, "") else {}),
            **({"roiPct": _number(row.get("roiPct"))} if row.get("roiPct") not in (None, "") else {}),
        } for row in active],
    }


def infer_dca_level(position_notional: float, base_notional: float, multiplier: float, maximum: int) -> int | None:
    """Infer a lost DCA counter only when notional closely matches the configured ladder."""
    if position_notional <= 0 or base_notional <= 0 or multiplier <= 0:
        return None
    candidate = max(0, min(maximum, round((position_notional / base_notional - 1) / multiplier)))
    expected = base_notional * (1 + multiplier * candidate)
    return candidate if abs(position_notional - expected) <= max(.10, expected * .12) else None


@dataclass(frozen=True)
class AsterLegState:
    side: str
    quantity: float = 0.0
    average_entry: float = 0.0
    leverage: int = 1
    margin_type: str = "cross"
    dca_level: int = 0


@dataclass(frozen=True)
class AsterPairState:
    symbol: str
    long: AsterLegState
    short: AsterLegState
    open_order_ids: tuple[str, ...] = ()
    last_exchange_event_ms: int = 0
    metadata_needs_rebuild: bool = False


@dataclass(frozen=True)
class AsterAccountState:
    schema_version: int = 1
    hedge_mode_confirmed: bool = False
    pairs: tuple[AsterPairState, ...] = ()

    def pair(self, symbol: str) -> AsterPairState | None:
        wanted = symbol.upper()
        return next((item for item in self.pairs if item.symbol == wanted), None)


@dataclass(frozen=True)
class AsterStateReconciliation:
    state: AsterAccountState
    changed: bool
    allow_risk_increase: bool
    reasons: tuple[str, ...]


def state_from_mapping(raw: dict[str, Any] | None) -> AsterAccountState | None:
    if not isinstance(raw, dict) or not raw:
        return None
    pairs: list[AsterPairState] = []
    for item in raw.get("pairs", ()):
        if not isinstance(item, dict):
            continue
        def leg(side: str) -> AsterLegState:
            value = item.get(side.lower()) if isinstance(item.get(side.lower()), dict) else {}
            return AsterLegState(
                side, _number(value.get("quantity")), _number(value.get("averageEntry")),
                max(1, int(_number(value.get("leverage")) or 1)),
                str(value.get("marginType", "cross")), int(_number(value.get("dcaLevel"))),
            )
        symbol = str(item.get("symbol", "")).upper()
        if symbol:
            pairs.append(AsterPairState(
                symbol, leg("LONG"), leg("SHORT"), tuple(str(x) for x in item.get("openOrderIds", ()) if x),
                int(_number(item.get("lastExchangeEventMs"))), bool(item.get("metadataNeedsRebuild", False)),
            ))
    return AsterAccountState(int(_number(raw.get("schemaVersion", 1)) or 1),
                             bool(raw.get("hedgeModeConfirmed", False)), tuple(pairs))


def state_to_mapping(state: AsterAccountState) -> dict[str, Any]:
    def leg(value: AsterLegState) -> dict[str, Any]:
        return {"quantity": value.quantity, "averageEntry": value.average_entry, "leverage": value.leverage,
                "marginType": value.margin_type, "dcaLevel": value.dca_level}
    return {"schemaVersion": state.schema_version, "hedgeModeConfirmed": state.hedge_mode_confirmed,
            "pairs": [{"symbol": pair.symbol, "long": leg(pair.long), "short": leg(pair.short),
                       "openOrderIds": list(pair.open_order_ids), "lastExchangeEventMs": pair.last_exchange_event_ms,
                       "metadataNeedsRebuild": pair.metadata_needs_rebuild} for pair in state.pairs]}


def reconcile_aster_state(
    *,
    persisted: AsterAccountState | None,
    exchange_positions: list[dict[str, Any]],
    exchange_open_orders: list[dict[str, Any]],
    hedge_mode_confirmed: bool,
    exchange_read_ok: bool,
    round_trip_verified: bool = False,
    fills_reconciled: bool = False,
) -> AsterStateReconciliation:
    if not exchange_read_ok:
        return AsterStateReconciliation(
            persisted or AsterAccountState(), False, False,
            ("Aster exchange-state kon niet betrouwbaar worden gelezen",),
        )

    persisted_by_symbol = {item.symbol: item for item in (persisted.pairs if persisted else ())}
    positions: dict[tuple[str, str], dict[str, Any]] = {}
    symbols: set[str] = set(persisted_by_symbol)
    for raw in exchange_positions:
        symbol = str(raw.get("symbol", "")).upper()
        side = str(raw.get("positionSide", "")).upper()
        quantity = abs(_number(raw.get("positionAmt", 0)))
        if symbol and side in {"LONG", "SHORT"} and quantity > 0:
            positions[(symbol, side)] = raw
            symbols.add(symbol)

    order_ids: dict[str, list[str]] = {}
    for raw in exchange_open_orders:
        symbol = str(raw.get("symbol", "")).upper()
        order_id = str(raw.get("orderId", raw.get("clientOrderId", "")))
        if symbol and order_id:
            symbols.add(symbol)
            order_ids.setdefault(symbol, []).append(order_id)

    changed = persisted is None or persisted.hedge_mode_confirmed != hedge_mode_confirmed
    reasons: list[str] = []
    rebuilt_pairs: list[AsterPairState] = []
    for symbol in sorted(symbols):
        previous = persisted_by_symbol.get(symbol)
        previous_long = previous.long if previous else AsterLegState("LONG")
        previous_short = previous.short if previous else AsterLegState("SHORT")
        long = _leg_from_exchange("LONG", positions.get((symbol, "LONG")), previous_long)
        short = _leg_from_exchange("SHORT", positions.get((symbol, "SHORT")), previous_short)
        previous_orders = previous.open_order_ids if previous else ()
        current_orders = tuple(sorted(order_ids.get(symbol, ())))
        leg_changed = _leg_changed(previous_long, long) or _leg_changed(previous_short, short)
        has_exposure = long.quantity > 0 or short.quantity > 0
        metadata_rebuild = has_exposure and (
            (previous.metadata_needs_rebuild if previous else False)
            or leg_changed
        ) and not fills_reconciled
        if metadata_rebuild:
            reasons.append(f"{symbol}: positie wijkt af; DCA-metadata moet uit fills worden herbouwd")
        pair = AsterPairState(
            symbol=symbol,
            long=long,
            short=short,
            open_order_ids=current_orders,
            last_exchange_event_ms=previous.last_exchange_event_ms if previous else 0,
            metadata_needs_rebuild=metadata_rebuild,
        )
        if previous is None or pair != previous or current_orders != previous_orders:
            changed = True
        # Remove empty, orderless pairs only after exchange confirms they are
        # flat; this prevents stale active cards while retaining no ghost risk.
        if has_exposure or current_orders:
            rebuilt_pairs.append(pair)

    state = AsterAccountState(1, hedge_mode_confirmed, tuple(rebuilt_pairs))
    if not hedge_mode_confirmed:
        reasons.append("Aster Hedge Mode is niet bevestigd")
    if changed and not round_trip_verified:
        reasons.append("Exchange-authoritatieve state moet nog persistent worden teruggelezen")
    ready = hedge_mode_confirmed and (not changed or round_trip_verified) and not any(
        item.metadata_needs_rebuild for item in state.pairs
    )
    return AsterStateReconciliation(
        state=state,
        changed=changed,
        allow_risk_increase=ready,
        reasons=tuple(reasons or ("Aster multi-pair state is volledig gereconcilieerd",)),
    )


def apply_exchange_event(pair: AsterPairState, event: dict[str, Any]) -> AsterPairState:
    """Apply only a strictly newer stream cursor; payload parsing follows later."""
    event_time = int(_number(event.get("E", 0)))
    if event_time <= pair.last_exchange_event_ms:
        return pair
    return replace(pair, last_exchange_event_ms=event_time)


def _leg_from_exchange(side: str, raw: dict[str, Any] | None, previous: AsterLegState) -> AsterLegState:
    if raw is None:
        return AsterLegState(side)
    quantity = abs(_number(raw.get("positionAmt", 0)))
    return AsterLegState(
        side=side,
        quantity=quantity,
        average_entry=_number(raw.get("entryPrice", 0)),
        leverage=max(1, int(_number(raw.get("leverage", 1)))),
        margin_type=str(raw.get("marginType", "cross")).lower(),
        dca_level=previous.dca_level if math.isclose(previous.quantity, quantity) else 0,
    )


def _leg_changed(previous: AsterLegState, current: AsterLegState) -> bool:
    return not (
        math.isclose(previous.quantity, current.quantity, rel_tol=1e-8, abs_tol=1e-8)
        and math.isclose(previous.average_entry, current.average_entry, rel_tol=1e-8, abs_tol=1e-8)
    )
