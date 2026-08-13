"""Transactional Aster pair execution with compensation on half-open hedges."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, ROUND_UP
from typing import Any, Callable

from aster_gateway import (
    AsterAutomationConfig, AsterOrderIntent, ContractRules, LeverageBracket,
    PositionSide, maximum_allowed_leverage,
)


@dataclass(frozen=True)
class PairExecutionPlan:
    symbol: str
    quantity: Decimal
    notional_per_leg: Decimal
    leverage: int


def client_order_id(*parts: str) -> str:
    """Build a deterministic Aster client order id within its 36-char limit."""
    raw = "-".join(str(part).strip("-") for part in parts if str(part).strip("-"))
    if len(raw) <= 36:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"{raw[:25]}-{digest}"


def contract_brackets(client: Any, bulk_rows: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    """Resolve brackets from bulk data, falling back to a symbol query.

    Aster's account-wide bracket response can omit otherwise tradable symbols.
    Missing bulk data must therefore not silently shrink a Top-N universe.
    """
    def select(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            if str(row.get("symbol", "")).upper() == symbol.upper():
                return list(row.get("brackets") or [])
        if rows and all("initialLeverage" in row for row in rows):
            return list(rows)
        return []
    brackets=select(bulk_rows)
    if brackets:return brackets
    brackets=select(client.leverage_brackets(symbol))
    if not brackets:raise ValueError(f"{symbol}: Aster gaf geen geldige leveragebrackets")
    return brackets


def planning_brackets(client: Any, bulk_rows: list[dict[str, Any]], symbol: str,
                      requested_leverage: int) -> list[dict[str, Any]]:
    """Return planning brackets without excluding a tradable contract.

    Some Aster contracts are present in exchangeInfo and accept leverage
    changes, while both account-wide and per-symbol bracket reads return no
    rows.  A synthetic planning ceiling keeps those contracts eligible.  The
    real OPEN path still calls configure_maximum_usable_leverage, so Aster
    remains the final authority and can only lower this value.
    """
    try:
        return contract_brackets(client, bulk_rows, symbol)
    except ValueError:
        return [{"notionalFloor": "0", "notionalCap": "0",
                 "initialLeverage": max(1, int(requested_leverage)),
                 "maintMarginRatio": "0"}]


def is_definite_contract_rejection(exc: Exception) -> bool:
    """Return true only for explicit pre-fill contract/leverage rejections.

    These responses prove that Aster rejected the requested contract settings;
    they are safe to skip while selecting another symbol.  Timeouts, network
    failures and unknown order states deliberately return false because those
    must stop the scheduler rather than risk a duplicate order.
    """
    messages=[]
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current));messages.append(str(current).lower())
        current=current.__cause__ or current.__context__
    text=" ".join(messages)
    return any(marker in text for marker in (
        "-5018", "-2027", "-4131", "maximum notional", "maximum supported leverage",
        "leverage exceeds", "max leverage", "percent_price filter limit",
    ))


def configure_maximum_usable_leverage(client: Any, plan: PairExecutionPlan) -> int:
    """Use the highest contract leverage that Aster accepts for this account."""
    candidates = [plan.leverage] + [x for x in (200, 150, 125, 100, 75, 50, 40, 30, 25, 20, 15, 10, 8, 5, 3, 2, 1) if x < plan.leverage]
    last_error: Exception | None = None
    for leverage in candidates:
        try:
            client.change_leverage(plan.symbol, leverage)
            return leverage
        except Exception as exc:
            if not is_definite_contract_rejection(exc):
                raise
            last_error = exc
    raise RuntimeError(f"{plan.symbol}: geen door Aster geaccepteerde leverage gevonden") from last_error


def _confirmed_fill(client: Any, intent_id: str, symbol: str, result: dict[str, Any]) -> dict[str, Any]:
    """Confirm dependent market-order steps from exchange truth.

    Aster can acknowledge a market order before its final fill is visible.  A
    follow-up OPEN/CLOSE is therefore forbidden while the first leg is still
    NEW/PARTIALLY_FILLED or has an unknown terminal state.
    """
    current = result
    status = str(current.get("status", "")).upper()
    if status in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}:
        if status != "FILLED":
            raise RuntimeError(f"Aster-order eindigde als {status}")
        return current
    query = getattr(client, "query_order", None)
    if query is None and not status:
        # Test adapters and older mocks return only an order id. Production
        # clients always expose query_order.
        return current
    if query is None:
        raise RuntimeError("Aster-orderfill kan niet worden bevestigd")
    current = query(symbol, intent_id)
    status = str(current.get("status", "")).upper()
    if status != "FILLED":
        raise RuntimeError(f"Aster-order is nog niet definitief gevuld ({status or 'ONBEKEND'})")
    return current


def plan_pair(symbol_row: dict[str, Any], bracket_rows: list[dict[str, Any]],
              price: float, notional_per_leg: float, maximum_oversize_ratio: float = .05) -> PairExecutionPlan:
    if price <= 0 or notional_per_leg <= 0:
        raise ValueError("Prijs en positieomvang moeten positief zijn")
    rules = ContractRules.from_exchange_info(symbol_row)
    step = rules.market_quantity_step
    requested = Decimal(str(notional_per_leg)) / Decimal(str(price))
    if step > 0:
        requested = (requested / step).to_integral_value(rounding=ROUND_UP) * step
    minimum = max(rules.market_min_quantity, rules.min_quantity)
    if rules.min_notional > 0 and step > 0:
        min_notional_quantity = (rules.min_notional / Decimal(str(price)) / step).to_integral_value(rounding=ROUND_UP) * step
        minimum = max(minimum, min_notional_quantity)
    quantity = rules.market_quantity(max(requested, minimum), Decimal(str(price)))
    actual_notional = quantity * Decimal(str(price))
    maximum_notional = Decimal(str(notional_per_leg)) * Decimal(str(1 + maximum_oversize_ratio))
    if actual_notional > maximum_notional:
        raise ValueError(
            f"{symbol_row.get('symbol', '')}: minimale exchangeorder {actual_notional} USD "
            f"overschrijdt ingesteld bedrag {notional_per_leg} USD"
        )
    brackets = [LeverageBracket.from_mapping(item) for item in bracket_rows]
    leverage = maximum_allowed_leverage(quantity * Decimal(str(price)), brackets)
    return PairExecutionPlan(str(symbol_row.get("symbol", "")).upper(), quantity,
                             actual_notional, leverage)


def execute_pair_once(client: Any, plan: PairExecutionPlan, *, id_prefix: str,
                      confirm: bool, risk_approved: Callable[[float], bool]) -> list[dict[str, Any]]:
    """Open LONG then SHORT. If SHORT fails, close LONG before returning error."""
    if not confirm:
        raise ValueError("Persoonlijke bevestiging ontbreekt")
    client.change_margin_type(plan.symbol, "CROSSED")
    leverage = configure_maximum_usable_leverage(client, plan)
    required_margin = float(plan.notional_per_leg) * 2 / max(1, leverage)
    if not risk_approved(required_margin):
        raise ValueError("Portfolio Risk Manager blokkeert deze pair")
    config = AsterAutomationConfig(enabled=True, mode="live")
    long_intent = AsterOrderIntent(client_order_id(id_prefix, "long"), plan.symbol, PositionSide.LONG, plan.quantity, "OPEN")
    long_result, recovered = client.submit_order_once(
        long_intent, config=config, confirm=True, hedge_mode_confirmed=True, risk_approved=True,
    )
    long_result = _confirmed_fill(client, long_intent.intent_id, plan.symbol, long_result)
    results = [{"side": "LONG", "result": long_result, "recovered": recovered, "leverage": leverage}]
    short_intent = AsterOrderIntent(client_order_id(id_prefix, "short"), plan.symbol, PositionSide.SHORT, plan.quantity, "OPEN")
    try:
        short_result, recovered = client.submit_order_once(
            short_intent, config=config, confirm=True, hedge_mode_confirmed=True, risk_approved=True,
        )
        short_result = _confirmed_fill(client, short_intent.intent_id, plan.symbol, short_result)
        results.append({"side": "SHORT", "result": short_result, "recovered": recovered, "leverage": leverage})
        return results
    except Exception as original:
        compensation = AsterOrderIntent(
            client_order_id(id_prefix, "undo", "long"), plan.symbol, PositionSide.LONG, plan.quantity, "CLOSE",
        )
        try:
            close_result, close_recovered = client.submit_order_once(
                compensation, config=config, confirm=True, hedge_mode_confirmed=True, risk_approved=True,
            )
        except Exception as compensation_error:
            raise RuntimeError("SHORT mislukte en LONG-compensatiesluiting is onzeker; noodcontrole vereist") from compensation_error
        raise RuntimeError(
            f"SHORT mislukte; LONG is direct gecompenseerd met order {close_result.get('orderId', '?')}"
        ) from original


def execute_leg_once(client: Any, plan: PairExecutionPlan, *, side: PositionSide,
                     action: str, id_prefix: str, confirm: bool) -> dict[str, Any]:
    if not confirm: raise ValueError("Persoonlijke bevestiging ontbreekt")
    # Aster stores margin/leverage per contract.  A freshly selected symbol can
    # therefore still carry an old or unsupported value.  Configure it before
    # every risk-increasing OPEN; a contract-specific rejection is safely
    # stepped down instead of stopping the complete Strategy-2 batch.
    accepted_leverage = plan.leverage
    if action.upper() == "OPEN":
        client.change_margin_type(plan.symbol, "CROSSED")
        accepted_leverage = configure_maximum_usable_leverage(client, plan)
    intent = AsterOrderIntent(client_order_id(id_prefix, action.lower(), side.value.lower()), plan.symbol,
                              side, plan.quantity, action)
    result, recovered = client.submit_order_once(
        intent, config=AsterAutomationConfig(enabled=True, mode="live"), confirm=True,
        hedge_mode_confirmed=True, risk_approved=True,
    )
    result = _confirmed_fill(client, intent.intent_id, plan.symbol, result)
    return {"side": side.value, "action": action, "result": result, "recovered": recovered,
            "leverage": accepted_leverage}


def execute_harvest_reset(client: Any, close_plan: PairExecutionPlan, reopen_plan: PairExecutionPlan,
                          *, side: PositionSide, opposite_plan: PairExecutionPlan,
                          id_prefix: str, confirm: bool) -> list[dict[str, Any]]:
    """Close a profitable leg, reopen it, or flatten the opposite leg if reset fails."""
    closed = execute_leg_once(client, close_plan, side=side, action="CLOSE",
                              id_prefix=f"{id_prefix}-harvest", confirm=confirm)
    try:
        reopened = execute_leg_once(client, reopen_plan, side=side, action="OPEN",
                                    id_prefix=f"{id_prefix}-reset", confirm=confirm)
        return [closed, reopened]
    except Exception as original:
        opposite = PositionSide.SHORT if side is PositionSide.LONG else PositionSide.LONG
        try:
            flattened = execute_leg_once(client, opposite_plan, side=opposite, action="CLOSE",
                                         id_prefix=f"{id_prefix}-failsafe", confirm=True)
        except Exception as failsafe:
            raise RuntimeError("Heropening en noodneutralisatie zijn onzeker; handmatige controle vereist") from failsafe
        raise RuntimeError(
            f"Heropening mislukte; overgebleven {opposite.value} is veilig gesloten "
            f"met order {flattened['result'].get('orderId', '?')}"
        ) from original


def execute_close_all(client: Any, plans: list[tuple[PairExecutionPlan, PositionSide]], *,
                      id_prefix: str, confirm: bool) -> list[dict[str, Any]]:
    if not confirm: raise ValueError("Tweede bevestiging voor Alles sluiten ontbreekt")
    results = []
    for index, (plan, side) in enumerate(plans, 1):
        results.append(execute_leg_once(client, plan, side=side, action="CLOSE",
                                        id_prefix=f"{id_prefix}-{index}", confirm=True))
    return results
