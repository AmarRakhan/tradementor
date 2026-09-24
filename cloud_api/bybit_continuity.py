"""Read-only Bybit continuity client.

This module deliberately exposes balance and API-permission reads only.
It contains no order, transfer, withdrawal or account-mutation endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import httpx


class BybitContinuityError(RuntimeError):
    pass


@dataclass(frozen=True)
class BybitContinuityCredentials:
    api_key: str
    api_secret: str

    @classmethod
    def create(cls, api_key: str, api_secret: str) -> "BybitContinuityCredentials":
        key = str(api_key or "").strip()
        secret = str(api_secret or "").strip()
        if len(key) < 8 or len(key) > 256 or len(secret) < 8 or len(secret) > 256:
            raise ValueError("Ongeldige Bybit API-gegevens")
        return cls(api_key=key, api_secret=secret)


class BybitContinuityClient:
    """Minimum-privilege Bybit V5 reader for continuity monitoring."""

    def __init__(
        self,
        credentials: BybitContinuityCredentials,
        *,
        base_url: str = "https://api.bybit.com",
        recv_window_ms: int = 5000,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.recv_window_ms = int(recv_window_ms)
        self.timeout_seconds = float(timeout_seconds)

    def _signed_get(self, path: str, params: list[tuple[str, str]] | None = None) -> dict[str, Any]:
        rows = [(str(k), str(v)) for k, v in (params or []) if v is not None]
        query = urlencode(rows)
        timestamp = str(int(time.time() * 1000))
        payload = f"{timestamp}{self.credentials.api_key}{self.recv_window_ms}{query}"
        signature = hmac.new(
            self.credentials.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "X-BAPI-API-KEY": self.credentials.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": str(self.recv_window_ms),
            "X-BAPI-SIGN": signature,
        }
        try:
            response = httpx.get(
                f"{self.base_url}{path}",
                params=rows,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BybitContinuityError("Bybit is tijdelijk niet bereikbaar") from exc
        if int(body.get("retCode", -1)) != 0:
            message = str(body.get("retMsg") or "Bybit heeft de read-only aanvraag geweigerd")
            raise BybitContinuityError(message)
        result = body.get("result")
        return result if isinstance(result, dict) else {}

    def api_key_info(self) -> dict[str, Any]:
        return self._signed_get("/v5/user/query-api")

    def require_read_only(self) -> dict[str, Any]:
        info = self.api_key_info()
        if int(info.get("readOnly", 0)) != 1:
            raise BybitContinuityError(
                "Deze API-sleutel heeft schrijfrechten. Maak voor de veiligheid een read-only sleutel aan."
            )
        return info

    def funding_balances(self, coins: list[str] | None = None) -> list[dict[str, Any]]:
        requested = [str(coin).upper().strip() for coin in (coins or []) if str(coin).strip()]
        params: list[tuple[str, str]] = [("accountType", "FUND")]
        if requested:
            params.append(("coin", ",".join(dict.fromkeys(requested))))
        result = self._signed_get("/v5/asset/transfer/query-account-coins-balance", params)
        rows = result.get("balance")
        if not isinstance(rows, list):
            rows = result.get("list")
        return [row for row in (rows or []) if isinstance(row, dict)]

    def unified_balances(self) -> list[dict[str, Any]]:
        result = self._signed_get("/v5/account/wallet-balance", [("accountType", "UNIFIED")])
        accounts = result.get("list")
        if not isinstance(accounts, list):
            return []
        coins: list[dict[str, Any]] = []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            for row in account.get("coin") or []:
                if isinstance(row, dict):
                    coins.append(row)
        return coins
