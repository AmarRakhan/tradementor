"""Transactional Aster pair execution with compensation on half-open hedges."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Callable

from aster_gateway import (
    AsterAutomationConfig, AsterOrderIntent, ContractRules, LeverageBracket,
    PositionSide, maximum_allowed_leverage,
)
from aster_close_guard import CloseEvidence, require_profitable_automatic_close


class NewPositionLeverageBlocked(ValueError):
    """Fail-closed, candidate-local rejection before an OPEN reaches Aster."""

    def __init__(self, reason_code: str, symbol: str):
        self.reason_code = reason_code
        self.symbol = symbol.upper()
        super().__init__(f"{self.symbol}: {reason_code}")


@dataclass(frozen=True)
class PairExecutionPlan:
    symbol: str
    quantity: Decimal
    notional_per_leg: Decimal
    leverage: int
    tick_size: Decimal = Decimal("0")
    quantity_step: Decimal = Decimal("0")
    minimum_quantity: Decimal = Decimal("0")
    minimum_notional: Decimal = Decimal("0")
    maximum_notional: Decimal = Decimal("0")


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


def require_exact_new_position_leverage(client: Any, plan: PairExecutionPlan,
                                        configured_leverage: int) -> int:
    """Set and verify the exact configured leverage for one brand-new S2 leg.

    The private bracket read and setter are account scoped.  No synthetic
    bracket, lower fallback or order submission is allowed from this guard.
    """
    try:
        requested = int(configured_leverage)
    except (TypeError, ValueError) as exc:
        raise NewPositionLeverageBlocked("CONFIGURED_LEVERAGE_OUT_OF_RANGE", plan.symbol) from exc
    if requested < 1 or requested > 200:
        raise NewPositionLeverageBlocked("CONFIGURED_LEVERAGE_OUT_OF_RANGE", plan.symbol)
    try:
        rows = contract_brackets(client, [], plan.symbol)
        brackets = [LeverageBracket.from_mapping(row) for row in rows]
        maximum = maximum_allowed_leverage(plan.notional_per_leg, brackets)
    except Exception as exc:
        raise NewPositionLeverageBlocked("SYMBOL_LEVERAGE_DATA_UNAVAILABLE", plan.symbol) from exc
    if maximum < requested:
        raise NewPositionLeverageBlocked("SYMBOL_MAX_LEVERAGE_BELOW_CONFIGURED", plan.symbol)
    try:
        position_rows = client.position_risk(plan.symbol)
        if not isinstance(position_rows, list) or any(not isinstance(row, dict) for row in position_rows):
            raise ValueError("invalid position-risk response")
        active_rows = [row for row in position_rows
            if str(row.get("symbol", "")).upper() == plan.symbol.upper()
            and abs(float(row.get("positionAmt", 0))) > 0]
        active_leverages = {int(row.get("leverage")) for row in active_rows}
    except Exception as exc:
        raise NewPositionLeverageBlocked("SYMBOL_LEVERAGE_DATA_UNAVAILABLE", plan.symbol) from exc
    if active_rows:
        if active_leverages != {requested}:
            raise NewPositionLeverageBlocked("SYMBOL_LEVERAGE_VERIFICATION_FAILED", plan.symbol)
        # Aster leverage is contract-wide. Never rewrite it underneath an
        # existing leg; reliable exchange truth already proves the exact value.
        return requested
    try:
        response = client.change_leverage(plan.symbol, requested)
    except Exception as exc:
        raise NewPositionLeverageBlocked("SYMBOL_LEVERAGE_SET_FAILED", plan.symbol) from exc
    try:
        applied = int(response.get("leverage"))
        response_symbol = str(response.get("symbol", plan.symbol)).upper()
    except (AttributeError, TypeError, ValueError) as exc:
        raise NewPositionLeverageBlocked("SYMBOL_LEVERAGE_VERIFICATION_FAILED", plan.symbol) from exc
    if applied != requested or response_symbol != plan.symbol.upper():
        raise NewPositionLeverageBlocked("SYMBOL_LEVERAGE_VERIFICATION_FAILED", plan.symbol)
    return requested


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


def maximum_notional_for_leverage(brackets: list[LeverageBracket], leverage: int) -> Decimal:
    """Largest contract notional whose bracket accepts ``leverage``.

    A zero cap is Aster's unbounded final bracket and is preserved as zero.
    """
    eligible = [row.cap for row in brackets if row.maximum_leverage >= leverage]
    if not eligible:
        return Decimal("-1")
    if any(cap <= 0 for cap in eligible):
        return Decimal("0")
    return max(eligible)


def plan_pair(symbol_row: dict[str, Any], bracket_rows: list[dict[str, Any]],
              price: float, notional_per_leg: float, *, accepted_leverage: int | None = None,
              existing_contract_notional: float | Decimal = 0) -> PairExecutionPlan:
    if price <= 0 or notional_per_leg <= 0:
        raise ValueError("Prijs en positieomvang moeten positief zijn")
    rules = ContractRules.from_exchange_info(symbol_row)
    step = rules.market_quantity_step
    configured_notional = Decimal(str(notional_per_leg))
    market_price = Decimal(str(price))
    requested = configured_notional / market_price
    if step > 0:
        requested = (requested / step).to_integral_value(rounding=ROUND_DOWN) * step
    minimum = max(rules.market_min_quantity, rules.min_quantity)
    if step > 0:
        minimum = (minimum / step).to_integral_value(rounding=ROUND_UP) * step
    if rules.min_notional > 0 and step > 0:
        min_notional_quantity = (rules.min_notional / market_price / step).to_integral_value(rounding=ROUND_UP) * step
        minimum = max(minimum, min_notional_quantity)
    minimum_executable_notional = minimum * market_price
    if minimum_executable_notional > configured_notional:
        raise ValueError(
            f"{symbol_row.get('symbol', '')}: minimale exchangeorder {minimum_executable_notional} USD "
            f"overschrijdt ingesteld bedrag {notional_per_leg} USD"
        )
    quantity = rules.market_quantity(max(requested, minimum), market_price)
    actual_notional = quantity * market_price
    if actual_notional > configured_notional:
        raise ValueError(f"{rules.symbol}: uitvoerbare order {actual_notional} USD overschrijdt ingesteld bedrag {notional_per_leg} USD")
    brackets = [LeverageBracket.from_mapping(item) for item in bracket_rows]
    leverage = accepted_leverage or maximum_allowed_leverage(actual_notional, brackets)
    maximum_notional = maximum_notional_for_leverage(brackets, leverage)
    total_notional = abs(Decimal(str(existing_contract_notional))) + actual_notional
    if maximum_notional < 0 or (maximum_notional > 0 and total_notional > maximum_notional):
        raise ValueError(
            f"{rules.symbol}: contractcapaciteit {maximum_notional} USD bij {leverage}x is lager "
            f"dan totale geplande notional {total_notional} USD"
        )
    return PairExecutionPlan(str(symbol_row.get("symbol", "")).upper(), quantity,
                             actual_notional, leverage, rules.tick_size, step, minimum,
                             rules.min_notional, maximum_notional)


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
        raise RuntimeError(
            "SHORT mislukte; LONG blijft open omdat automatische compensatiesluiting zonder bewezen nettowinst verboden is"
        ) from original


def execute_leg_once(client: Any, plan: PairExecutionPlan, *, side: PositionSide,
                     action: str, id_prefix: str, confirm: bool,
                     close_evidence: CloseEvidence | None = None,
                     close_audit: Callable[[dict[str, Any]], None] | None = None,
                     manual_loss_confirmation: bool = False,
                     before_submit: Callable[[AsterOrderIntent], None] | None = None,
                     new_position_leverage: int | None = None) -> dict[str, Any]:
    if not confirm: raise ValueError("Persoonlijke bevestiging ontbreekt")
    # Aster stores margin/leverage per contract.  A freshly selected symbol can
    # therefore still carry an old or unsupported value.  Configure it before
    # every risk-increasing OPEN; a contract-specific rejection is safely
    # stepped down instead of stopping the complete Strategy-2 batch.
    accepted_leverage = plan.leverage
    if action.upper() == "CLOSE" and not manual_loss_confirmation:
        require_profitable_automatic_close(close_evidence, audit=close_audit)
    if action.upper() == "OPEN":
        client.change_margin_type(plan.symbol, "CROSSED")
        accepted_leverage = (require_exact_new_position_leverage(client, plan, new_position_leverage)
            if new_position_leverage is not None else configure_maximum_usable_leverage(client, plan))
    intent = AsterOrderIntent(client_order_id(id_prefix, action.lower(), side.value.lower()), plan.symbol,
                              side, plan.quantity, action)
    if before_submit is not None:
        before_submit(intent)
    result, recovered = client.submit_order_once(
        intent, config=AsterAutomationConfig(enabled=True, mode="live"), confirm=True,
        hedge_mode_confirmed=True, risk_approved=True,
    )
    result = _confirmed_fill(client, intent.intent_id, plan.symbol, result)
    return {"side": side.value, "action": action, "result": result, "recovered": recovered,
            "leverage": accepted_leverage}


def execute_harvest_reset(client: Any, close_plan: PairExecutionPlan, reopen_plan: PairExecutionPlan,
                          *, side: PositionSide, opposite_plan: PairExecutionPlan,
                          id_prefix: str, confirm: bool, close_evidence: CloseEvidence | None = None,
                          close_audit: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Close a profitable leg, reopen it, or flatten the opposite leg if reset fails."""
    closed = execute_leg_once(client, close_plan, side=side, action="CLOSE",
                              id_prefix=f"{id_prefix}-harvest", confirm=confirm,
                              close_evidence=close_evidence, close_audit=close_audit)
    try:
        reopened = execute_leg_once(client, reopen_plan, side=side, action="OPEN",
                                    id_prefix=f"{id_prefix}-reset", confirm=confirm)
        return [closed, reopened]
    except Exception as original:
        raise RuntimeError("Heropening mislukte; tegenhanger blijft open omdat verlieslatende noodneutralisatie verboden is") from original


def execute_close_all(client: Any, plans: list[tuple[PairExecutionPlan, PositionSide]], *,
                      id_prefix: str, confirm: bool,
                      explicit_loss_confirmation: bool = False) -> list[dict[str, Any]]:
    if not confirm or not explicit_loss_confirmation:
        raise ValueError("Aparte expliciete bevestiging voor mogelijk verlieslatend Alles sluiten ontbreekt")
    results = []
    for index, (plan, side) in enumerate(plans, 1):
        results.append(execute_leg_once(client, plan, side=side, action="CLOSE",
                                        id_prefix=f"{id_prefix}-{index}", confirm=True,
                                        manual_loss_confirmation=True))
    return results
