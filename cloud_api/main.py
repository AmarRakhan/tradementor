"""TradeMentor multi-user control plane.

Order execution is deliberately absent until authentication, tenant isolation,
idempotency and Testnet validation have passed. Never add a global wallet runtime.
"""
from __future__ import annotations

import os
import json
import hashlib
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any

import firebase_admin
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from firebase_admin import auth, firestore
from google.cloud import secretmanager
from google.api_core import exceptions as google_exceptions
from eth_account import Account
from eth_account.messages import encode_defunct
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from pydantic import BaseModel, Field


if not firebase_admin._apps:
    firebase_admin.initialize_app()

app = FastAPI(title="TradeMentor Cloud API", version="0.1.0")
db = firestore.client()
info = Info(constants.MAINNET_API_URL, skip_ws=True)
secrets_client = secretmanager.SecretManagerServiceClient()
MAX_ONE_TEST_POSITION_USD = 12.0
MAX_SLIPPAGE = 0.01
_cache_lock = threading.RLock()
_perp_dex_cache: tuple[float, list[str]] = (0.0, [])
_positions_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_info_cache: dict[str, tuple[float, Any]] = {}


class WalletLinkRequest(BaseModel):
    address: str = Field(min_length=42, max_length=42)


class AgentProvisionRequest(BaseModel):
    private_key: str = Field(min_length=64, max_length=66)
    agent_address: str = Field(min_length=42, max_length=42)


class CloudSettingsRequest(BaseModel):
    max_active_positions: int = Field(ge=1, le=400)


class HyperliquidInfoRequest(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    dex: str = Field(default="", max_length=64)


class CloudStateSyncRequest(BaseModel):
    scanner: dict[str, Any] = Field(default_factory=dict)
    trading_settings: dict[str, Any] = Field(default_factory=dict)
    trades: list[dict[str, Any]] = Field(default_factory=list, max_length=2500)


class OrderIntentRequest(BaseModel):
    idempotency_key: str = Field(min_length=12, max_length=160)
    symbol: str = Field(min_length=1, max_length=40)
    kind: str = Field(pattern="^(entry|add_on|close)$")
    short: bool = False
    position_value_usd: float = Field(default=0, ge=0, le=1_000_000)
    leverage: int = Field(default=1, ge=1, le=100)
    signal_price: float = Field(default=0, ge=0)
    profit_percentage: float = Field(default=0, ge=0, le=100)


class ExecutionPlanRequest(BaseModel):
    idempotency_key: str = Field(min_length=12, max_length=160)
    symbol: str = Field(min_length=1, max_length=40)
    kind: str = Field(pattern="^(entry|add_on|close)$")
    short: bool = False
    position_value_usd: float = Field(default=0, ge=0, le=100_000)
    leverage: int = Field(default=1, ge=1, le=100)
    signal_price: float = Field(default=0, ge=0)
    profit_percentage: float = Field(default=0, ge=0, le=25)


class OneTestOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    short: bool
    position_value_usd: float = Field(ge=10, le=MAX_ONE_TEST_POSITION_USD)
    leverage: int = Field(ge=1, le=100)
    signal_price: float = Field(gt=0)
    profit_percentage: float = Field(gt=0, le=25)


class LiveEntryOrderRequest(BaseModel):
    idempotency_key: str = Field(min_length=12, max_length=160)
    symbol: str = Field(min_length=1, max_length=40)
    short: bool
    position_value_usd: float = Field(ge=10, le=100_000)
    leverage: int = Field(ge=1, le=100)
    signal_price: float = Field(gt=0)
    profit_percentage: float = Field(gt=0, le=25)
    max_adverse_percentage: float = Field(gt=0, le=25)
    strategy_id: str = Field(pattern="^strategy_[1-6]$")


class LiveTradingToggleRequest(BaseModel):
    enabled: bool


class TpProtectionRequest(BaseModel):
    profit_percentage: float = Field(gt=0, le=25)
    max_adverse_percentage: float = Field(default=1.5, gt=0, le=25)
    strategy_id: str = Field(default="strategy_1", pattern="^strategy_[1-6]$")
    max_adverse_percentage: float = Field(default=1.5, gt=0, le=25)
    strategy_id: str = Field(default="strategy_1", pattern="^strategy_[1-6]$")


class TakeAllProfitsRequest(BaseModel):
    confirm: bool
    operation_id: str = Field(min_length=12, max_length=120)
    minimum_net_profit_usd: float = Field(default=0.05, ge=0.01, le=100)


class ResetTradingDataRequest(BaseModel):
    confirm: bool


class FeedbackCreateRequest(BaseModel):
    category: str = Field(pattern="^(bug|wish|improvement|removal)$")
    title: str = Field(min_length=4, max_length=120)
    description: str = Field(min_length=10, max_length=4000)
    screen: str = Field(default="", max_length=80)
    app_version: str = Field(default="", max_length=30)
    build_number: int = Field(default=0, ge=0, le=10_000_000)
    device_model: str = Field(default="", max_length=120)
    android_version: str = Field(default="", max_length=40)


class FeedbackStatusRequest(BaseModel):
    status: str = Field(pattern="^(new|reviewed|planned|in_progress|resolved|declined)$")
    admin_note: str = Field(default="", max_length=1000)


def user_reference(user: dict[str, Any]):
    return db.collection("users").document(str(user["uid"]))


def linked_wallet(user: dict[str, Any]) -> str:
    snapshot = user_reference(user).get()
    address = str((snapshot.to_dict() or {}).get("walletAddress", "")).strip().lower()
    if not (address.startswith("0x") and len(address) == 42):
        raise HTTPException(409, "Cloudaccount is nog niet aan een Hyperliquid-wallet gekoppeld")
    return address


def require_admin(user: dict[str, Any]) -> None:
    expected = os.getenv("TRADEMENTOR_ADMIN_EMAIL", "tradementor.admin@gmail.com").strip().lower()
    admin_uids = {value.strip() for value in os.getenv("TRADEMENTOR_ADMIN_UIDS", "").split(",") if value.strip()}
    is_admin = str(user.get("email", "")).strip().lower() == expected or str(user.get("uid", "")) in admin_uids
    if not is_admin:
        raise HTTPException(403, "Alleen TradeMentor-beheer kan deze feedbackinbox openen")


def safe_feedback_text(value: str) -> str:
    """Keep secrets out of support reports even when pasted accidentally."""
    import re
    cleaned = value.strip()
    cleaned = re.sub(r"(?i)(secret|private\s*key|password|wachtwoord)\s*[:=]\s*\S+", r"\1: [VERWIJDERD]", cleaned)
    cleaned = re.sub(r"(?<![0-9a-fA-F])(?:0x)?[0-9a-fA-F]{64}(?![0-9a-fA-F])", "[MOGELIJKE SLEUTEL VERWIJDERD]", cleaned)
    return cleaned


def perp_dex_names() -> list[str]:
    global _perp_dex_cache
    now = time.monotonic()
    with _cache_lock:
        cached_at, cached_names = _perp_dex_cache
        if cached_names and now - cached_at < 900:
            return list(cached_names)
        try:
            names: list[str] = []
            for dex in info.perp_dexs():
                name = dex.get("name", "") if isinstance(dex, dict) else str(dex)
                if name and name.lower() != "none":
                    names.append(name)
            _perp_dex_cache = (now, names)
            return list(names)
        except Exception:
            if cached_names:
                return list(cached_names)
            # The original perp dex remains usable when HIP-3 metadata is rate-limited.
            return []


def all_positions(address: str, *, force: bool = False) -> list[dict[str, Any]]:
    now = time.monotonic()
    with _cache_lock:
        cached = _positions_cache.get(address)
        if not force and cached and now - cached[0] < 2.0:
            return [dict(position) for position in cached[1]]
    states = [info.user_state(address)]
    for name in perp_dex_names():
        try:
            states.append(info.user_state(address, name))
        except Exception:
            continue
    positions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for account_state in states:
        for item in account_state.get("assetPositions", []):
            position = item.get("position", {})
            if float(position.get("szi", "0") or 0) == 0:
                continue
            key = (str(position.get("coin", "")), str(position.get("szi", "")), str(position.get("entryPx", "")))
            if key not in seen:
                seen.add(key)
                positions.append(position)
    with _cache_lock:
        _positions_cache[address] = (time.monotonic(), [dict(position) for position in positions])
    return positions


def invalidate_positions(address: str) -> None:
    with _cache_lock:
        _positions_cache.pop(address, None)


def execution_perp_dex_names() -> list[str]:
    """SDK market map including the original Hyperliquid perp dex plus HIP-3 dexes."""
    return ["", *perp_dex_names()]


def all_frontend_open_orders(address: str) -> list[dict[str, Any]]:
    orders = list(info.frontend_open_orders(address))
    for dex in perp_dex_names():
        try:
            orders.extend(info.frontend_open_orders(address, dex))
        except Exception:
            continue
    return orders


def build_execution_plan(request: ExecutionPlanRequest, address: str, maximum: int) -> dict[str, Any]:
    """Validate a prospective mainnet action without signing or broadcasting it."""
    symbol = request.symbol.strip()
    normalized = symbol.upper()
    current = all_positions(address)
    existing = next((p for p in current if str(p.get("coin", "")).upper() == normalized), None)
    longs = sum(float(p.get("szi", 0) or 0) > 0 for p in current)
    shorts = sum(float(p.get("szi", 0) or 0) < 0 for p in current)

    if request.kind == "entry":
        if len(current) >= maximum:
            raise HTTPException(409, f"Maximum van {maximum} posities is bereikt")
        if existing is not None:
            raise HTTPException(409, "Deze pair heeft al een open positie")
        future_longs = longs + (0 if request.short else 1)
        future_shorts = shorts + (1 if request.short else 0)
        current_difference = abs(longs - shorts)
        future_difference = abs(future_longs - future_shorts)
        # If an existing portfolio is already outside the normal band, do not
        # deadlock recovery: allow only orders that strictly reduce imbalance.
        balance_allowed = future_difference < current_difference if current_difference > 5 else future_difference <= 5
        if not balance_allowed:
            raise HTTPException(409, "Deze order overschrijdt het maximale LONG/SHORT-verschil van 5")
    elif existing is None:
        raise HTTPException(404, "De actieve positie bestaat niet meer")
    elif request.kind == "add_on" and (float(existing.get("szi", 0) or 0) < 0) != request.short:
        raise HTTPException(409, "De bijkooprichting wijkt af van de actieve positie")

    if request.kind == "close":
        pnl = float(existing.get("unrealizedPnl", 0) or 0)
        value = abs(float(existing.get("positionValue", 0) or 0))
        buffer = max(0.05, value * 0.0015)
        if pnl <= buffer:
            raise HTTPException(409, "De positie heeft nog onvoldoende positieve buffer voor een veilige app-sluiting")
        return {
            "symbol": symbol, "kind": request.kind, "size": abs(float(existing.get("szi", 0) or 0)),
            "unrealizedPnl": pnl, "requiredPositiveBuffer": buffer, "dryRun": True,
        }

    if request.position_value_usd < 10:
        raise HTTPException(422, "Orderwaarde moet minimaal $10 zijn")
    dex = symbol.split(":", 1)[0] if ":" in symbol else ""
    try:
        execution_info = Info(
            constants.MAINNET_API_URL, skip_ws=True,
            perp_dexs=execution_perp_dex_names(),
        )
        mark = float(execution_info.all_mids(dex)[symbol])
        decimals = execution_info.asset_to_sz_decimals[execution_info.name_to_asset(symbol)]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, "Deze Hyperliquid-pair is niet beschikbaar") from exc
    if request.signal_price <= 0:
        raise HTTPException(422, "Een geldige signaalprijs ontbreekt")
    drift_limit = 0.003 if request.kind == "add_on" else 0.005
    drift = abs(mark / request.signal_price - 1.0)
    if drift > drift_limit:
        raise HTTPException(409, f"Koers is {drift * 100:.2f}% van het signaal afgeweken")
    size_factor = 10 ** decimals
    size = math.floor((request.position_value_usd / mark) * size_factor) / size_factor
    if size <= 0 or size * mark < 10:
        raise HTTPException(422, "Ordergrootte is na afronding kleiner dan $10")
    target = mark * (1.0 - request.profit_percentage / 100.0 if request.short else 1.0 + request.profit_percentage / 100.0)
    return {
        "symbol": symbol, "kind": request.kind, "short": request.short, "markPrice": mark,
        "size": size, "positionValueUsd": size * mark, "leverage": request.leverage,
        "priceDriftPercentage": drift * 100.0, "targetPriceEstimate": target,
        "activePositions": len(current), "maxActivePositions": maximum, "dryRun": True,
    }


def agent_wallet_status(user: dict[str, Any], expected_master: str) -> dict[str, Any]:
    uid = str(user["uid"])
    name = f"projects/{os.getenv('GOOGLE_CLOUD_PROJECT', 'tradementor-production')}/secrets/tradementor-wallet-{uid}/versions/latest"
    try:
        raw = secrets_client.access_secret_version(request={"name": name}).payload.data.decode("utf-8")
        payload = json.loads(raw)
        master = str(payload.get("master", "")).strip().lower()
        key = str(payload.get("key", "")).strip()
        agent = Account.from_key(key).address.lower()
        if master != expected_master:
            return {"configured": False, "reason": "wallet_mismatch"}
        return {"configured": True, "agentAddressSuffix": agent[-6:]}
    except Exception:
        return {"configured": False, "reason": "missing"}


def verified_agent_wallet(user: dict[str, Any], expected_master: str):
    uid = str(user["uid"])
    name = f"projects/{os.getenv('GOOGLE_CLOUD_PROJECT', 'tradementor-production')}/secrets/tradementor-wallet-{uid}/versions/latest"
    try:
        raw = secrets_client.access_secret_version(request={"name": name}).payload.data.decode("utf-8")
        payload = json.loads(raw)
        if str(payload.get("master", "")).strip().lower() != expected_master:
            raise HTTPException(409, "De agentwallet hoort niet bij de gekoppelde hoofdwallet")
        wallet = Account.from_key(str(payload.get("key", "")).strip())
        challenge = encode_defunct(text=f"TradeMentor cloud execution preflight:{uid}")
        signed = Account.sign_message(challenge, wallet.key)
        recovered = Account.recover_message(challenge, signature=signed.signature).lower()
        if recovered != wallet.address.lower():
            raise HTTPException(409, "De agentwallet kon de lokale ondertekenproef niet verifiëren")
        return wallet
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(409, "De persoonlijke agentwallet is niet uitvoeringsklaar") from exc


def authenticated_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Firebase ID-token ontbreekt")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return auth.verify_id_token(token, check_revoked=True)
    except Exception as exc:
        raise HTTPException(401, "Ongeldige of verlopen gebruikerssessie") from exc


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ready",
        "environment": os.getenv("TRADEMENTOR_ENV", "development"),
        "ordersEnabled": False,
        "multiUser": True,
    }


@app.get("/health/markets")
def market_health() -> dict[str, Any]:
    """Read-only proof that the execution SDK loaded the original perp market."""
    try:
        execution_info = Info(
            constants.MAINNET_API_URL,
            skip_ws=True,
            perp_dexs=execution_perp_dex_names(),
        )
        symbols = ("APT", "AAVE", "ADA", "BTC", "ETH")
        resolved = {
            symbol: {
                "asset": execution_info.name_to_asset(symbol),
                "markPrice": float(execution_info.all_mids("")[symbol]),
            }
            for symbol in symbols
        }
        return {"status": "ready", "originalPerpDex": True, "symbols": resolved}
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, "De oorspronkelijke Hyperliquid-marktkaart is niet gereed") from exc


@app.post("/v1/me/bootstrap")
def bootstrap_user(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    uid = str(user["uid"])
    reference = db.collection("users").document(uid)
    snapshot = reference.get()
    now = datetime.now(timezone.utc)
    if not snapshot.exists:
        reference.set({"createdAt": now, "updatedAt": now, "schemaVersion": 1})
    else:
        reference.update({"updatedAt": now})
    return {"uid": uid, "accountReady": True, "ordersEnabled": False}


@app.post("/v1/me/feedback")
def create_feedback(request: FeedbackCreateRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    reference = db.collection("feedbackReports").document()
    data = {
        "id": reference.id,
        "userId": str(user["uid"]),
        "userEmail": str(user.get("email", ""))[:180],
        "category": request.category,
        "title": safe_feedback_text(request.title),
        "description": safe_feedback_text(request.description),
        "screen": safe_feedback_text(request.screen),
        "appVersion": request.app_version,
        "buildNumber": request.build_number,
        "deviceModel": request.device_model,
        "androidVersion": request.android_version,
        "status": "new",
        "adminNote": "",
        "createdAt": now,
        "updatedAt": now,
    }
    reference.set(data)
    return {"received": True, "id": reference.id, "status": "new"}


def feedback_result(snapshot) -> dict[str, Any]:
    item = snapshot.to_dict() or {}
    item["id"] = snapshot.id
    for field in ("createdAt", "updatedAt"):
        value = item.get(field)
        if hasattr(value, "isoformat"):
            item[field] = value.isoformat()
    return item


@app.get("/v1/me/feedback")
def list_my_feedback(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    snapshots = db.collection("feedbackReports").where("userId", "==", str(user["uid"])).limit(100).stream()
    reports = sorted((feedback_result(item) for item in snapshots), key=lambda item: item.get("createdAt", ""), reverse=True)
    return {"reports": reports}


@app.get("/v1/admin/feedback")
def list_admin_feedback(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    require_admin(user)
    snapshots = db.collection("feedbackReports").limit(300).stream()
    reports = sorted((feedback_result(item) for item in snapshots), key=lambda item: item.get("createdAt", ""), reverse=True)
    return {"reports": reports}


@app.put("/v1/admin/feedback/{report_id}")
def update_feedback(report_id: str, request: FeedbackStatusRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    require_admin(user)
    if not report_id or len(report_id) > 80 or "/" in report_id:
        raise HTTPException(422, "Ongeldig feedbacknummer")
    reference = db.collection("feedbackReports").document(report_id)
    if not reference.get().exists:
        raise HTTPException(404, "Feedbackmelding bestaat niet")
    reference.set({
        "status": request.status,
        "adminNote": safe_feedback_text(request.admin_note),
        "updatedAt": datetime.now(timezone.utc),
        "updatedBy": str(user["uid"]),
    }, merge=True)
    return {"updated": True, "id": report_id, "status": request.status}


@app.put("/v1/me/wallet")
def link_wallet(request: WalletLinkRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = request.address.strip().lower()
    if not (address.startswith("0x") and all(char in "0123456789abcdef" for char in address[2:])):
        raise HTTPException(422, "Ongeldig Hyperliquid-walletadres")
    info.user_state(address)
    reference = user_reference(user)
    existing = str((reference.get().to_dict() or {}).get("walletAddress", "")).strip().lower()
    if existing and existing != address:
        # A second device must never silently replace the wallet belonging to
        # an existing account. That would also detach its approved agent wallet.
        raise HTTPException(
            409,
            "Dit TradeMentor-account hoort al bij een andere Hyperliquid-wallet. "
            "Meld af en gebruik het account dat bij deze wallet hoort.",
        )
    reference.set({"walletAddress": address, "updatedAt": datetime.now(timezone.utc)}, merge=True)
    return {"linked": True, "address": address, "tradingEnabled": False}


@app.get("/v1/me/wallet")
def wallet_status(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = linked_wallet(user)
    return {"linked": True, "address": address, "tradingEnabled": False}


@app.get("/v1/me/preflight")
def cloud_preflight(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = linked_wallet(user)
    current = all_positions(address)
    settings = user_reference(user).collection("settings").document("trading").get().to_dict() or {}
    live = user_reference(user).collection("executionControls").document("liveTrading").get().to_dict() or {}
    maximum = int(settings.get("maxActivePositions", 40))
    longs = sum(float(position.get("szi", 0)) > 0 for position in current)
    shorts = sum(float(position.get("szi", 0)) < 0 for position in current)
    return {
        "masterAddress": address,
        "activePositions": len(current),
        "maxActivePositions": maximum,
        "remainingSlots": max(0, maximum - len(current)),
        "longs": longs,
        "shorts": shorts,
        "symbols": sorted(str(position.get("coin", "")) for position in current),
        "tradingEnabled": bool(live.get("enabled", False)),
    }


@app.post("/v1/me/settings")
def cloud_settings(request: CloudSettingsRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    user_reference(user).collection("settings").document("trading").set({
        "maxActivePositions": request.max_active_positions,
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {"maxActivePositions": request.max_active_positions}


@app.put("/v1/me/state")
def sync_cloud_state(request: CloudStateSyncRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Idempotently store one user's scanner state and trade ledger.

    This route cannot place orders. Documents are always scoped below the
    authenticated Firebase uid and trade ids are stable upsert keys.
    """
    reference = user_reference(user)
    now = datetime.now(timezone.utc)
    scanner = dict(request.scanner)
    settings = dict(request.trading_settings)
    scanner["updatedAt"] = now
    settings["updatedAt"] = now
    reference.collection("settings").document("scanner").set(scanner, merge=True)
    reference.collection("settings").document("trading").set(settings, merge=True)

    valid_trades: list[tuple[str, dict[str, Any]]] = []
    for raw in request.trades:
        trade = dict(raw)
        trade_id = str(trade.get("id", "")).strip()
        symbol = str(trade.get("symbol", "")).strip().upper()
        if not trade_id or not symbol or len(symbol) > 40:
            continue
        trade["id"] = trade_id
        trade["symbol"] = symbol
        trade["syncedAt"] = now
        valid_trades.append((trade_id, trade))

    for start in range(0, len(valid_trades), 450):
        batch = db.batch()
        for trade_id, trade in valid_trades[start:start + 450]:
            batch.set(reference.collection("trades").document(trade_id), trade, merge=True)
        batch.commit()
    reference.set({"lastStateSyncAt": now, "updatedAt": now}, merge=True)
    return {"synced": True, "trades": len(valid_trades), "ordersEnabled": False}


@app.get("/v1/me/state")
def read_cloud_state(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    reference = user_reference(user)
    scanner = reference.collection("settings").document("scanner").get().to_dict() or {}
    settings = reference.collection("settings").document("trading").get().to_dict() or {}
    trades = [snapshot.to_dict() or {} for snapshot in reference.collection("trades").limit(2500).stream()]
    for value in (scanner, settings):
        value.pop("updatedAt", None)
    for trade in trades:
        trade.pop("syncedAt", None)
    return {"scanner": scanner, "tradingSettings": settings, "trades": trades, "ordersEnabled": False}


@app.post("/v1/me/state/reset")
def reset_trading_data(request: ResetTradingDataRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(422, "Resetbevestiging ontbreekt")
    reference = user_reference(user)
    now = datetime.now(timezone.utc)
    reference.collection("executionControls").document("liveTrading").set({
        "enabled": False, "disabledReason": "milestone_reset", "updatedAt": now,
    }, merge=True)
    reference.collection("executionControls").document("entryLease").set({
        "active": False, "updatedAt": now,
    }, merge=True)
    reference.set({"lastTradingResetAt": now, "updatedAt": now}, merge=True)
    # Historical trades and executions are intentionally retained as learning data.
    return {"reset": True, "learningDataRetained": True, "scanAndBuyEnabled": False}


@app.post("/v1/me/order-intents")
def prepare_order_intent(request: OrderIntentRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Prepare an order exactly once without executing it.

    The idempotency document protects network retries. A separate symbol lock
    protects against two different requests attempting the same pair.
    """
    uid = str(user["uid"])
    symbol = request.symbol.strip().upper()
    key_hash = hashlib.sha256(f"{uid}:{request.idempotency_key}".encode()).hexdigest()
    symbol_hash = hashlib.sha256(f"{uid}:{symbol}".encode()).hexdigest()
    intent_ref = user_reference(user).collection("orderIntents").document(key_hash)
    lock_ref = user_reference(user).collection("orderLocks").document(symbol_hash)
    transaction = db.transaction()

    @firestore.transactional
    def reserve(txn):
        existing = intent_ref.get(transaction=txn)
        if existing.exists:
            return {"intentId": key_hash, "duplicate": True, "status": (existing.to_dict() or {}).get("status", "prepared_locked")}
        lock = lock_ref.get(transaction=txn)
        lock_data = lock.to_dict() or {}
        if lock.exists and lock_data.get("active", False):
            raise HTTPException(409, f"Er bestaat al een actieve orderintentie voor {symbol}")
        now = datetime.now(timezone.utc)
        data = request.model_dump()
        data.update({
            "idempotencyKeyHash": key_hash, "symbol": symbol, "status": "prepared_locked",
            "ordersEnabled": False, "createdAt": now, "updatedAt": now,
        })
        txn.set(intent_ref, data)
        txn.set(lock_ref, {"active": True, "symbol": symbol, "intentId": key_hash, "kind": request.kind, "updatedAt": now})
        return {"intentId": key_hash, "duplicate": False, "status": "prepared_locked"}

    result = reserve(transaction)
    return {**result, "symbol": symbol, "ordersEnabled": False}


@app.get("/v1/me/order-intents")
def list_order_intents(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    values = []
    for snapshot in user_reference(user).collection("orderIntents").limit(100).stream():
        item = snapshot.to_dict() or {}
        for field in ("createdAt", "updatedAt"):
            if field in item and hasattr(item[field], "isoformat"):
                item[field] = item[field].isoformat()
        item.pop("idempotency_key", None)
        values.append(item)
    return {"intents": values, "ordersEnabled": False}


@app.post("/v1/me/info")
def cloud_hyperliquid_info(request: HyperliquidInfoRequest, user: dict[str, Any] = Depends(authenticated_user)) -> Any:
    allowed = {
        "clearinghouseState", "openOrders", "userFills", "userAbstraction",
        "spotClearinghouseState", "spotMetaAndAssetCtxs", "perpDexs",
    }
    if request.type not in allowed:
        raise HTTPException(422, "Dit Hyperliquid-informatietype is niet toegestaan")
    address = linked_wallet(user)
    payload: dict[str, Any] = {"type": request.type}
    if request.type in {"clearinghouseState", "openOrders", "userFills", "userAbstraction", "spotClearinghouseState"}:
        payload["user"] = address
    if request.type == "clearinghouseState" and request.dex:
        payload["dex"] = request.dex
    cache_key = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    ttl = 900.0 if request.type in {"perpDexs", "spotMetaAndAssetCtxs"} else (5.0 if request.type == "userFills" else 2.0)
    now = time.monotonic()
    with _cache_lock:
        cached = _info_cache.get(cache_key)
        if cached and now - cached[0] < ttl:
            return cached[1]
        # Keep the lock during the short upstream call so identical concurrent
        # phone refreshes collapse into one Hyperliquid request.
        try:
            response = httpx.post("https://api.hyperliquid.xyz/info", json=payload, timeout=15.0)
            response.raise_for_status()
            value = response.json()
            _info_cache[cache_key] = (time.monotonic(), value)
            return value
        except (httpx.HTTPError, ValueError) as exc:
            # A recent successful snapshot is safer and more useful than making
            # the entire wallet flash disconnected during a brief 429 burst.
            if cached and now - cached[0] < max(30.0, ttl):
                return cached[1]
            raise HTTPException(502, "Hyperliquid-accountgegevens zijn tijdelijk niet beschikbaar") from exc


@app.get("/v1/me/trading/health")
def cloud_trading_health(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = linked_wallet(user)
    current = all_positions(address)
    settings = user_reference(user).collection("settings").document("trading").get().to_dict() or {}
    live = user_reference(user).collection("executionControls").document("liveTrading").get().to_dict() or {}
    maximum = int(settings.get("maxActivePositions", 40))
    agent_status = agent_wallet_status(user, address)
    return {
        "status": "ready",
        "environment": "mainnet",
        "tradingEnabled": bool(live.get("enabled", False)),
        "oneTestOrderArmed": False,
        "activePositions": len(current),
        "remainingSlots": max(0, maximum - len(current)),
        "cloud": True,
        "agentWalletConfigured": agent_status["configured"],
        "agentWalletReason": agent_status.get("reason", "ready"),
        "agentAddressSuffix": agent_status.get("agentAddressSuffix", ""),
        "agentAddressSuffix": agent_status.get("agentAddressSuffix", ""),
    }


@app.get("/v1/me/agent/status")
def cloud_agent_status(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = linked_wallet(user)
    status = agent_wallet_status(user, address)
    return {**status, "ordersEnabled": False}


@app.post("/v1/me/agent/provision")
def provision_cloud_agent(request: AgentProvisionRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Store an agent only after Hyperliquid Mainnet has accepted its approval."""
    master = linked_wallet(user)
    clean_key = request.private_key.removeprefix("0x").strip()
    if len(clean_key) != 64 or any(char not in "0123456789abcdefABCDEF" for char in clean_key):
        raise HTTPException(422, "Ongeldige agentwalletsleutel")
    try:
        agent = Account.from_key(clean_key).address.lower()
    except Exception as exc:
        raise HTTPException(422, "Agentwallet kon niet worden afgeleid") from exc
    if agent != request.agent_address.strip().lower():
        raise HTTPException(409, "Agentwalletadres en sleutel horen niet bij elkaar")

    try:
        role_response = httpx.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "userRole", "user": agent},
            timeout=15.0,
        )
        role_response.raise_for_status()
        role = role_response.json()
        if str(role.get("role", "")).lower() != "agent":
            raise HTTPException(409, "Hyperliquid heeft deze Mainnet-agentwallet nog niet goedgekeurd")
        role_master = str((role.get("data") or {}).get("user", "")).strip().lower()
        if role_master and role_master != master:
            raise HTTPException(409, "Deze agentwallet is door een andere hoofdwallet goedgekeurd")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Mainnet-agentmachtiging kon niet worden gecontroleerd") from exc

    project = os.getenv("GOOGLE_CLOUD_PROJECT", "tradementor-production")
    secret_id = f"tradementor-wallet-{user['uid']}"
    parent = f"projects/{project}"
    secret_name = f"{parent}/secrets/{secret_id}"
    try:
        secrets_client.create_secret(
            request={"parent": parent, "secret_id": secret_id, "secret": {"replication": {"automatic": {}}}}
        )
    except google_exceptions.AlreadyExists:
        pass
    payload = json.dumps({"master": master, "key": clean_key}).encode("utf-8")
    secrets_client.add_secret_version(request={"parent": secret_name, "payload": {"data": payload}})
    user_reference(user).collection("executionControls").document("liveTrading").set({
        "enabled": False, "disabledReason": "new_agent_requires_preflight", "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {"configured": True, "agentAddressSuffix": agent[-6:], "tradingEnabled": False}


@app.get("/v1/me/execution/preflight")
def execution_preflight(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = linked_wallet(user)
    wallet = verified_agent_wallet(user, address)
    current = all_positions(address)
    settings = user_reference(user).collection("settings").document("trading").get().to_dict() or {}
    maximum = int(settings.get("maxActivePositions", settings.get("maxActiveTrades", 40)))
    return {
        "ready": True,
        "dryRun": True,
        "signatureVerified": True,
        "agentAddressSuffix": wallet.address[-6:].lower(),
        "activePositions": len(current),
        "maxActivePositions": maximum,
        "remainingSlots": max(0, maximum - len(current)),
        "ordersEnabled": False,
    }


@app.put("/v1/me/execution/live")
def set_live_trading(request: LiveTradingToggleRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = linked_wallet(user)
    verified_agent_wallet(user, address)
    enabled = bool(request.enabled)
    user_reference(user).collection("executionControls").document("liveTrading").set({
        "enabled": enabled, "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {
        "enabled": enabled,
        "ordersEnabled": enabled and os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() == "true",
    }


@app.post("/v1/me/execution/plan")
def execution_plan(request: ExecutionPlanRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Produce a fully validated plan but never submit an order."""
    address = linked_wallet(user)
    verified_agent_wallet(user, address)
    settings = user_reference(user).collection("settings").document("trading").get().to_dict() or {}
    maximum = int(settings.get("maxActivePositions", settings.get("maxActiveTrades", 40)))
    plan = build_execution_plan(request, address, maximum)
    return {**plan, "signatureVerified": True, "ordersEnabled": False}


def orders_locked() -> None:
    raise HTTPException(423, "Cloudorders blijven vergrendeld tot de agentwallet en idempotentietests zijn voltooid")


@app.post("/v1/me/orders/one-test-order")
def one_test_entry_order(request: OneTestOrderRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Execute one pre-authorized, fail-closed mainnet test order per user.

    A Firestore claim is written before broadcasting. Any crash therefore locks
    the test instead of risking a duplicate retry.
    """
    if os.getenv("TRADEMENTOR_ALLOW_ONE_TEST_ORDER", "").lower() != "true":
        orders_locked()
    address = linked_wallet(user)
    settings = user_reference(user).collection("settings").document("trading").get().to_dict() or {}
    maximum = int(settings.get("maxActivePositions", settings.get("maxActiveTrades", 40)))
    plan_request = ExecutionPlanRequest(
        idempotency_key=f"one-test:{request.symbol}:{request.signal_price:.10g}", kind="entry",
        **request.model_dump(),
    )
    plan = build_execution_plan(plan_request, address, maximum)
    control_ref = user_reference(user).collection("executionControls").document("oneTestOrder")
    transaction = db.transaction()

    @firestore.transactional
    def claim_once(txn):
        snapshot = control_ref.get(transaction=txn)
        control = snapshot.to_dict() or {}
        if not control.get("armed", False):
            raise HTTPException(423, "De eenmalige testorder is niet persoonlijk vrijgegeven")
        if control.get("status") not in (None, "armed"):
            raise HTTPException(409, "De eenmalige testorder is al geclaimd of uitgevoerd")
        approved_maximum = min(float(control.get("maximumUsd", MAX_ONE_TEST_POSITION_USD)), MAX_ONE_TEST_POSITION_USD)
        if request.position_value_usd > approved_maximum:
            raise HTTPException(422, f"De testorder mag maximaal ${approved_maximum:.2f} bedragen")
        txn.set(control_ref, {
            "armed": False, "status": "claimed_before_broadcast", "symbol": plan["symbol"],
            "claimedAt": datetime.now(timezone.utc), "maximumUsd": approved_maximum,
        }, merge=True)

    claim_once(transaction)
    wallet = verified_agent_wallet(user, address)
    exchange = Exchange(
        wallet, constants.MAINNET_API_URL, account_address=address,
        perp_dexs=execution_perp_dex_names(),
    )
    try:
        exchange.update_leverage(request.leverage, plan["symbol"], is_cross=True)
        response = exchange.market_open(
            plan["symbol"], not request.short, plan["size"], px=plan["markPrice"], slippage=MAX_SLIPPAGE,
        )
        filled = response["response"]["data"]["statuses"][0]["filled"]
        fill_price = float(filled["avgPx"])
        filled_size = float(filled["totalSz"])
        entry_order_id = filled.get("oid")
    except Exception as exc:
        control_ref.set({"status": "broadcast_failed_locked", "failedAt": datetime.now(timezone.utc)}, merge=True)
        raise HTTPException(502, "De testorder is vergrendeld omdat de instap niet volledig kon worden bevestigd") from exc

    asset = info.name_to_asset(plan["symbol"])
    price_decimals = max(0, 6 - info.asset_to_sz_decimals[asset])
    raw_target = fill_price * (1.0 - request.profit_percentage / 100.0 if request.short else 1.0 + request.profit_percentage / 100.0)
    target = round(float(f"{raw_target:.5g}"), price_decimals)
    try:
        tp_response = exchange.order(
            plan["symbol"], request.short, filled_size, target,
            {"trigger": {"triggerPx": target, "isMarket": True, "tpsl": "tp"}}, reduce_only=True,
        )
        tp_status = tp_response["response"]["data"]["statuses"][0]
        if "resting" not in tp_status:
            raise ValueError("take-profit is niet als rustende order bevestigd")
    except Exception as exc:
        control_ref.set({
            "status": "entry_filled_tp_failed_locked", "entryOrderId": entry_order_id,
            "fillPrice": fill_price, "filledSize": filled_size, "failedAt": datetime.now(timezone.utc),
        }, merge=True)
        raise HTTPException(502, "Instap is gevuld, maar take-profit ontbreekt; verdere cloudhandel is vergrendeld") from exc

    control_ref.set({
        "status": "completed", "entryOrderId": entry_order_id, "fillPrice": fill_price,
        "filledSize": filled_size, "targetPrice": target, "completedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {
        "accepted": True, "symbol": plan["symbol"], "short": request.short,
        "filledSize": filled_size, "fillPrice": fill_price, "targetPrice": target,
        "entryOrderId": entry_order_id, "oneTestOrderConsumed": True,
    }


@app.post("/v1/me/orders/entry")
def live_entry_order(request: LiveEntryOrderRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Execute an idempotent production entry for one authenticated tenant."""
    if os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        orders_locked()
    reference = user_reference(user)
    live_ref = reference.collection("executionControls").document("liveTrading")
    live = live_ref.get().to_dict() or {}
    if not live.get("enabled", False):
        raise HTTPException(423, "Scan & Buy staat voor dit account uit")
    if request.strategy_id == "strategy_2":
        if request.leverage > 3:
            raise HTTPException(422, "Quantum Shield staat maximaal 3× hefboom toe")
        if request.max_adverse_percentage > 1.5:
            raise HTTPException(422, "Quantum Shield staat maximaal 1,5% ongunstige koersbeweging toe")
    address = linked_wallet(user)
    settings = reference.collection("settings").document("trading").get().to_dict() or {}
    maximum = int(settings.get("maxActivePositions", settings.get("maxActiveTrades", 40)))
    configured_value = float(settings.get("positionSizeUsd", request.position_value_usd))
    if request.position_value_usd > configured_value + 0.001:
        raise HTTPException(422, "Orderbedrag is hoger dan het persoonlijk ingestelde instapbedrag")
    plan = build_execution_plan(ExecutionPlanRequest(
        idempotency_key=request.idempotency_key, kind="entry",
        **request.model_dump(exclude={"idempotency_key", "max_adverse_percentage", "strategy_id"})
    ), address, maximum)
    uid = str(user["uid"])
    intent_id = hashlib.sha256(f"{uid}:{request.idempotency_key}".encode()).hexdigest()
    intent_ref = reference.collection("executions").document(intent_id)
    lease_ref = reference.collection("executionControls").document("entryLease")
    transaction = db.transaction()

    @firestore.transactional
    def claim(txn):
        existing = intent_ref.get(transaction=txn)
        if existing.exists:
            data = existing.to_dict() or {}
            if data.get("status") == "completed":
                return data
            raise HTTPException(409, "Deze orderopdracht is al in behandeling")
        now = datetime.now(timezone.utc)
        lease = lease_ref.get(transaction=txn).to_dict() or {}
        lease_updated = lease.get("updatedAt")
        # Cloud Run can be interrupted after claiming this lease. Normal entry
        # orders finish in seconds, so reclaim a lease older than five minutes.
        lease_is_fresh = (
            lease.get("active", False)
            and hasattr(lease_updated, "astimezone")
            and (now - lease_updated.astimezone(timezone.utc)).total_seconds() < 300
        )
        if lease_is_fresh:
            raise HTTPException(409, "Een andere cloudorder wordt nog verwerkt")
        txn.set(intent_ref, {
            "status": "claimed_before_broadcast", "symbol": plan["symbol"], "short": request.short,
            "positionValueUsd": request.position_value_usd, "strategyId": request.strategy_id,
            "maxAdversePercentage": request.max_adverse_percentage, "createdAt": now, "updatedAt": now,
        })
        txn.set(lease_ref, {"active": True, "intentId": intent_id, "updatedAt": now})
        return None

    completed = claim(transaction)
    if completed:
        return {
            "accepted": True, "symbol": completed["symbol"], "short": completed["short"],
            "filledSize": completed["filledSize"], "fillPrice": completed["fillPrice"],
            "targetPrice": completed["targetPrice"], "entryOrderId": completed.get("entryOrderId"),
            "duplicate": True,
        }

    try:
        wallet = verified_agent_wallet(user, address)
    except Exception:
        # Verification happens after the transactional claim. A replaced or
        # temporarily unavailable agent must never strand the account lease.
        now = datetime.now(timezone.utc)
        intent_ref.set({"status": "agent_verification_failed", "updatedAt": now}, merge=True)
        lease_ref.set({"active": False, "updatedAt": now}, merge=True)
        raise
    exchange = Exchange(
        wallet, constants.MAINNET_API_URL, account_address=address,
        perp_dexs=execution_perp_dex_names(),
    )
    try:
        exchange.update_leverage(request.leverage, plan["symbol"], is_cross=True)
        response = exchange.market_open(
            plan["symbol"], not request.short, plan["size"], px=plan["markPrice"], slippage=MAX_SLIPPAGE,
        )
        filled = response["response"]["data"]["statuses"][0]["filled"]
        fill_price = float(filled["avgPx"])
        filled_size = float(filled["totalSz"])
        entry_order_id = filled.get("oid")
    except Exception as exc:
        intent_ref.set({"status": "broadcast_failed_locked", "updatedAt": datetime.now(timezone.utc)}, merge=True)
        lease_ref.set({"active": False, "updatedAt": datetime.now(timezone.utc)}, merge=True)
        raise HTTPException(502, "Instap is niet volledig bevestigd; deze opdracht blijft vergrendeld") from exc

    asset = exchange.info.name_to_asset(plan["symbol"])
    price_decimals = max(0, 6 - exchange.info.asset_to_sz_decimals[asset])
    raw_target = fill_price * (1.0 - request.profit_percentage / 100.0 if request.short else 1.0 + request.profit_percentage / 100.0)
    target = round(float(f"{raw_target:.5g}"), price_decimals)
    tp_order_id = None
    try:
        tp_response = exchange.order(
            plan["symbol"], request.short, filled_size, target,
            {"trigger": {"triggerPx": target, "isMarket": True, "tpsl": "tp"}}, reduce_only=True,
        )
        tp_status = tp_response["response"]["data"]["statuses"][0]
        if "resting" not in tp_status:
            raise ValueError("take-profit ontbreekt")
        tp_order_id = tp_status["resting"].get("oid")
    except Exception as exc:
        now = datetime.now(timezone.utc)
        emergency_close = None
        try:
            emergency_close = exchange.market_close(
                plan["symbol"], sz=filled_size, px=fill_price, slippage=MAX_SLIPPAGE,
            )
        except Exception:
            pass
        intent_ref.set({"status": "entry_filled_tp_failed_locked", "emergencyClose": emergency_close, "updatedAt": now}, merge=True)
        lease_ref.set({"active": False, "updatedAt": now}, merge=True)
        live_ref.set({"enabled": False, "disabledReason": "take_profit_failed", "updatedAt": now}, merge=True)
        raise HTTPException(502, "Instap gevuld maar take-profit ontbreekt; noodsluiting gestart en Scan & Buy uitgeschakeld") from exc

    raw_stop = fill_price * (
        1.0 + request.max_adverse_percentage / 100.0
        if request.short else 1.0 - request.max_adverse_percentage / 100.0
    )
    stop_price = round(float(f"{raw_stop:.5g}"), price_decimals)
    try:
        sl_response = exchange.order(
            plan["symbol"], request.short, filled_size, stop_price,
            {"trigger": {"triggerPx": stop_price, "isMarket": True, "tpsl": "sl"}}, reduce_only=True,
        )
        sl_status = sl_response["response"]["data"]["statuses"][0]
        if "resting" not in sl_status:
            raise ValueError("stop-loss ontbreekt")
        sl_order_id = sl_status["resting"].get("oid")
    except Exception as exc:
        now = datetime.now(timezone.utc)
        if tp_order_id is not None:
            try:
                exchange.cancel(plan["symbol"], tp_order_id)
            except Exception:
                pass
        emergency_close = None
        try:
            emergency_close = exchange.market_close(
                plan["symbol"], sz=filled_size, px=fill_price, slippage=MAX_SLIPPAGE,
            )
        except Exception:
            pass
        intent_ref.set({
            "status": "entry_filled_sl_failed_locked", "emergencyClose": emergency_close, "updatedAt": now,
        }, merge=True)
        lease_ref.set({"active": False, "updatedAt": now}, merge=True)
        live_ref.set({"enabled": False, "disabledReason": "stop_loss_failed", "updatedAt": now}, merge=True)
        raise HTTPException(502, "Instap gevuld maar stop-loss ontbreekt; noodsluiting gestart en Scan & Buy uitgeschakeld") from exc

    result = {
        "status": "completed", "symbol": plan["symbol"], "short": request.short,
        "filledSize": filled_size, "fillPrice": fill_price, "targetPrice": target,
        "stopPrice": stop_price, "entryOrderId": entry_order_id,
        "takeProfitOrderId": tp_order_id, "stopLossOrderId": sl_order_id,
        "strategyId": request.strategy_id, "updatedAt": datetime.now(timezone.utc),
    }
    batch = db.batch()
    batch.set(intent_ref, result, merge=True)
    batch.set(lease_ref, {"active": False, "updatedAt": datetime.now(timezone.utc)}, merge=True)
    batch.commit()
    invalidate_positions(address)
    return {"accepted": True, **{k: v for k, v in result.items() if k not in ("status", "updatedAt")}, "duplicate": False}


@app.post("/v1/me/positions/protect")
def protect_open_positions(request: TpProtectionRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Ensure every open position has real reduce-only Hyperliquid TP and SL protection.

    This is idempotent: an existing reduce-only trigger is never duplicated. It
    also covers positions opened outside TradeMentor. If one repair fails,
    Scan & Buy is disabled until the account can be checked safely.
    """
    if os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        orders_locked()
    reference = user_reference(user)
    address = linked_wallet(user)
    wallet = verified_agent_wallet(user, address)
    exchange = Exchange(
        wallet, constants.MAINNET_API_URL, account_address=address,
        perp_dexs=execution_perp_dex_names(),
    )
    positions = all_positions(address)
    try:
        open_orders = all_frontend_open_orders(address)
    except Exception as exc:
        raise HTTPException(502, "Openstaande Hyperliquid-orders konden niet veilig worden gecontroleerd") from exc

    take_profit_symbols = {
        str(order.get("coin", "")).upper()
        for order in open_orders
        if bool(order.get("reduceOnly", False))
        and float(order.get("triggerPx", 0) or 0) > 0
        and "take profit" in str(order.get("orderType", "")).lower()
    }
    stop_loss_symbols = {
        str(order.get("coin", "")).upper()
        for order in open_orders
        if bool(order.get("reduceOnly", False))
        and float(order.get("triggerPx", 0) or 0) > 0
        and "stop" in str(order.get("orderType", "")).lower()
    }
    already_protected: list[str] = []
    repaired: list[str] = []
    closed_at_target: list[str] = []
    failed: list[dict[str, str]] = []

    for position in positions:
        symbol = str(position.get("coin", "")).strip()
        if not symbol:
            continue
        has_tp = symbol.upper() in take_profit_symbols
        has_sl = symbol.upper() in stop_loss_symbols
        if has_tp and has_sl:
            already_protected.append(symbol)
            continue
        signed_size = float(position.get("szi", 0) or 0)
        entry_price = float(position.get("entryPx", 0) or 0)
        if signed_size == 0 or entry_price <= 0:
            failed.append({"symbol": symbol, "reason": "ongeldige positiegegevens"})
            continue
        try:
            asset = exchange.info.name_to_asset(symbol)
            price_decimals = max(0, 6 - exchange.info.asset_to_sz_decimals[asset])
            raw_target = entry_price * (
                1.0 - request.profit_percentage / 100.0
                if signed_size < 0
                else 1.0 + request.profit_percentage / 100.0
            )
            target = round(float(f"{raw_target:.5g}"), price_decimals)
            raw_stop = entry_price * (
                1.0 + request.max_adverse_percentage / 100.0
                if signed_size < 0
                else 1.0 - request.max_adverse_percentage / 100.0
            )
            stop_price = round(float(f"{raw_stop:.5g}"), price_decimals)
            if not has_tp:
                response = exchange.order(
                    symbol, signed_size < 0, abs(signed_size), target,
                    {"trigger": {"triggerPx": target, "isMarket": True, "tpsl": "tp"}},
                    reduce_only=True,
                )
                status = response["response"]["data"]["statuses"][0]
                if "filled" in status:
                    closed_at_target.append(symbol)
                    continue
                if "resting" not in status:
                    raise ValueError(str(status.get("error", "TP niet bevestigd")))
            if not has_sl:
                response = exchange.order(
                    symbol, signed_size < 0, abs(signed_size), stop_price,
                    {"trigger": {"triggerPx": stop_price, "isMarket": True, "tpsl": "sl"}},
                    reduce_only=True,
                )
                status = response["response"]["data"]["statuses"][0]
                if "resting" not in status:
                    raise ValueError(str(status.get("error", "SL niet bevestigd")))
            repaired.append(symbol)
        except Exception as exc:
            failed.append({"symbol": symbol, "reason": str(exc)[:180]})

    now = datetime.now(timezone.utc)
    reference.collection("protectionAudits").document("latest").set({
        "profitPercentage": request.profit_percentage,
        "maxAdversePercentage": request.max_adverse_percentage,
        "strategyId": request.strategy_id,
        "positionsChecked": len(positions),
        "alreadyProtected": already_protected,
        "repaired": repaired,
        "closedAtTarget": closed_at_target,
        "failed": failed,
        "updatedAt": now,
    })
    if failed:
        reference.collection("executionControls").document("liveTrading").set({
            "enabled": False, "disabledReason": "position_protection_failed", "updatedAt": now,
        }, merge=True)
    return {
        "positionsChecked": len(positions),
        "alreadyProtected": already_protected,
        "repaired": repaired,
        "closedAtTarget": closed_at_target,
        "failed": failed,
        "scanAndBuyEnabled": not failed,
    }


def profitable_position_preview(address: str, minimum_net_profit_usd: float = 0.05) -> dict[str, Any]:
    positions = all_positions(address)
    eligible: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for position in positions:
        symbol = str(position.get("coin", "")).strip()
        pnl = float(position.get("unrealizedPnl", 0) or 0)
        value = abs(float(position.get("positionValue", 0) or 0))
        # Conservative allowance for closing fee and price movement. A position
        # must remain positive after this buffer; merely showing green is not enough.
        buffer = max(minimum_net_profit_usd, value * 0.0015)
        item = {
            "symbol": symbol,
            "unrealizedPnl": pnl,
            "positionValueUsd": value,
            "safetyBufferUsd": buffer,
            "estimatedNetProfitUsd": max(0.0, pnl - buffer),
        }
        if symbol and pnl > buffer:
            eligible.append(item)
        else:
            skipped.append(item)
    return {
        "eligible": eligible,
        "skipped": skipped,
        "eligibleCount": len(eligible),
        "estimatedGrossProfitUsd": sum(item["unrealizedPnl"] for item in eligible),
        "estimatedNetProfitUsd": sum(item["estimatedNetProfitUsd"] for item in eligible),
        "minimumNetProfitUsd": minimum_net_profit_usd,
    }


@app.get("/v1/me/positions/take-all-profits/preview")
def take_all_profits_preview(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    return profitable_position_preview(linked_wallet(user))


@app.post("/v1/me/positions/take-all-profits")
def take_all_profits(request: TakeAllProfitsRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        orders_locked()
    if not request.confirm:
        raise HTTPException(422, "Bevestiging voor Take All Profits ontbreekt")
    reference = user_reference(user)
    address = linked_wallet(user)
    wallet = verified_agent_wallet(user, address)
    operation_hash = hashlib.sha256(f"{user['uid']}:{request.operation_id}".encode()).hexdigest()
    operation_ref = reference.collection("bulkExits").document(operation_hash)
    existing = operation_ref.get().to_dict() or {}
    if existing.get("status") == "completed":
        return {**existing.get("result", {}), "duplicate": True}
    if existing:
        raise HTTPException(409, "Deze Take All Profits-opdracht is al in behandeling")

    live_ref = reference.collection("executionControls").document("liveTrading")
    entry_lease_ref = reference.collection("executionControls").document("entryLease")
    entry_lease = entry_lease_ref.get().to_dict() or {}
    lease_updated = entry_lease.get("updatedAt")
    lease_is_fresh = (
        entry_lease.get("active", False)
        and hasattr(lease_updated, "astimezone")
        and (datetime.now(timezone.utc) - lease_updated.astimezone(timezone.utc)).total_seconds() < 300
    )
    if lease_is_fresh:
        raise HTTPException(409, "Een instaporder wordt nog verwerkt; probeer het zo opnieuw")
    now = datetime.now(timezone.utc)
    live_before = bool((live_ref.get().to_dict() or {}).get("enabled", False))
    batch = db.batch()
    batch.set(operation_ref, {"status": "claimed", "createdAt": now})
    batch.set(live_ref, {"enabled": False, "disabledReason": "take_all_profits", "updatedAt": now}, merge=True)
    batch.set(entry_lease_ref, {"active": True, "intentId": operation_hash, "updatedAt": now}, merge=True)
    batch.commit()

    exchange = Exchange(
        wallet, constants.MAINNET_API_URL, account_address=address,
        perp_dexs=execution_perp_dex_names(),
    )
    preview = profitable_position_preview(address, request.minimum_net_profit_usd)
    closed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = list(preview["skipped"])
    failed: list[dict[str, str]] = []
    try:
        open_orders = all_frontend_open_orders(address)
        for candidate in preview["eligible"]:
            symbol = candidate["symbol"]
            latest = next((p for p in all_positions(address) if str(p.get("coin", "")).upper() == symbol.upper()), None)
            if latest is None:
                skipped.append({**candidate, "reason": "positie is al gesloten"})
                continue
            pnl = float(latest.get("unrealizedPnl", 0) or 0)
            value = abs(float(latest.get("positionValue", 0) or 0))
            buffer = max(request.minimum_net_profit_usd, value * 0.0015)
            size = abs(float(latest.get("szi", 0) or 0))
            if size <= 0 or pnl <= buffer:
                skipped.append({**candidate, "reason": "niet langer netto groen"})
                continue
            try:
                mark = value / size
                response = exchange.market_close(symbol, sz=size, px=mark, slippage=MAX_SLIPPAGE)
                status = response["response"]["data"]["statuses"][0]
                if "filled" not in status:
                    raise ValueError(str(status.get("error", "sluiting niet gevuld")))
                cancelled = 0
                for order in open_orders:
                    if str(order.get("coin", "")).upper() != symbol.upper() or not bool(order.get("reduceOnly", False)):
                        continue
                    oid = order.get("oid")
                    if oid is None:
                        continue
                    try:
                        exchange.cancel(symbol, int(oid))
                        cancelled += 1
                    except Exception:
                        pass
                closed.append({
                    **candidate, "confirmedAt": datetime.now(timezone.utc).isoformat(),
                    "cancelledOrders": cancelled, "exitReason": "TAKE_ALL_PROFITS",
                })
                invalidate_positions(address)
            except Exception as exc:
                failed.append({"symbol": symbol, "reason": str(exc)[:180]})
        result = {
            "closed": closed, "skipped": skipped, "failed": failed,
            "closedCount": len(closed),
            "estimatedRealizedProfitUsd": sum(item["unrealizedPnl"] for item in closed),
            "scannerWasEnabled": live_before, "scannerEnabled": False,
        }
        operation_ref.set({"status": "completed", "result": result, "completedAt": datetime.now(timezone.utc)}, merge=True)
        return {**result, "duplicate": False}
    finally:
        entry_lease_ref.set({"active": False, "updatedAt": datetime.now(timezone.utc)}, merge=True)


@app.post("/v1/me/positions/add-on")
def locked_add_on(_: dict[str, Any], user: dict[str, Any] = Depends(authenticated_user)) -> None:
    linked_wallet(user)
    orders_locked()


@app.post("/v1/me/positions/{symbol}/close")
def locked_close(symbol: str, _: dict[str, Any], user: dict[str, Any] = Depends(authenticated_user)) -> None:
    linked_wallet(user)
    orders_locked()
