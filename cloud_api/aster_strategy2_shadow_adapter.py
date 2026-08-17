"""Fail-closed conversion of read-only exchange truth into shadow inputs.

This adapter does not own a database or exchange client.  Callers may only
provide snapshots obtained through GET/read methods.  The result can be fed to
``plan_validated_shadow``; no mutation capability crosses this boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from aster_execution import plan_pair
from aster_strategy2 import Strategy2Config
from aster_strategy2_queue import PendingReopen
from aster_strategy2_runtime import (
    active_position_map, cost_evidence_max_age_seconds, owned_from_mapping,
    next_balanced_entry_side, portfolio_state,
)
from aster_strategy2_shadow import ShadowInputs
from aster_strategy2_state import OwnedLeg
from aster_universe import build_snapshot


class ShadowSnapshotRejected(ValueError):
    """The supplied read snapshot is not reliable enough to plan actions."""


@dataclass(frozen=True)
class ReadOnlyAccountSnapshot:
    account_uid: str
    scan_id: str
    captured_at_ms: int
    strategy_state: dict[str, Any]
    hedge_mode: bool
    account: dict[str, Any]
    positions: tuple[dict[str, Any], ...]
    open_orders: tuple[dict[str, Any], ...]
    exchange_reliable: bool = True
    entry_symbols: tuple[str, ...] = ()


def validated_entry_symbols(
    *, config: Strategy2Config, owned: tuple[OwnedLeg, ...],
    positions: tuple[dict[str, Any], ...], account: dict[str, Any],
    exchange_info: dict[str, Any], ticker_prices: tuple[dict[str, Any], ...],
    tickers_24h: tuple[dict[str, Any], ...],
    leverage_brackets: tuple[dict[str, Any], ...],
    captured_at_ms: int,
) -> tuple[str, ...]:
    """Return only currently executable entry symbols, without mutations."""
    universe = build_snapshot(
        exchange_info, tickers_24h, config.universe_top_n,
        fetched_at=datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc),
        base_notional=config.base_notional,
    )
    rows = {str(row.get("symbol", "")).upper(): row
            for row in exchange_info.get("symbols", ()) if isinstance(row, dict)}
    prices = {str(row.get("symbol", "")).upper(): float(row.get("price", 0) or 0)
              for row in ticker_prices if isinstance(row, dict)}
    brackets = {str(row.get("symbol", "")).upper(): list(row.get("brackets") or [])
                for row in leverage_brackets if isinstance(row, dict)}
    active_keys = set(active_position_map(list(positions)))
    exposure: dict[str, Decimal] = {}
    for row in positions:
        symbol = str(row.get("symbol", "")).upper()
        try:
            notional = abs(Decimal(str(row.get("positionAmt", 0)))
                           * Decimal(str(row.get("markPrice", 0))))
        except Exception:
            continue
        exposure[symbol] = exposure.get(symbol, Decimal("0")) + notional
    try:
        remaining_margin = float(account.get("availableBalance", 0) or 0)
    except (TypeError, ValueError):
        return ()

    simulated = list(owned)
    result: list[str] = []
    for market in universe.selected:
        side = next_balanced_entry_side(simulated, config.maximum_pairs)
        if not side:
            break
        symbol = market.symbol
        if (symbol, side) in active_keys or symbol not in rows or prices.get(symbol, 0) <= 0:
            continue
        symbol_brackets = brackets.get(symbol, [])
        if not symbol_brackets:
            continue
        try:
            initial = plan_pair(
                rows[symbol], symbol_brackets, prices[symbol], config.base_notional,
                existing_contract_notional=exposure.get(symbol, Decimal("0")),
            )
            accepted = min(initial.leverage, config.leverage)
            plan = plan_pair(
                rows[symbol], symbol_brackets, prices[symbol], config.base_notional,
                accepted_leverage=accepted,
                existing_contract_notional=exposure.get(symbol, Decimal("0")),
            )
        except (TypeError, ValueError):
            continue
        required_margin = float(plan.notional_per_leg) / max(1, plan.leverage) * 1.05
        if required_margin > remaining_margin:
            continue
        remaining_margin -= required_margin
        result.append(symbol)
        simulated.append(OwnedLeg(
            config.strategy_id, "strategy2", symbol, side,
            f"shadow-contract-{len(result)}", config.version,
        ))
        active_keys.add((symbol, side))
        exposure[symbol] = exposure.get(symbol, Decimal("0")) + plan.notional_per_leg
    return tuple(result)


def _owned_rows(state: dict[str, Any]) -> tuple[OwnedLeg, ...]:
    raw = state.get("ownedLegs")
    if not isinstance(raw, list):
        raise ShadowSnapshotRejected("Strategy-2 ownership ontbreekt")
    result: list[OwnedLeg] = []
    for row in raw:
        try:
            leg = owned_from_mapping(row)
        except (TypeError, ValueError) as exc:
            raise ShadowSnapshotRejected("Strategy-2 ownership is ongeldig") from exc
        if leg.strategy_id != "aster-strategy-2" or leg.engine_type != "strategy2":
            raise ShadowSnapshotRejected("Niet-exclusieve Strategy-2 ownership aangetroffen")
        result.append(leg)
    return tuple(result)


def _pending_rows(state: dict[str, Any]) -> tuple[PendingReopen, ...]:
    raw = state.get("pendingReopens", [])
    if not isinstance(raw, list):
        raise ShadowSnapshotRejected("pendingReopens heeft een ongeldig formaat")
    result = []
    for row in raw:
        if not isinstance(row, dict):
            raise ShadowSnapshotRejected("pendingReopen is ongeldig")
        try:
            result.append(PendingReopen(
                symbol=str(row.get("symbol", "")).upper(),
                side=str(row.get("side", "")).upper(),
                closed_cycle_id=str(row.get("closed_cycle_id", row.get("closedCycleId", ""))),
                package_id=str(row.get("package_id", row.get("packageId", ""))),
                notional=float(row.get("notional", 0)),
                created_scan_id=str(row.get("created_scan_id", row.get("createdScanId", ""))),
                reason=str(row.get("reason", "ORDER_BUDGET_EXHAUSTED")),
                cooldown_until_ms=int(row.get("cooldown_until_ms", row.get("cooldownUntilMs", 0)) or 0),
                attempts=int(row.get("attempts", 0) or 0),
            ))
        except (TypeError, ValueError) as exc:
            raise ShadowSnapshotRejected("pendingReopen is ongeldig") from exc
    if any(not x.symbol or x.side not in {"LONG", "SHORT"} or not x.package_id
           or x.notional <= 0 for x in result):
        raise ShadowSnapshotRejected("pendingReopen mist betrouwbaar bewijs")
    return tuple(result)


def validated_shadow_inputs(snapshot: ReadOnlyAccountSnapshot) -> ShadowInputs:
    """Validate one immutable snapshot without reading or writing externally."""
    state = snapshot.strategy_state
    if not snapshot.exchange_reliable:
        raise ShadowSnapshotRejected("Aster exchange-state is onzeker")
    if not snapshot.hedge_mode:
        raise ShadowSnapshotRejected("Aster Hedge Mode staat uit")
    if not bool(state.get("exclusiveOwnership")):
        raise ShadowSnapshotRejected("Exclusieve Strategy-2 ownership is niet bewezen")
    if snapshot.open_orders:
        raise ShadowSnapshotRejected("Bestaande Aster-order moet eerst worden gereconcilieerd")
    if snapshot.captured_at_ms <= 0:
        raise ShadowSnapshotRejected("Snapshot-tijd ontbreekt")

    config = Strategy2Config.from_mapping(state.get("settings"))
    owned = _owned_rows(state)
    active = active_position_map(list(snapshot.positions))
    owned_keys = {(leg.symbol, leg.side) for leg in owned}
    if set(active) != owned_keys:
        raise ShadowSnapshotRejected("Aster-posities en Strategy-2 ownership komen niet exact overeen")

    maximum_age_ms = cost_evidence_max_age_seconds(list(owned)) * 1000
    fresh_cost_keys = frozenset(
        (leg.symbol, leg.side) for leg in owned
        if leg.costs_updated_at_ms > 0
        and 0 <= snapshot.captured_at_ms - leg.costs_updated_at_ms <= maximum_age_ms
    )
    high_water_mark = float(state.get("adjustedHighWaterMark", 0) or 0)
    portfolio = portfolio_state(
        config, snapshot.account, list(snapshot.positions), list(owned), high_water_mark,
        exchange_reliable=True, ownership_reliable=True, open_orders_unknown=False,
    )
    queue = state.get("orderQueueState") if isinstance(state.get("orderQueueState"), dict) else {}
    orders_used = int(queue.get("ordersUsed", 0) or 0)
    if not 0 <= orders_used <= 15:
        raise ShadowSnapshotRejected("Persistente orders_used-teller is ongeldig")
    return ShadowInputs(
        account_uid=snapshot.account_uid, scan_id=snapshot.scan_id,
        config=config, portfolio=portfolio, owned=owned,
        positions=snapshot.positions, pending_reopens=_pending_rows(state),
        entry_symbols=snapshot.entry_symbols, orders_used=orders_used,
        halted_uncertain=bool(queue.get("haltedUncertain", False)),
        close_evidence_keys=fresh_cost_keys,
    )
