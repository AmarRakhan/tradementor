"""Small, auditable MEXC Futures REST adapter.

Credentials are supplied by the caller and are never logged or included in
exceptions.  Order submission intentionally lives behind an explicit flag in
the cloud API; this module is safe to unit-test with a mock transport.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import math
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode

import httpx


BASE_URL = "https://api.mexc.com"


class MexcApiError(RuntimeError):
    pass


class MexcCanaryUncertain(MexcApiError):
    """Submission may have reached MEXC; callers must not retry automatically."""


def canary_existing_action(status: str | None) -> str:
    if status in {"accepted", "filled", "pending"}:
        return "replay"
    if status == "uncertain":
        return "block"
    return "proceed"


@dataclass(frozen=True)
class MexcCredentials:
    api_key: str
    secret_key: str


def query_string(parameters: dict[str, Any] | None) -> str:
    cleaned = {key: value for key, value in (parameters or {}).items() if value is not None}
    return urlencode(sorted(cleaned.items()), doseq=True)


def signature(credentials: MexcCredentials, timestamp_ms: int, parameter_string: str) -> str:
    target = f"{credentials.api_key}{timestamp_ms}{parameter_string}".encode("utf-8")
    return hmac.new(credentials.secret_key.encode("utf-8"), target, hashlib.sha256).hexdigest()


class MexcClient:
    def __init__(
        self,
        credentials: MexcCredentials,
        *,
        transport: httpx.BaseTransport | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.credentials = credentials
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.http = httpx.Client(base_url=BASE_URL, timeout=15.0, transport=transport)

    def _private(self, method: str, path: str, parameters: dict[str, Any] | None = None) -> Any:
        method = method.upper()
        timestamp = self.clock_ms()
        if method in {"GET", "DELETE"}:
            parameter_string = query_string(parameters)
            request_kwargs: dict[str, Any] = {"params": parameters or {}}
        else:
            # Compact JSON is also the exact byte-equivalent string MEXC signs.
            parameter_string = json.dumps(parameters or {}, separators=(",", ":"), ensure_ascii=False)
            request_kwargs = {"content": parameter_string.encode("utf-8")}
        headers = {
            "ApiKey": self.credentials.api_key,
            "Request-Time": str(timestamp),
            "Signature": signature(self.credentials, timestamp, parameter_string),
            "Recv-Window": "15",
            "Content-Type": "application/json",
            "Language": "en-US",
        }
        try:
            response = self.http.request(method, path, headers=headers, **request_kwargs)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MexcApiError("MEXC is tijdelijk niet bereikbaar") from exc
        if not isinstance(payload, dict) or payload.get("success") is not True:
            code = payload.get("code", "unknown") if isinstance(payload, dict) else "invalid"
            message = payload.get("message", "MEXC-controle mislukt") if isinstance(payload, dict) else "MEXC-controle mislukt"
            raise MexcApiError(f"MEXC {code}: {message}")
        return payload.get("data")

    def assets(self) -> list[dict[str, Any]]:
        data = self._private("GET", "/api/v1/private/account/assets")
        return data if isinstance(data, list) else []

    def open_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        data = self._private("GET", "/api/v1/private/position/open_positions", {"symbol": symbol})
        return data if isinstance(data, list) else []

    def open_orders(self, symbol: str = "BTC_USDT") -> list[dict[str, Any]]:
        data = self._private("GET", f"/api/v1/private/order/list/open_orders/{symbol}")
        return data if isinstance(data, list) else []

    def cancel_all_orders(self, symbol: str = "BTC_USDT") -> bool:
        """Cancel every unfilled order for one Futures contract."""
        self._private("POST", "/api/v1/private/order/cancel_all", {"symbol": symbol})
        return True

    def position_mode(self) -> int:
        data = self._private("GET", "/api/v1/private/position/position_mode")
        if isinstance(data, (int, float, str)):
            return int(data)
        if isinstance(data, dict) and "positionMode" in data:
            return int(data["positionMode"])
        if isinstance(data, list) and data and isinstance(data[0], dict) and "positionMode" in data[0]:
            return int(data[0]["positionMode"])
        raise MexcApiError("MEXC gaf geen herkenbare position mode terug")

    def fee_details(self, symbol: str = "BTC_USDT") -> dict[str, Any]:
        data = self._private("GET", "/api/v1/private/account/tiered_fee_rate/v2", {"symbol": symbol})
        return data if isinstance(data, dict) else {}

    def leverage_details(self, symbol: str = "BTC_USDT") -> list[dict[str, Any]]:
        data = self._private("GET", "/api/v1/private/position/leverage", {"symbol": symbol})
        return data if isinstance(data, list) else []

    def change_leverage(
        self,
        *,
        leverage: int = 200,
        position_id: int | None = None,
        symbol: str = "BTC_USDT",
        position_type: int = 1,
        open_type: int = 2,
    ) -> bool:
        payload: dict[str, Any] = {"leverage": leverage}
        if position_id is not None:
            payload["positionId"] = position_id
        else:
            payload.update({"openType": open_type, "symbol": symbol, "positionType": position_type})
        self._private("POST", "/api/v1/private/position/change_leverage", payload)
        return True

    def public(self, path: str, parameters: dict[str, Any] | None = None) -> Any:
        try:
            response = self.http.get(path, params=parameters or {})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MexcApiError("MEXC-marktdata is tijdelijk niet bereikbaar") from exc
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise MexcApiError("MEXC gaf geen geldige marktdata terug")
        return payload.get("data")

    def contract_detail(self, symbol: str = "BTC_USDT") -> dict[str, Any]:
        data = self.public("/api/v1/contract/detail", {"symbol": symbol})
        return data if isinstance(data, dict) else {}

    def ticker(self, symbol: str = "BTC_USDT") -> dict[str, Any]:
        data = self.public("/api/v1/contract/ticker", {"symbol": symbol})
        return data if isinstance(data, dict) else {}

    def candles(self, symbol: str, timeframe: str, count: int = 60) -> list[dict[str, float]]:
        intervals = {"1m": ("Min1", 60), "3m": ("Min1", 60), "5m": ("Min5", 300), "15m": ("Min15", 900), "30m": ("Min30", 1800), "1h": ("Min60", 3600), "4h": ("Hour4", 14400)}
        if timeframe not in intervals:
            raise MexcApiError("Niet-ondersteund MEXC-timeframe")
        interval, seconds = intervals[timeframe]
        requested = min(count * 3 if timeframe == "3m" else count, 1900)
        end = int(time.time())
        data = self.public(f"/api/v1/contract/kline/{symbol}", {"interval": interval, "start": end - seconds * requested, "end": end})
        if not isinstance(data, dict):
            raise MexcApiError("MEXC gaf geen candledata terug")
        names = ("time", "open", "high", "low", "close", "vol")
        if any(not isinstance(data.get(name), list) for name in names):
            raise MexcApiError("MEXC candledata is onvolledig")
        size = min(len(data[name]) for name in names)
        raw = [{"time": int(data["time"][i]), "open": safe_float(data["open"][i]), "high": safe_float(data["high"][i]), "low": safe_float(data["low"][i]), "close": safe_float(data["close"][i]), "volume": safe_float(data["vol"][i])} for i in range(size)]
        now = int(time.time())
        raw = [item for item in raw if item["time"] + seconds <= now]
        if timeframe != "3m":
            return raw[-count:]
        grouped: list[dict[str, float]] = []
        buckets: dict[int, list[dict[str, float]]] = {}
        for item in raw:
            buckets.setdefault((int(item["time"]) // 180) * 180, []).append(item)
        for bucket in sorted(buckets):
            group = sorted(buckets[bucket], key=lambda item: item["time"])
            if len(group) != 3 or bucket + 180 > now:
                continue
            grouped.append({"time": group[0]["time"], "open": group[0]["open"], "high": max(item["high"] for item in group), "low": min(item["low"] for item in group), "close": group[-1]["close"], "volume": sum(item["volume"] for item in group)})
        return grouped[-count:]

    def place_market_order(
        self,
        *,
        symbol: str,
        volume: float,
        side: int,
        leverage: int,
        external_oid: str,
        open_type: int = 1,
        position_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "price": 0,
            "vol": volume,
            "leverage": leverage,
            "side": side,
            "type": 5,
            "openType": open_type,
            "externalOid": external_oid,
            "positionMode": 1,
        }
        if position_id is not None:
            payload["positionId"] = position_id
        data = self._private("POST", "/api/v1/private/order/create", payload)
        return data if isinstance(data, dict) else {"orderId": str(data)}

    def order_by_external_id(self, symbol: str, external_oid: str) -> dict[str, Any]:
        data = self._private("GET", f"/api/v1/private/order/external/{symbol}/{external_oid}")
        return data if isinstance(data, dict) else {}


def place_canary_once(
    client: MexcClient,
    *,
    symbol: str,
    volume: float,
    external_oid: str,
    leverage: int = 200,
    open_type: int = 2,
) -> tuple[dict[str, Any], bool]:
    """Submit once; recover by external id after an ambiguous transport/API error."""
    try:
        return client.place_market_order(
            symbol=symbol,
            volume=volume,
            side=1,
            leverage=leverage,
            external_oid=external_oid,
            open_type=open_type,
        ), False
    except MexcApiError as original:
        try:
            recovered = client.order_by_external_id(symbol, external_oid)
        except MexcApiError:
            recovered = {}
        if str(recovered.get("orderId", "")):
            return recovered, True
        raise MexcCanaryUncertain(
            "Canarystatus is onzeker; er wordt niet automatisch opnieuw besteld"
        ) from original


def place_order_once(
    client: MexcClient,
    *,
    symbol: str,
    volume: float,
    side: int,
    external_oid: str,
    position_id: int | None = None,
) -> tuple[dict[str, Any], bool]:
    """Idempotent Cross 200x order submission for every automation leg."""
    try:
        return client.place_market_order(
            symbol=symbol, volume=volume, side=side, leverage=200,
            external_oid=external_oid, open_type=2, position_id=position_id,
        ), False
    except MexcApiError as original:
        try:
            recovered = client.order_by_external_id(symbol, external_oid)
        except MexcApiError:
            recovered = {}
        if str(recovered.get("orderId", "")):
            return recovered, True
        raise MexcCanaryUncertain(
            "Orderstatus is onzeker; automatisering is gepauzeerd zonder retry"
        ) from original


def usdt_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((item for item in assets if str(item.get("currency", "")).upper() == "USDT"), None)


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def volume_for_notional(max_notional: float, price: float, contract: dict[str, Any]) -> tuple[float, float]:
    contract_size = safe_float(contract.get("contractSize"))
    minimum_volume = safe_float(contract.get("minVol"))
    volume_step = safe_float(contract.get("volUnit")) or 1.0
    if max_notional <= 0 or price <= 0 or contract_size <= 0 or minimum_volume <= 0:
        raise MexcApiError("MEXC-contractgrenzen zijn ongeldig")
    raw = max_notional / (price * contract_size)
    volume = math.floor(raw / volume_step) * volume_step
    if volume + 1e-12 < minimum_volume:
        raise MexcApiError("De bevestigde canarylimiet ligt onder het actuele MEXC-minimum")
    actual_notional = volume * contract_size * price
    if actual_notional > max_notional + 1e-8:
        raise MexcApiError("Canaryvolume overschrijdt de bevestigde limiet")
    return volume, actual_notional


def normalized_positions(
    positions: list[dict[str, Any]],
    *,
    mark_price: float,
    contract: dict[str, Any],
    account_equity: float = 0.0,
) -> list[dict[str, Any]]:
    """Convert MEXC position payload variants into a stable app contract."""
    contract_size = safe_float(contract.get("contractSize"))
    liquidation_fee_rate = safe_float(contract.get("liquidationFeeRate"))
    default_mmr = safe_float(contract.get("maintenanceMarginRate"))
    risk_tiers = contract.get("riskLimitCustom") if isinstance(contract.get("riskLimitCustom"), list) else []
    normalized: list[dict[str, Any]] = []
    for row in positions:
        volume = abs(safe_float(row.get("holdVol", row.get("volume", row.get("vol")))))
        if volume <= 0:
            continue
        leverage = max(1, int(safe_float(row.get("leverage")) or 1))
        entry = safe_float(row.get("holdAvgPrice", row.get("openAvgPrice", row.get("newOpenAvgPrice"))))
        current = safe_float(row.get("fairPrice", row.get("markPrice"))) or mark_price
        notional = volume * contract_size * current
        margin = safe_float(row.get("im", row.get("positionMargin"))) or (notional / leverage if leverage else 0.0)
        position_type = int(safe_float(row.get("positionType")))
        tier = next((item for item in risk_tiers if volume <= safe_float(item.get("maxVol"))), None)
        maintenance_rate = safe_float((tier or {}).get("mmr")) or default_mmr
        if any(key in row for key in ("unrealised", "unrealized", "unrealizedPnl")):
            unrealized = safe_float(row.get("unrealised", row.get("unrealized", row.get("unrealizedPnl"))))
        else:
            price_move = (current - entry) * volume * contract_size
            unrealized = price_move if position_type == 1 else -price_move
        maintenance_margin = notional * maintenance_rate
        liquidation_fee = notional * liquidation_fee_rate
        isolated = int(safe_float(row.get("openType"))) == 1
        # In Cross mode MEXC backs the position with the shared Futures equity.
        # Using only the position's initial margin here would incorrectly apply
        # an Isolated liquidation model to a Cross position.
        margin_balance = (margin + unrealized) if isolated else (account_equity or (margin + unrealized))
        margin_ratio = ((maintenance_margin + liquidation_fee) / margin_balance * 100.0) if margin_balance > 0 else 100.0
        normalized.append({
            "positionId": str(row.get("positionId", "")),
            "symbol": str(row.get("symbol", "BTC_USDT")),
            "side": "long" if position_type == 1 else "short",
            "isolated": isolated,
            "volume": volume,
            "contractSize": contract_size,
            "entryPrice": entry,
            "markPrice": current,
            "notionalUsd": notional,
            "marginUsd": margin,
            "unrealizedPnl": unrealized,
            "realizedPnl": safe_float(row.get("realised", row.get("realized", row.get("realizedPnl")))),
            "funding": safe_float(row.get("holdFee", row.get("funding"))),
            "liquidationPrice": safe_float(row.get("liquidatePrice", row.get("liquidationPrice"))),
            "leverage": leverage,
            "maintenanceMarginRate": maintenance_rate,
            "liquidationFeeRate": liquidation_fee_rate,
            "maintenanceMarginUsd": maintenance_margin,
            "marginRatioPercent": margin_ratio,
        })
    return normalized
