"""Auditable Aster Futures V3 domain layer.

The module intentionally performs no signing and sends no HTTP requests. It
defines the exact, validated payload contract that a later authenticated
adapter may consume after risk, Hedge Mode and idempotency gates have passed.
New Aster automation is OFF by default.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from enum import Enum
import re
import threading
import time
from typing import Any, Callable, Literal
from urllib.parse import urlencode

import httpx


ASTER_FUTURES_REST = "https://fapi.asterdex.com"
ASTER_FUTURES_WEBSOCKET = "wss://fstream.asterdex.com"
ASTER_API_VERSION = "v3"
CLIENT_ORDER_ID_PATTERN = re.compile(r"^[.A-Z:/a-z0-9_-]{1,36}$")


class AsterValidationError(ValueError):
    pass


class AsterSubmissionUncertain(RuntimeError):
    """The exchange may have accepted the request; never blind-retry it."""


class AsterApiError(RuntimeError):
    pass


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class AsterAutomationConfig:
    enabled: bool = False
    mode: Literal["paper", "live"] = "paper"
    hedge_mode_required: bool = True
    websocket_required: bool = True

    def can_submit_live(self) -> bool:
        return self.enabled and self.mode == "live"


@dataclass(frozen=True)
class ContractRules:
    symbol: str
    min_price: Decimal
    max_price: Decimal
    tick_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal
    quantity_step: Decimal
    market_min_quantity: Decimal
    market_max_quantity: Decimal
    market_quantity_step: Decimal
    min_notional: Decimal

    @classmethod
    def from_exchange_info(cls, symbol: dict[str, Any]) -> "ContractRules":
        filters = {
            str(item.get("filterType", "")): item
            for item in symbol.get("filters", ())
            if isinstance(item, dict)
        }
        price = filters.get("PRICE_FILTER", {})
        lot = filters.get("LOT_SIZE", {})
        market = filters.get("MARKET_LOT_SIZE", lot)
        notional = filters.get("MIN_NOTIONAL", {})
        return cls(
            symbol=str(symbol.get("symbol", "")).upper(),
            min_price=_decimal(price.get("minPrice", 0)),
            max_price=_decimal(price.get("maxPrice", 0)),
            tick_size=_decimal(price.get("tickSize", 0)),
            min_quantity=_decimal(lot.get("minQty", 0)),
            max_quantity=_decimal(lot.get("maxQty", 0)),
            quantity_step=_decimal(lot.get("stepSize", 0)),
            market_min_quantity=_decimal(market.get("minQty", lot.get("minQty", 0))),
            market_max_quantity=_decimal(market.get("maxQty", lot.get("maxQty", 0))),
            market_quantity_step=_decimal(market.get("stepSize", lot.get("stepSize", 0))),
            min_notional=_decimal(notional.get("notional", notional.get("minNotional", 0))),
        )

    def market_quantity(self, requested: Decimal | float | str, mark_price: Decimal | float | str) -> Decimal:
        quantity = _floor_step(_decimal(requested), self.market_quantity_step)
        price = _decimal(mark_price)
        if quantity <= 0 or price <= 0:
            raise AsterValidationError("Hoeveelheid en marktprijs moeten positief zijn")
        if self.market_min_quantity and quantity < self.market_min_quantity:
            raise AsterValidationError("Order ligt onder de minimale Aster-hoeveelheid")
        if self.market_max_quantity and quantity > self.market_max_quantity:
            raise AsterValidationError("Order ligt boven de maximale Aster-hoeveelheid")
        if self.min_notional and quantity * price < self.min_notional:
            raise AsterValidationError("Order ligt onder de minimale Aster-orderwaarde")
        return quantity


@dataclass(frozen=True)
class LeverageBracket:
    floor: Decimal
    cap: Decimal
    maximum_leverage: int
    maintenance_margin_ratio: Decimal

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "LeverageBracket":
        return cls(
            floor=_decimal(raw.get("notionalFloor", 0)),
            cap=_decimal(raw.get("notionalCap", 0)),
            maximum_leverage=int(raw.get("initialLeverage", 0)),
            maintenance_margin_ratio=_decimal(raw.get("maintMarginRatio", 0)),
        )


def maximum_allowed_leverage(notional: Decimal | float | str, brackets: list[LeverageBracket]) -> int:
    value = _decimal(notional)
    for bracket in sorted(brackets, key=lambda item: item.floor):
        if value >= bracket.floor and (bracket.cap <= 0 or value <= bracket.cap):
            return bracket.maximum_leverage
    raise AsterValidationError("Geen geldige Aster-leveragebracket voor deze orderwaarde")


@dataclass(frozen=True)
class AsterOrderIntent:
    intent_id: str
    symbol: str
    position_side: PositionSide
    quantity: Decimal
    action: Literal["OPEN", "CLOSE"]
    order_type: Literal["MARKET"] = "MARKET"

    def order_side(self) -> OrderSide:
        if self.position_side is PositionSide.LONG:
            return OrderSide.BUY if self.action == "OPEN" else OrderSide.SELL
        return OrderSide.SELL if self.action == "OPEN" else OrderSide.BUY

    def risk_increasing(self) -> bool:
        return self.action == "OPEN"


def build_hedge_order_payload(
    intent: AsterOrderIntent,
    *,
    hedge_mode_confirmed: bool,
    risk_approved: bool,
) -> dict[str, str]:
    if not hedge_mode_confirmed:
        raise AsterValidationError("Aster Hedge Mode is niet bevestigd")
    if intent.risk_increasing() and not risk_approved:
        raise AsterValidationError("Portfolio Risk Manager heeft de order niet goedgekeurd")
    if not CLIENT_ORDER_ID_PATTERN.fullmatch(intent.intent_id):
        raise AsterValidationError("Ongeldige of te lange idempotency-id")
    if not intent.symbol or intent.quantity <= 0:
        raise AsterValidationError("Symbool en hoeveelheid zijn verplicht")
    # Aster V3 requires positionSide in Hedge Mode and explicitly forbids
    # reduceOnly there. Direction plus positionSide makes a partial close
    # unambiguous without sending reduceOnly.
    return {
        "symbol": intent.symbol.upper(),
        "side": intent.order_side().value,
        "positionSide": intent.position_side.value,
        "type": intent.order_type,
        "quantity": _plain(intent.quantity),
        "newClientOrderId": intent.intent_id,
    }


def classify_submission(status_code: int, payload: dict[str, Any] | None) -> str:
    """Classify one submission response without deciding to retry it."""
    if status_code == 503:
        raise AsterSubmissionUncertain(
            "Aster gaf 503; orderstatus is onbekend en moet via orderquery/stream worden hersteld"
        )
    if 200 <= status_code < 300 and isinstance(payload, dict) and payload.get("orderId") is not None:
        return "accepted"
    if status_code in {408, 429} or status_code >= 500:
        return "retryable-before-submit-only"
    return "rejected"


def stream_event_is_newer(last_event_time: int, event: dict[str, Any]) -> bool:
    """Aster says user-stream payloads can arrive out of order; order on E."""
    try:
        return int(event.get("E", 0)) > int(last_event_time)
    except (TypeError, ValueError):
        return False


class MonotonicNonce:
    """Thread-safe microsecond nonce as required by Aster V3."""

    def __init__(self, clock_microseconds: Callable[[], int] | None = None) -> None:
        self._clock = clock_microseconds or (lambda: time.time_ns() // 1_000)
        self._last = 0
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            candidate = int(self._clock())
            self._last = max(candidate, self._last + 1)
            return self._last


class AsterV3Client:
    """Injectable V3 transport; live order submission is disabled by default.

    ``sign_message`` receives the exact URL-encoded parameter string that will
    be sent and must return its EIP-712 signature. Credential storage and the
    signer implementation live outside this class (Secret Manager boundary).
    """

    def __init__(
        self,
        *,
        signer_address: str,
        sign_message: Callable[[str], str],
        transport: httpx.BaseTransport | None = None,
        nonce: MonotonicNonce | None = None,
        live_authorized: bool = False,
    ) -> None:
        self._signer_address = signer_address
        self._sign_message = sign_message
        self._nonce = nonce or MonotonicNonce()
        self._live_authorized = live_authorized
        self._http = httpx.Client(base_url=ASTER_FUTURES_REST, timeout=15.0, transport=transport)

    def public_exchange_info(self) -> dict[str, Any]:
        try:
            response = self._http.get("/fapi/v3/exchangeInfo")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AsterApiError("Aster exchangeInfo kon niet betrouwbaar worden gelezen") from exc
        if not isinstance(payload, dict):
            raise AsterApiError("Aster exchangeInfo heeft een ongeldig formaat")
        return payload

    def ticker_prices(self) -> list[dict[str, Any]]:
        """Read current public prices without signing or trading."""
        try:
            response = self._http.get("/fapi/v3/ticker/price")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AsterApiError("Aster-prijzen konden niet betrouwbaar worden gelezen") from exc
        if isinstance(payload, dict):
            return [payload]
        if not isinstance(payload, list):
            raise AsterApiError("Aster-prijzen hebben een ongeldig formaat")
        return [item for item in payload if isinstance(item, dict)]

    def ticker_24h(self) -> list[dict[str, Any]]:
        try:
            response = self._http.get("/fapi/v3/ticker/24hr")
            response.raise_for_status(); payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AsterApiError("Aster 24-uursmarktdata kon niet betrouwbaar worden gelezen") from exc
        if isinstance(payload, dict): return [payload]
        if not isinstance(payload, list): raise AsterApiError("Aster 24-uursmarktdata heeft een ongeldig formaat")
        return [item for item in payload if isinstance(item, dict)]

    def signed_request(self, method: str, path: str, parameters: dict[str, Any] | None = None) -> Any:
        values = dict(parameters or {})
        values["nonce"] = str(self._nonce.next())
        values["signer"] = self._signer_address
        encoded = urlencode([(key, str(value)) for key, value in values.items()])
        signature = self._sign_message(encoded)
        signed = f"{encoded}&signature={signature}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            if method.upper() == "GET":
                response = self._http.get(f"{path}?{signed}", headers=headers)
            else:
                response = self._http.request(method.upper(), path, content=signed.encode(), headers=headers)
        except httpx.HTTPError as exc:
            raise AsterApiError("Aster is tijdelijk niet bereikbaar") from exc
        if response.status_code == 503:
            raise AsterSubmissionUncertain(
                "Aster gaf 503; uitvoeringsstatus moet via orderquery/stream worden hersteld"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AsterApiError("Aster gaf geen geldig JSON-antwoord") from exc
        if response.status_code >= 400:
            code = payload.get("code", response.status_code) if isinstance(payload, dict) else response.status_code
            message = payload.get("msg", "Aster-request afgewezen") if isinstance(payload, dict) else "Aster-request afgewezen"
            raise AsterApiError(f"Aster {code}: {message}")
        return payload

    def position_mode(self) -> bool:
        payload = self.signed_request("GET", "/fapi/v3/positionSide/dual")
        return bool(payload.get("dualSidePosition")) if isinstance(payload, dict) else False

    def position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        payload = self.signed_request("GET", "/fapi/v3/positionRisk", {"symbol": symbol} if symbol else {})
        return payload if isinstance(payload, list) else []

    def account_balance(self) -> list[dict[str, Any]]:
        payload = self.signed_request("GET", "/fapi/v3/balance")
        return payload if isinstance(payload, list) else []

    def account_information(self) -> dict[str, Any]:
        """Return Aster's authoritative joined-margin account totals."""
        payload = self.signed_request("GET", "/fapi/v3/accountWithJoinMargin")
        return payload if isinstance(payload, dict) else {}

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        payload = self.signed_request(
            "GET", "/fapi/v3/openOrders", {"symbol": symbol} if symbol else {},
        )
        return payload if isinstance(payload, list) else []

    def all_orders(
        self, symbol: str, *, start_time: int | None = None,
        end_time: int | None = None, limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Read authoritative order history; this method never submits an order."""
        if not 1 <= limit <= 1000:
            raise AsterValidationError("Orderhistorie-limit moet tussen 1 en 1000 liggen")
        params: dict[str, Any] = {"symbol": symbol.upper(), "limit": limit}
        if start_time is not None: params["startTime"] = int(start_time)
        if end_time is not None: params["endTime"] = int(end_time)
        payload = self.signed_request("GET", "/fapi/v3/allOrders", params)
        return payload if isinstance(payload, list) else []

    def user_trades(
        self, symbol: str, *, start_time: int | None = None,
        end_time: int | None = None, from_id: int | None = None, limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Read actual fills, including commission and realised PnL."""
        if not 1 <= limit <= 1000:
            raise AsterValidationError("Fillhistorie-limit moet tussen 1 en 1000 liggen")
        if from_id is not None and (start_time is not None or end_time is not None):
            raise AsterValidationError("fromId kan niet met een tijdvenster worden gecombineerd")
        params: dict[str, Any] = {"symbol": symbol.upper(), "limit": limit}
        if start_time is not None: params["startTime"] = int(start_time)
        if end_time is not None: params["endTime"] = int(end_time)
        if from_id is not None: params["fromId"] = int(from_id)
        payload = self.signed_request("GET", "/fapi/v3/userTrades", params)
        if not isinstance(payload, list):
            raise AsterApiError("Aster-fillhistorie heeft een ongeldig formaat")
        if any(not isinstance(row, dict) for row in payload):
            raise AsterApiError("Aster-fillhistorie bevat een ongeldig record")
        return list(payload)

    def income_history(
        self, *, symbol: str | None = None, income_type: str | None = None,
        start_time: int | None = None, end_time: int | None = None, limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Read funding, commission, realised PnL and transfer records."""
        if not 1 <= limit <= 1000:
            raise AsterValidationError("Inkomstenhistorie-limit moet tussen 1 en 1000 liggen")
        params: dict[str, Any] = {"limit": limit}
        if symbol: params["symbol"] = symbol.upper()
        if income_type: params["incomeType"] = income_type.upper()
        if start_time is not None: params["startTime"] = int(start_time)
        if end_time is not None: params["endTime"] = int(end_time)
        payload = self.signed_request("GET", "/fapi/v3/income", params)
        if not isinstance(payload, list):
            raise AsterApiError("Aster-inkomstenhistorie heeft een ongeldig formaat")
        if any(not isinstance(row, dict) for row in payload):
            raise AsterApiError("Aster-inkomstenhistorie bevat een ongeldig record")
        return list(payload)

    def leverage_brackets(self, symbol: str | None = None) -> list[dict[str, Any]]:
        payload = self.signed_request(
            "GET", "/fapi/v3/leverageBracket", {"symbol": symbol} if symbol else {},
        )
        if isinstance(payload, list):
            return payload
        return [payload] if isinstance(payload, dict) else []

    def change_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        if leverage < 1:
            raise AsterValidationError("Aster-leverage moet positief zijn")
        payload = self.signed_request("POST", "/fapi/v3/leverage", {
            "symbol": symbol.upper(), "leverage": int(leverage),
        })
        return payload if isinstance(payload, dict) else {}

    def change_margin_type(self, symbol: str, margin_type: str = "CROSSED") -> dict[str, Any]:
        value = margin_type.upper()
        if value not in {"ISOLATED", "CROSSED"}:
            raise AsterValidationError("Ongeldig Aster-margetype")
        try:
            payload = self.signed_request("POST", "/fapi/v3/marginType", {
                "symbol": symbol.upper(), "marginType": value,
            })
        except AsterApiError as exc:
            if "No need to change margin type" in str(exc) or "-4046" in str(exc):
                return {"marginType": value, "unchanged": True}
            raise
        return payload if isinstance(payload, dict) else {}

    def query_order(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        payload = self.signed_request("GET", "/fapi/v3/order", {
            "symbol": symbol.upper(), "origClientOrderId": client_order_id,
        })
        return payload if isinstance(payload, dict) else {}

    def submit_order_once(
        self,
        intent: AsterOrderIntent,
        *,
        config: AsterAutomationConfig,
        confirm: bool,
        hedge_mode_confirmed: bool,
        risk_approved: bool,
    ) -> tuple[dict[str, Any], bool]:
        if not self._live_authorized or not config.can_submit_live() or not confirm:
            raise AsterValidationError("Aster live-uitvoering is niet expliciet geautoriseerd")
        payload = build_hedge_order_payload(
            intent, hedge_mode_confirmed=hedge_mode_confirmed, risk_approved=risk_approved,
        )
        try:
            response = self.signed_request("POST", "/fapi/v3/order", payload)
            if not isinstance(response, dict) or response.get("orderId") is None:
                raise AsterApiError("Aster bevestigde geen order-id")
            return response, False
        except AsterSubmissionUncertain as original:
            # One read-only recovery attempt; crucially there is no second POST.
            try:
                recovered = self.query_order(intent.symbol, intent.intent_id)
            except AsterApiError:
                recovered = {}
            if recovered.get("orderId") is not None:
                return recovered, True
            raise AsterSubmissionUncertain(
                "Aster-order blijft onzeker; blokkeren tot user-stream/reconciliation duidelijkheid geeft"
            ) from original


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AsterValidationError("Ongeldig numeriek Aster-veld") from exc
    if not result.is_finite():
        raise AsterValidationError("Niet-eindig numeriek Aster-veld")
    return result


def _floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _plain(value: Decimal) -> str:
    return format(value, "f")
