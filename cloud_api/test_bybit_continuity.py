from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlencode

import pytest

import bybit_continuity as module
from bybit_continuity import BybitContinuityClient, BybitContinuityCredentials, BybitContinuityError


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_read_only_verification_accepts_only_read_only(monkeypatch):
    client = BybitContinuityClient(BybitContinuityCredentials.create("abcdefgh", "secretsecret"))
    monkeypatch.setattr(client, "api_key_info", lambda: {"readOnly": 1})
    assert client.require_read_only()["readOnly"] == 1

    monkeypatch.setattr(client, "api_key_info", lambda: {"readOnly": 0})
    with pytest.raises(BybitContinuityError, match="schrijfrechten"):
        client.require_read_only()


def test_funding_balance_uses_fund_account_and_never_mutating_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, *, params, headers, timeout):
        captured.update(url=url, params=params, headers=headers, timeout=timeout)
        return DummyResponse({"retCode": 0, "retMsg": "OK", "result": {
            "balance": [{"coin": "EUR", "walletBalance": "12.34", "transferBalance": "12.34"}]
        }})

    monkeypatch.setattr(module.httpx, "get", fake_get)
    monkeypatch.setattr(module.time, "time", lambda: 1_700_000_000.0)
    client = BybitContinuityClient(BybitContinuityCredentials.create("abcdefgh", "secretsecret"))
    rows = client.funding_balances(["EUR", "USDT"])

    assert rows[0]["coin"] == "EUR"
    assert captured["url"].endswith("/v5/asset/transfer/query-account-coins-balance")
    assert ("accountType", "FUND") in captured["params"]
    assert ("coin", "EUR,USDT") in captured["params"]
    assert all(word not in captured["url"] for word in ("order", "withdraw", "transfer/inter", "create"))


def test_bybit_signature_contract(monkeypatch):
    captured = {}

    def fake_get(url, *, params, headers, timeout):
        captured.update(url=url, params=params, headers=headers)
        return DummyResponse({"retCode": 0, "result": {"readOnly": 1}})

    monkeypatch.setattr(module.httpx, "get", fake_get)
    monkeypatch.setattr(module.time, "time", lambda: 1_700_000_000.0)
    creds = BybitContinuityCredentials.create("abcdefgh", "secretsecret")
    client = BybitContinuityClient(creds, recv_window_ms=5000)
    client.api_key_info()

    query = urlencode([])
    payload = f"1700000000000{creds.api_key}5000{query}"
    expected = hmac.new(creds.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert captured["headers"]["X-BAPI-SIGN"] == expected
    assert captured["headers"]["X-BAPI-API-KEY"] == creds.api_key


def test_secret_validation_rejects_too_short_values():
    with pytest.raises(ValueError):
        BybitContinuityCredentials.create("short", "also")
