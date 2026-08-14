Warning: truncated output (original token count: 93861)
Total output lines: 6452

"""TradeMentor multi-user control plane.

Order execution is deliberately absent until authentication, tenant isolation,
idempotency and Testnet validation have passed. Never add a global wallet runtime.
"""
from __future__ import annotations

import os
import json
import base64
import hashlib
import hmac
import math
import re
import secrets as python_secrets
import struct
import threading
import time
from urllib.parse import quote
from dataclasses import replace
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

import firebase_admin
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from firebase_admin import auth, firestore
from google.cloud import secretmanager
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_auth_requests
from google.api_core import exceptions as google_exceptions
from eth_account import Account
from eth_account.messages import encode_defunct
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from pydantic import BaseModel, Field
from aster_universe import AsterUniverseSnapshot, build_snapshot as build_aster_universe_snapshot, normalize_top_n, stale_snapshot as stale_aster_universe_snapshot
from trading_cycle import cycle_payload_values, cycle_start_decision
from close_all import execute_close_all
from position_close import ALLOWED_CLOSE_PERCENTAGES, close_size
from bitcoin_casino import ALLOWED_DURATIONS, MAX_STAKE_USD, MIN_STAKE_USD, directional_signal, price_result, rolling_backtest, validate_trade
from mexc_gateway import (
    MexcApiError, MexcCanaryUncertain, MexcClient, MexcCredentials,
    canary_existing_action, normalized_positions, place_canary_once, place_order_once, safe_float, usdt_asset,
    volume_for_notional,
)
from mexc_automation import (
    AccountSnapshot as MexcAutoAccountSnapshot,
    AutoSettings as MexcAutoSettings,
    AutoState as MexcAutoState,
    decide as decide_mexc_automation,
    plan_order_legs as plan_mexc_order_legs,
    signal_from_candles as mexc_signal_from_candles,
)
from mexc_hedge_dca_v3 import (
    V3Account, V3Market, V3Settings, V3State, apply_paper_action, decide_v3,
    enforce_protective_only, protective_monitor_is_complete,
    reconcile_state as reconcile_v3_state, state_from_dict as v3_state_from_dict,
    state_to_dict as v3_state_to_dict,
)
from aster_gateway import (
    AsterApiError, AsterOrderIntent, AsterSubmissionUncertain, AsterV3Client, AsterValidationError, ContractRules, PositionSide,
    build_hedge_order_payload,
)
from aster_signing import AsterSecret, local_eip712_signer
from aster_history import closed_trades_from_fills, realized_events_from_income, merge_realized_events, recent_trade_activity_from_fills, trade_events_from_fills
from aster_strategy import AsterStrategySettings
from aster_strategy2 import PortfolioState as Strategy2PortfolioState, Strategy2Config, validate_worst_case
from aster_strategy2_simulation import standard_suite as strategy2_standard_suite, failure_suite as strategy2_failure_suite
from aster_strategy2_state import OwnedLeg, reconcile_owned_legs
from aster_strategy2_readiness import build_readiness_report
from aster_canary import choose_flat_symbol, existing_canary_action
from aster_strategy2 import Decision
from aster_strategy3 import Strategy3Config, LegState as Strategy3LegState, PortfolioState as Strategy3PortfolioState
from aster_strategy3 import Decision as Strategy3Decision, decide as decide_strategy3, net_return as strategy3_net_return
from aster_strategy3 import account_canary_proven as strategy3_account_canary_proven
from aster_strategy3 import persisted_runtime_mode as strategy3_persisted_runtime_mode
from aster_strategy3_simulation import standard_suite as strategy3_standard_suite, failure_suite as strategy3_failure_suite
from aster_strategy3_readiness import build_strategy3_readiness_report
from aster_strategy3_execution import Strategy3ExecutionContext, execute_strategy3_decision
from aster_strategy3_status import strategy3_position_tp_contract
from aster_rapid_build import run_confirmed_batch
from aster_strategy2_execution import ExecutionContext, execute_decision as execute_aster_strategy2_decision
from aster_strategy2_runtime import owned_from_mapping, owned_to_mapping, recover_audited_ownership, portfolio_state as strategy2_portfolio_state
from aster_strategy2_runtime import next_management_decision, scanner_allowed, active_position_map
from aster_strategy2_runtime import changed_owned_symbols, most_urgent_profitable_owned
from aster_strategy2_runtime import enrich_confirmed_costs
from aster_strategy2_runtime import scheduler_status as strategy2_scheduler_status, strategy2_position_tp_contract
from aster_strategy2_runtime import remove_strategy3_proven_conflicts
from aster_strategy2_runtime import portfolio_protection_decision, same_pair_protection_decision
from aster_strategy2_runtime import balanced_entry_targets, harvest_counts, next_balanced_entry_side, entry_order_limit, management_preempts_initial_build
from aster_portfolio_replay import ReplayCandle, ReplaySeed, comparison_conclusion, config_with_overrides, run_portfolio_replay
from aster_strategy import Account as AsterStrategyAccount, Leg as AsterStrategyLeg, Pair as AsterStrategyPair
from aster_automation import TickMarket as AsterTickMarket, decide_tick as decide_aster_tick
from aster_execution import PairExecutionPlan, plan_pair as plan_aster_pair, execute_pair_once as execute_aster_pair
from aster_execution import execute_leg_once as execute_aster_leg, execute_harvest_reset as execute_aster_harvest
from aster_execution import execute_close_all as execute_aster_close_all
from aster_execution import configure_maximum_usable_leverage
from aster_execution import is_definite_contract_rejection
from aster_execution import contract_brackets, planning_brackets
from aster_state import (
    account_values as aster_account_values, reconcile_aster_state,
    account_information_values as aster_account_information_values,
    dashboard_snapshot as aster_dashboard_snapshot,
    infer_dca_level as infer_aster_dca_level,
    state_from_mapping as aster_state_from_mapping, state_to_mapping as aster_state_to_mapping,
)
from hyperliquid_scanner import (
    MarketSnapshot as HyperliquidMarketSnapshot,
    ScannerSettings as HyperliquidScannerSettings,
    add_on_due as hyperliquid_add_on_due,
    bollinger_position as hyperliquid_bollinger_position,
    choose_entries as choose_hyperliquid_entries,
    universe_matches as hyperliquid_universe_matches,
    select_candidates as select_hyperliquid_candidates,
)
from portfolio_risk import (
    ExchangeRiskSnapshot, PortfolioRiskLimits, evaluate_risk_increase,
)
from admin_platform import classify_bot_health, safe_recovery_plan, incident_key
from aster_strategy3 import account_entry_side
from hyperliquid_account_state import direction_available, normalize_hyperliquid_account_state
from firebase_identity import check_revoked_tokens, identity_app, recent_id_token
from read_only_source import read_source_url


if not firebase_admin._apps:
    firebase_admin.initialize_app()

# Staging can validate tokens from the established identity project while all
# application data remains in the isolated Google Cloud project selected by
# ADC/GOOGLE_CLOUD_PROJECT. This preserves user IDs without granting the
# staging runtime a write path to the production Firestore database.
data_project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
auth_project_id = os.getenv("FIREBASE_AUTH_PROJECT_ID", "").strip()
auth_app = identity_app(
    firebase_admin,
    data_project_id=data_project_id,
    auth_project_id=auth_project_id,
)

app = FastAPI(title="TradeMentor Cloud API", version="0.1.0")


@app.middleware("http")
async def existing_data_read_bridge(request: Request, call_next: Any) -> Response:
    """Expose existing account snapshots in staging without a production write path."""

    source = os.getenv("TRADEMENTOR_READ_SOURCE_URL", "").strip()
    target = read_source_url(
        source,
        request.method,
        request.url.path,
        request.url.query,
    )
    if not target:
        return await call_next(request)
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Firebase ID-token ontbreekt")
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            upstream = await client.request(
                request.method,
                target,
                headers={"Authorization": authorization},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Alleen-lezen databron is tijdelijk niet bereikbaar") from exc
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json").split(";", 1)[0],
        headers={"X-TradeMentor-Data-Mode": "existing-read-only"},
    )


db = firestore.client()
info = Info(constants.MAINNET_API_URL, skip_ws=True)
secrets_client = secretmanager.SecretManagerServiceClient()
tasks_client = tasks_v2.CloudTasksClient()
MAX_ONE_TEST_POSITION_USD = 12.0
MAX_MEXC_CANARY_NOTIONAL_USD = 8.50
MAX_SLIPPAGE = 0.01
_cache_lock = threading.RLock()
_perp_dex_cache: tuple[float, list[str]] = (0.0, [])
_positions_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_info_cache: dict[str, tuple[float, Any]] = {}
_aster_universe_cache: AsterUniverseSnapshot | None = None
_bitcoin_backtest_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_aster_closed_trades_cache: dict[str, tuple[float, list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]] = {}
_aster_strategy3_cost_cache: dict[str, tuple[float, dict[tuple[str, str], OwnedLeg]]] = {}


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
    take_profit_enabled: bool = True
    trailing_take_profit_enabled: bool = False
    trailing_deviation_percentage: float = Field(default=0.5, ge=0.1, le=10)
    stop_loss_enabled: bool = True
    top_universe_size: int = Field(default=50, ge=1, le=500)


class DcaAddOnRequest(BaseModel):
    idempotency_key: str = Field(min_length=12, max_length=160)
    symbol: str = Field(min_length=1, max_length=40)
    short: bool
    position_value_usd: float = Field(ge=10, le=100_000)
    leverage: int = Field(ge=1, le=100)
    signal_price: float = Field(gt=0)
    profit_percentage: float = Field(gt=0, le=25)
    strategy_id: str = Field(default="strategy_1", pattern="^strategy_[1-6]$")
    safety_order_index: int = Field(default=1, ge=1, le=20)
    max_safety_orders: int = Field(default=1, ge=1, le=20)
    max_deal_value_usd: float = Field(ge=20, le=1_000_000)
    max_adverse_percentage: float = Field(default=8.0, gt=0, le=25)
    take_profit_enabled: bool = True
    trailing_take_profit_enabled: bool = False
    trailing_deviation_percentage: float = Field(default=0.5, ge=0.1, le=10)
    stop_loss_enabled: bool = True


class LiveTradingToggleRequest(BaseModel):
    enabled: bool


class MexcCredentialRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=256)
    secret_key: str = Field(min_length=8, max_length=256)


class AsterCredentialRequest(BaseModel):
    signer_address: str = Field(min_length=42, max_length=42)
    private_key: str = Field(min_length=64, max_length=66)


class AsterWalletConnectRequest(BaseModel):
    address: str = Field(min_length=42, max_length=42)
    message: str = Field(min_length=20, max_length=1000)
    signature: str = Field(min_length=130, max_length=132)


class AsterDryRunRequest(BaseModel):
    pair_count: int = Field(default=5, ge=1, le=100)
    notional_per_leg_usd: float = Field(default=10.0, ge=5.0, le=1000.0)


class AsterStrategySettingsRequest(BaseModel):
    settings: dict[str, Any]


class AsterStrategyStartRequest(BaseModel):
    confirm: bool
    settings: dict[str, Any]


class AsterStrategyStopRequest(BaseModel):
    confirm: bool


class AsterCloseAllRequest(BaseModel):
    confirm: bool


class AsterCanaryRequest(BaseModel):
    confirm: bool
    notional_usd: float = Field(default=10.0, ge=5.0, le=12.0)


class AsterRapidBuildRequest(BaseModel):
    confirm: bool = False


class AsterPortfolioReplayRequest(BaseModel):
    test_a: dict[str, Any] = Field(default_factory=dict)
    test_b: dict[str, Any] = Field(default_factory=dict)


class MexcLiveToggleRequest(BaseModel):
    enabled: bool
    confirm: bool = False


class MexcCanaryRequest(BaseModel):
    confirm: bool
    idempotency_key: str = Field(min_length=16, max_length=120)
    maximum_notional_usd: float = Field(ge=6.0, le=MAX_MEXC_CANARY_NOTIONAL_USD)
    leverage: int = Field(ge=1, le=200)


class MexcAutomationSettingsRequest(BaseModel):
    settings: dict[str, Any]


class MexcAutomationStartRequest(BaseModel):
    confirm: bool
    settings: dict[str, Any]


class MexcAutomationStopRequest(BaseModel):
    confirm: bool


class ManualCloseRequest(BaseModel):
    confirm: bool
    percentage: int = Field(default=100, ge=25, le=100)


class BitcoinSignalRequest(BaseModel):
    duration_seconds: int


class BitcoinTradeOpenRequest(BaseModel):
    duration_seconds: int
    stake_usd: float
    short: bool
    confirm: bool
    idempotency_key: str = Field(min_length=12, max_length=160)


class BitcoinTradeCloseRequest(BaseModel):
    confirm: bool


class TradingCycleStartRequest(BaseModel):
    target_percentage: float = Field(default=10.0, ge=1.0, le=1000.0)
    portfolio_value: float | None = Field(default=None, ge=0.0)
    # Backwards compatibility for builds <= 2.49.
    available_to_trade: float | None = Field(default=None, ge=0.0)


class TradingCycleTargetRequest(BaseModel):
    target_percentage: float = Field(ge=1.0, le=1000.0)


class TradingCycleEvaluateRequest(BaseModel):
    portfolio_value: float | None = Field(default=None, ge=0.0)
    available_to_trade: float | None = Field(default=None, ge=0.0)


class HyperliquidScannerSettingsRequest(BaseModel):
    settings: dict[str, Any]


class HyperliquidScannerStartRequest(BaseModel):
    confirm: bool
    settings: dict[str, Any]


class HyperliquidScannerStopRequest(BaseModel):
    confirm: bool


class TpProtectionRequest(BaseModel):
    profit_percentage: float = Field(gt=0, le=25)
    max_adverse_percentage: float = Field(default=1.5, gt=0, le=25)
    strategy_id: str = Field(default="strategy_1", pattern="^strategy_[1-6]$")
    take_profit_enabled: bool = True
    trailing_take_profit_enabled: bool = False
    stop_loss_enabled: bool = True


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


class AdminIncidentUpdateRequest(BaseModel):
    status: str = Field(pattern="^(new|investigating|auto_recovery|waiting_user|resolved|not_reproducible|safety_blocked)$")
    note: str = Field(default="", max_length=2000)


class AdminUserActionRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)
    confirm: bool = False


class AdminDeviceEnrollRequest(BaseModel):
    device_id: str = Field(min_length=32, max_length=160)
    device_label: str = Field(default="Samsung Fold", min_length=3, max_length=240)
    confirm: bool = False


class AdminMfaVerifyRequest(BaseModel):
    device_id: str = Field(min_length=32, max_length=160)
    device_label: str = Field(default="Beheertoestel", min_length=3, max_length=240)
    code: str = Field(min_length=6, max_length=32)
    confirm: bool = False


class InterfacePreferenceRequest(BaseModel):
    mode: str = Field(pattern="^(legacy|premium)$")


def user_reference(user: dict[str, Any]):
    return db.collection("users").document(str(user["uid"]))


def mexc_secret_name(user: dict[str, Any]) -> str:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "tradementor-production")
    return f"projects/{project}/secrets/tradementor-mexc-{user['uid']}"


def aster_secret_name(user: dict[str, Any]) -> str:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "tradementor-production")
    return f"projects/{project}/secrets/tradementor-aster-{user['uid']}"


def load_aster_secret(user: dict[str, Any]) -> AsterSecret:
    try:
        response = secrets_client.access_secret_version(
            request={"name": f"{aster_secret_name(user)}/versions/latest"}
        )
        value = json.loads(response.payload.data.decode("utf-8"))
        return AsterSecret.create(str(value["signerAddress"]), str(value["privateKey"]))
    except Exception as exc:
        raise HTTPException(409, "Aster is nog niet veilig aan dit account gekoppeld") from exc


def inspect_aster(secret: AsterSecret) -> dict[str, Any]:
    client = AsterV3Client(
        signer_address=secret.signer_address,
        sign_message=local_eip712_signer(secret),
        live_authorized=False,
    )
    try:
        hedge_mode = client.position_mode()
        balances = client.account_balance()
        positions = client.position_risk()
        open_orders = client.open_orders()
        brackets = client.leverage_brackets()
        exchange_info = client.public_exchange_info()
    except (AsterApiError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    usdt = next((item for item in balances if str(item.get("asset", "")).upper() == "USDT"), {})
    active_positions = [item for item in positions if abs(safe_float(item.get("positionAmt"))) > 0]
    maintenance_margin = sum(safe_float(item.get("maintMargin", item.get("maintenanceMargin"))) for item in active_positions)
    equity, wallet_balance, available_balance, unrealized_pnl = aster_account_values(usdt, positions)
    tradable_symbols = [
        str(item.get("symbol", ""))
        for item in exchange_info.get("symbols", [])
        if str(item.get("status", "")).upper() == "TRADING"
    ]
    maximum_leverage = max(
        (int(safe_float(bracket.get("initialLeverage")))
         for row in brackets for bracket in (row.get("brackets") or [])),
        default=0,
    )
    return {
        "configured": True,
        "credentialsVerified": True,
        "hedgeMode": hedge_mode,
        "equity": equity,
        "walletBalance": wallet_balance,
        "availableBalance": available_balance,
        "unrealizedPnl": unrealized_pnl,
        "activePositions": len(active_positions),
        "maintenanceMargin": maintenance_margin,
        "marginRatio": maintenance_margin / equity if equity > 0 else (1.0 if active_positions else 0.0),
        "openOrders": len(open_orders),
        "tradableSymbols": len(tradable_symbols),
        "maximumLeverage": maximum_leverage,
        "liveReady": hedge_mode and bool(tradable_symbols),
        # No Aster order endpoint exists in this migration phase.
        "ordersEnabled": False,
    }


def store_aster_secret(user: dict[str, Any], secret: AsterSecret) -> None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "tradementor-production")
    parent = f"projects/{project}"
    secret_id = f"tradementor-aster-{user['uid']}"
    secret_name = f"{parent}/secrets/{secret_id}"
    try:
        secrets_client.create_secret(
            request={"parent": parent, "secret_id": secret_id, "secret": {"replication": {"automatic": {}}}}
        )
    except google_exceptions.AlreadyExists:
        pass
    payload = json.dumps({
        "signerAddress": secret.signer_address,
        "privateKey": secret.private_key,
    }).encode("utf-8")
    secrets_client.add_secret_version(request={"parent": secret_name, "payload": {"data": payload}})


def load_mexc_credentials(user: dict[str, Any]) -> MexcCredentials:
    try:
        response = secrets_client.access_secret_version(
            request={"name": f"{mexc_secret_name(user)}/versions/latest"}
        )
        value = json.loads(response.payload.data.decode("utf-8"))
        return MexcCredentials(str(value["apiKey"]), str(value["secretKey"]))
    except Exception as exc:
        raise HTTPException(409, "MEXC is nog niet veilig aan dit account gekoppeld") from exc


def inspect_mexc(credentials: MexcCredentials) -> dict[str, Any]:
    client = MexcClient(credentials)
    try:
        assets = client.assets()
        positions = client.open_positions("BTC_USDT")
        open_orders = client.open_orders("BTC_USDT")
        position_mode = client.position_mode()
        fees = client.fee_details("BTC_USDT")
        leverage_rows = client.leverage_details("BTC_USDT")
        contract = client.contract_detail("BTC_USDT")
        ticker = client.ticker("BTC_USDT")
    except MexcApiError as exc:
        raise HTTPException(409, str(exc)) from exc
    usdt = usdt_asset(assets)
    if usdt is None:
        raise HTTPException(409, "Geen USDT Futures-account bij MEXC gevonden")
    maximum_leverage = max((int(row.get("maxLeverageView", 0)) for row in leverage_rows), default=0)
    mark_price = safe_float(ticker.get("fairPrice", ticker.get("lastPrice", ticker.get("last"))))
    live_positions = normalized_positions(
        positions,
        mark_price=mark_price,
        contract=contract,
        account_equity=safe_float(usdt.get("equity")),
    )
    return {
        "configured": True,
        "credentialsVerified": True,
        "hedgeMode": position_mode == 1,
        "positionMode": position_mode,
        "equity": safe_float(usdt.get("equity")),
        "availableBalance": safe_float(usdt.get("availableBalance")),
        "availableOpen": safe_float(usdt.get("availableOpen")),
        "positionMargin": safe_float(usdt.get("positionMargin")),
        "unrealizedPnl": safe_float(usdt.get("unrealized")),
        "openBtcPositions": len(positions),
        "openBtcOrders": len(open_orders),
        "positions": live_positions,
        "makerFee": safe_float(fees.get("realMakerFee", fees.get("originalMakerFee"))),
        "takerFee": safe_float(fees.get("realTakerFee", fees.get("originalTakerFee"))),
        "maximumLeverage": maximum_leverage,
        "executionLeverage": 200,
        "executionMarginMode": "cross",
        "automationExecutionEnabled": os.getenv("MEXC_AUTOMATION_EXECUTION_ENABLED", "false").lower() == "true",
        "liveReady": position_mode == 1 and safe_float(usdt.get("availableOpen")) > 0 and maximum_leverage >= 200 and len(open_orders) == 0,
    }


def hyperliquid_scanner_reference(uid: str):
    return db.collection("hyperliquidScanners").document(uid)


def hyperliquid_scanner_public(uid: str) -> dict[str, Any]:
    value = hyperliquid_scanner_reference(uid).get().to_dict() or {}
    settings_value = value.get("settings") if isinstance(value.get("settings"), dict) else {}
    return {
        "scannerEnabled": bool(value.get("enabled", False)),
        "scannerMonitoring": bool(value.get("monitor", False)),
        "scannerProtectiveOnly": bool(value.get("protectiveOnly", False)),
        "scannerPhase": str(value.get("phase", "idle")),
        "scannerReason": str(value.get("lastReason", "Niet gestart")),
        "scannerLastTickAt": value.get("lastTickAt"),
        "scannerNextTickAt": value.get("nextTickAt"),
        "scannerScannedMarkets": int(safe_float(value.get("scannedMarkets"))),
        "scannerCandidateCount": int(safe_float(value.get("candidateCount"))),
        "scannerOrdersPlaced": int(safe_float(value.get("ordersPlaced"))),
        "scannerRejectedCount": int(safe_float(value.get("rejectedCount"))),
        "scannerSettings": settings_value or HyperliquidScannerSettings().public_dict(),
    }


def _hyperliquid_meta_rows() -> list[dict[str, Any]]:
    response = httpx.post(
        f"{constants.MAINNET_API_URL}/info",
        json={"type": "metaAndAssetCtxs"}, timeout=12.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError("Hyperliquid-marktmetadata is onvolledig")
    universe = (payload[0] or {}).get("universe", [])
    contexts = payload[1] if isinstance(payload[1], list) else []
    rows: list[dict[str, Any]] = []
    for market, context in zip(universe, contexts):
        if bool((market or {}).get("isDelisted", False)):
            continue
        name = str((market or {}).get("name", "")).strip()
        mark = safe_float((context or {}).get("markPx"))
        previous = safe_float((context or {}).get("prevDayPx"))
        leverage = max(1, int(safe_float((market or {}).get("maxLeverage")) or 1))
        if name and mark > 0 and previous > 0:
            rows.append({"symbol": name, "mark": mark, "previous": previous, "leverage": leverage})
    if not rows:
        raise ValueError("Hyperliquid retourneerde geen bruikbare markten")
    return rows


def _hyperliquid_closed_closes(symbol: str, *, count: int = 20) -> tuple[float, ...]:
    now_ms = int(time.time() * 1000)
    response = httpx.post(
        f"{constants.MAINNET_API_URL}/info",
        json={"type": "candleSnapshot", "req": {
            "coin": symbol, "interval": "1m",
            "startTime": now_ms - max(count + 5, 25) * 60_000,
            "endTime": now_ms,
        }}, timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()
    values = []
    for candle in payload if isinstance(payload, list) else []:
        close_time = int(safe_float((candle or {}).get("T")))
        close = safe_float((candle or {}).get("c"))
        if close_time <= now_ms and close > 0:
            values.append(close)
    return tuple(values[-count:])


def _hyperliquid_market_batch(user: dict[str, Any], settings: HyperliquidScannerSettings,
                              cursor: int, active_symbols: set[str] | None = None) -> tuple[list[HyperliquidMarketSnapshot], set[str], int, int]:
    del user
    universe = aster_usdt_universe_snapshot(settings.top_universe_size).public_dict()
    if universe["entryBlocked"]:
        raise ValueError(str(universe["entryBlockReason"]))
    allowed = {str(symbol).upper().removesuffix("USDT") for symbol in universe["selectedSymbols"]}
    rows = _hyperliquid_meta_rows()
    eligible = [
        row for row in rows
        if hyperliquid_universe_matches(str(row["symbol"]), allowed)
    ]
    eligible.sort(key=lambda row: -abs((row["mark"] / row["previous"] - 1.0) * 100.0))
    if settings.entry_mode == "direct":
        selected_rows = eligible
        next_cursor = 0
    else:
        batch_size = min(80, max(20, settings.max_active_deals * 2))
        start = cursor % max(1, len(eligible))
        selected_rows = (eligible + eligible)[start:start + min(batch_size, len(eligible))]
        next_cursor = (start + len(selected_rows)) % max(1, len(eligible))
    scanned_count = len(selected_rows)
    selected_names = {str(row["symbol"]).upper() for row in selected_rows}
    for row in rows:
        if str(row["symbol"]).upper() in (active_symbols or set()) and str(row["symbol"]).upper() not in selected_names:
            selected_rows.append(row)
            selected_names.add(str(row["symbol"]).upper())
    markets: list[HyperliquidMarketSnapshot] = []
    for row in selected_rows:
        closes: tuple[float, ...] = ()
        if settings.entry_mode == "bollinger":
            try:
                closes = _hyperliquid_closed_closes(str(row["symbol"]))
            except Exception:
                continue
        markets.append(HyperliquidMarketSnapshot(
            symbol=str(row["symbol"]), mark_price=float(row["mark"]),
            previous_day_price=float(row["previous"]), max_leverage=int(row["leverage"]),
            closed_one_minute_closes=closes,
        ))
    return markets, allowed, scanned_count, next_cursor


def _hyperliquid_info_value(payload: dict[str, Any], ttl: float = 2.0) -> Any:
    cache_key = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    now = time.monotonic()
    with _cache_lock:
        cached = _info_cache.get(cache_key)
        if cached and now - cached[0] < ttl:
            return cached[1]
        try:
            response = httpx.post("https://api.hyperliquid.xyz/info", json=payload, timeout=15.0)
            response.raise_for_status()
            value = response.json()
            _info_cache[cache_key] = (time.monotonic(), value)
            return value
        except (httpx.HTTPError, ValueError) as exc:
            if cached and now - cached[0] < max(30.0, ttl):
                return cached[1]
            raise HTTPException(502, "Hyperliquid-accountgegevens zijn tijdelijk niet beschikbaar") from exc


def _hyperliquid_account_truth(address: str, *, asset: str = "BTC") -> dict[str, Any]:
    clearing = _hyperliquid_info_value({"type": "clearinghouseState", "user": address})
    spot = _hyperliquid_info_value({"type": "spotClearinghouseState", "user": address})
    abstraction = _hyperliquid_info_value({"type": "userAbstraction", "user": address}, ttl=30.0)
    active = _hyperliquid_info_value({"type": "activeAssetData", "user": address, "coin": asset.upper()})
    return normalize_hyperliquid_account_state(clearing, spot, abstraction, active, asset=asset)


def _hyperliquid_risk_decision(address: str, requested_notional: float, day_start_equity: float,
                               *, symbol: str, short: bool):
    account = _hyperliquid_account_truth(address, asset=symbol)
    equity = safe_float(account.get("portfolioValue"))
    available = direction_available(account, short)
    used_margin = safe_float(account.get("totalMarginUsed"))
    maintenance = safe_float(account.get("maintenanceMargin"))
    positions = all_positions(address)
    gross = sum(abs(safe_float(item.get("positionValue"))) for item in positions)
    net = sum(abs(safe_float(item.get("positionValue"))) * (1 if safe_float(item.get("szi")) >= 0 else -1) for item in positions)
    distances: list[float] = []
    mids = info.all_mids()
    for item in positions:
        symbol = str(item.get("coin", ""))
        mark = safe_float(mids.get(symbol))
        liquidation = safe_float(item.get("liquidationPx"))
        if mark > 0 and liquidation > 0:
            distances.append(abs(mark - liquidation) / mark)
    minimum_distance = min(distances) if distances else 1.0
    snapshot = ExchangeRiskSnapshot(
        exchange="hyperliquid", equity=equity, available_balance=available,
        gross_exposure=gross, net_exposure=net, used_margin=used_margin,
        maintenance_margin=maintenance, minimum_liquidation_distance=minimum_distance,
        captured_at_ms=int(time.time() * 1000),
    )
    return evaluate_risk_increase(
        [snapshot], requested_exchange="hyperliquid", requested_notional=requested_notional,
        now_ms=int(time.time() * 1000), day_start_equity=day_start_equity or equity,
        limits=PortfolioRiskLimits(maximum_single_exchange_share=1.0),
    )


def _hyperliquid_scanner_settings(value: dict[str, Any] | None) -> HyperliquidScannerSettings:
    settings = HyperliquidScannerSettings.from_dict(value)
    if errors := settings.validate():
        raise HTTPException(422, "; ".join(errors))
    return settings


def _datetime_is_recent(value: Any, seconds: int) -> bool:
    if not isinstance(value, datetime):
        return False
    candidate = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - candidate.astimezone(timezone.utc)).total_seconds() < seconds


def _hyperliquid_deals(reference) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for snapshot in reference.collection("dcaDeals").stream():
        value = snapshot.to_dict() or {}
        symbol = str(value.get("symbol", "")).strip().upper()
        if symbol and str(value.get("strategyId", "")) == "strategy_3":
            result[symbol] = value
    return result


def _scanner_action_payload(kind: str, symbol: str, short: bool, price: float, reason: str,
                            *, safety_order_index: int = 0, leverage: int = 1) -> dict[str, Any]:
    return {
        "kind": kind, "symbol": symbol, "short": short, "signalPrice": price,
        "reason": reason, "safetyOrderIndex": safety_order_index, "leverage": leverage,
    }


def _run_hyperliquid_scanner_tick(uid: str, *, dry_run: bool = False,
                                  ignore_monitor: bool = False,
                                  settings_override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Plan one tenant's DCA Pulse tick and execute only after every live gate passes.

    Dry-run is side-effect free with respect to orders. It may cache public market
    data, but never loads an agent key and never invokes an execution endpoint.
    """
    control_ref = hyperliquid_scanner_reference(uid)
    control = control_ref.get().to_dict() or {}
    if not ignore_monitor and not bool(control.get("monitor", False)):
        return {"uid": uid, "status": "idle", **hyperliquid_scanner_public(uid)}
    settings = _hyperliquid_scanner_settings(settings_override or control.get("settings"))
    next_tick = control.get("nextTickAt")
    if (not dry_run and not ignore_monitor and str(control.get("phase", "")) == "full"
            and isinstance(next_tick, datetime) and next_tick > datetime.now(timezone.utc)):
        return {
            "uid": uid, "status": "capacity-sleep",
            "reason": "Capaciteit was gevuld; wacht op de ingestelde hercontrole",
            **hyperliquid_scanner_public(uid),
        }
    user = {"uid": uid}
    reference = user_reference(user)
    address = linked_wallet(user)
    positions = list(all_positions(address, force=True))
    active_symbols = {str(item.get("coin", "")).upper() for item in positions}
    long_count = sum(safe_float(item.get("szi")) > 0 for item in positions)
    short_count = sum(safe_float(item.get("szi")) < 0 for item in positions)
    account_truth = _hyperliquid_account_truth(address)
    equity = safe_float(account_truth.get("portfolioValue"))
    today = datetime.now(timezone.utc).date().isoformat()
    day_start_equity = safe_float(control.get("dayStartEquity"))
    if str(control.get("dayStartDate", "")) != today or day_start_equity <= 0:
        day_start_equity = equity

    cursor = int(safe_float(control.get("marketCursor")))
    markets, allowed, scanned, next_cursor = _hyperliquid_market_batch(user, settings, cursor, active_symbols)
    market_map = {item.symbol.upper(): item for item in markets}
    if settings.entry_mode == "direct":
        # Direct mode receives every Hyperliquid market from the batch helper.
        market_map = {item.symbol.upper(): item for item in markets}
    deals = _hyperliquid_deals(reference)
    planned: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    # Existing DCA Pulse positions remain eligible after falling out of Top-N.
    # Only their original direction and the fixed ladder from initialEntryPrice count.
    for position in positions:
        symbol = str(position.get("coin", "")).upper()
        deal = deals.get(symbol)
        if not deal:
            continue
        row = market_map.get(symbol)
        if row is None:
            rejected.append({"symbol": symbol, "reason": "Actuele DCA-prijs ontbreekt"})
            continue
        short = safe_float(position.get("szi")) < 0
        completed = int(safe_float(deal.get("safetyOrdersCompleted")))
        initial = safe_float(deal.get("initialEntryPrice")) or safe_float(position.get("entryPx"))
        if _datetime_is_recent(deal.get("updatedAt"), settings.cooldown_minutes * 60):
            continue
        if hyperliquid_add_on_due(short=short, current_price=row.mark_price,
                                  initial_entry_price=initial,
                                  safety_orders_completed=completed, settings=settings):
            risk = _hyperliquid_risk_decision(
                address, settings.base_order_usd, day_start_equity, symbol=symbol, short=short,
            )
            if risk.approved:
                planned.append(_scanner_action_payload(
                    "add_on", row.symbol, short, row.mark_price,
                    f"DCA-laag {completed + 1}/{settings.max_safety_orders} vanaf oorspronkelijke instap",
                    safety_order_index=completed + 1,
                    leverage=max(1, min(settings.leverage, row.max_leverage)),
                ))
            else:
                rejected.append({"symbol": symbol, "reason": "; ".join(risk.reasons)})

    candidates = select_hyperliquid_candidates(
        markets, allowed_symbols=allowed, active_symbols=active_symbols, settings=settings,
    )
    entries = choose_hyperliquid_entries(
        candidates, active_count=len(positions), maximum=settings.max_active_deals,
        long_count=long_count, short_count=short_count,
    )
    for candidate in entries:
        risk = _hyperliquid_risk_decision(
            address, settings.base_order_usd, day_start_equity,
            symbol=candidate.symbol, short=candidate.short,
        )
        if risk.approved:
            planned.append(_scanner_action_payload(
                "entry", candidate.symbol, candidate.short, candidate.price, candidate.reason,
                leverage=candidate.leverage,
            ))
        else:
            rejected.append({"symbol": candidate.symbol, "reason": "; ".join(risk.reasons)})

    base_result = {
        "uid": uid, "status": "simulated" if dry_run else "planned",
        "activePositions": len(positions), "maxActiveDeals": settings.max_active_deals,
        "longs": long_count, "shorts": short_count, "scannedMarkets": scanned,
        "candidateCount": len(candidates), "actions": planned, "rejected": rejected,
        "settings": settings.public_dict(), "dayStartEquity": day_start_equity,
    }
    if dry_run:
        return base_result

    if not bool(control.get("enabled", False)):
        control_ref.set({
            "phase": "monitoring", "lastReason": "Scanner staat persoonlijk uit",
            "lastTickAt": datetime.now(timezone.utc), "marketCursor": next_cursor,
        }, merge=True)
        return {**base_result, "status": "personally-disabled"}
    live = reference.collection("executionControls").document("liveTrading").get().to_dict() or {}
    if not bool(live.get("enabled", False)) or os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        control_ref.set({
            "enabled": False, "phase": "locked", "lastReason": "Persoonlijke of centrale livehandel staat uit",
            "lastTickAt": datetime.now(timezone.utc), "marketCursor": next_cursor,
        }, merge=True)
        return {**base_result, "status": "live-locked"}

    placed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    slot = int(time.time() // max(60, settings.cooldown_minutes * 60))
    for index, action in enumerate(planned[:12]):
        try:
            if action["kind"] == "entry":
                response = live_entry_order(LiveEntryOrderRequest(
                    idempotency_key=f"hlscan:{uid}:{slot}:entry:{action['symbol']}",
                    symbol=action["symbol"], short=bool(action["short"]),
                    position_value_usd=settings.base_order_usd, leverage=int(action["leverage"]),
                    signal_price=float(action["signalPrice"]), profit_percentage=1.5,
                    max_adverse_percentage=settings.stop_loss_percent,
                    strategy_id=settings.strategy_id, take_profit_enabled=False,
                    trailing_take_profit_enabled=False, stop_loss_enabled=settings.stop_loss_enabled,
                    top_universe_size=settings.top_universe_size,
                ), user=user)
            else:
                response = dca_add_on(DcaAddOnRequest(
                    idempotency_key=f"hlscan:{uid}:{slot}:dca:{action['symbol']}:{action['safetyOrderIndex']}",
                    symbol=action["symbol"], short=bool(action["short"]),
                    position_value_usd=settings.base_order_usd, leverage=int(action["leverage"]),
                    signal_price=float(action["signalPrice"]), profit_percentage=1.5,
                    strategy_id=settings.strategy_id, safety_order_index=int(action["safetyOrderIndex"]),
                    max_safety_orders=settings.max_safety_orders,
                    max_deal_value_usd=settings.base_order_usd * (settings.max_safety_orders + 1),
                    max_adverse_percentage=settings.stop_loss_percent,
                    take_profit_enabled=False, trailing_take_profit_enabled=False,
                    stop_loss_enabled=settings.stop_loss_enabled,
                ), user=user)
            placed.append({"kind": action["kind"], "symbol": action["symbol"], "result": response})
        except HTTPException as exc:
            failures.append({"kind": action["kind"], "symbol": action["symbol"], "reason": str(exc.detail)})
            if exc.status_code >= 500 or exc.status_code in {401, 403, 423}:
                break

    now = datetime.now(timezone.utc)
    full = len(positions) + sum(item["kind"] == "entry" for item in placed) >= settings.max_active_deals
    reason = (
        f"Capaciteit gevuld ({settings.max_active_deals})" if full else
        f"{len(placed)} order(s) bevestigd" if placed else
        (failures[0]["reason"] if failures else "Geen kandidaat door alle livecontroles")
    )
    control_ref.set({
        "phase": "full" if full else "waiting", "lastReason": reason,
        "lastTickAt": now, "nextTickAt": now + timedelta(minutes=settings.cooldown_minutes),
        "marketCursor": next_cursor, "scannedMarkets": scanned,
        "candidateCount": len(candidates), "ordersPlaced": len(placed),
        "rejectedCount": len(rejected) + len(failures), "lastFailures": failures[:20],
        "dayStartDate": today, "dayStartEquity": day_start_equity, "updatedAt": now,
    }, merge=True)
    return {**base_result, "status": "ok", "placed": placed, "failures": failures, "reason": reason}


def mexc_automation_reference(uid: str):
    return db.collection("mexcAutomation").document(uid)


def aster_automation_reference(uid: str):
    return db.collection("asterAutomation").document(uid)


def aster_strategy2_reference(uid: str):
    return db.collection("asterStrategy2").document(uid)


def aster_strategy3_reference(uid: str):
    return db.collection("asterStrategy3").document(uid)


def _record_aster_order_attribution(ref: Any, result: dict[str, Any], *, strategy_id: str,
                                     strategy_name: str, cycle_id: str, config_version: int,
                                     symbol: str, side: str, action: str) -> None:
    """Persist the exchange order identity used later by Aster fill history."""
    order_id = str(result.get("orderId", result.get("orderID", ""))).strip()
    client_order_id = str(result.get("clientOrderId", result.get("clientOrderID", ""))).strip()
    if not order_id and not client_order_id:
        return
    current = ref.get().to_dict() or {}
    rows = [row for row in current.get("orderAttributions", []) if isinstance(row, dict)]
    identity = (order_id, client_order_id)
    rows = [row for row in rows if (str(row.get("orderId", "")), str(row.get("clientOrderId", ""))) != identity]
    rows.append({"orderId":order_id,"clientOrderId":client_order_id,"strategyId":strategy_id,
        "strategyName":strategy_name,"cycleId":cycle_id,"configVersion":config_version,
        "symbol":symbol,"side":side,"action":action,"recordedAt":datetime.now(timezone.utc)})
    ref.set({"orderAttributions":rows[-2000:]}, merge=True)


def _configured_universe_contract(raw: dict[str, Any], requested_top_n: int) -> dict[str, Any]:
    stored = raw.get("universe") if isinstance(raw.get("universe"), dict) else None
    if stored and int(safe_float(stored.get("requestedTopN"))) == requested_top_n:
        value=dict(stored);expires=value.get("expiresAt")
        try:
            expiry=expires if isinstance(expires,datetime) else datetime.fromisoformat(str(expires).replace("Z","+00:00"))
            if datetime.now(timezone.utc)>=expiry.astimezone(timezone.utc):
                value.update({"stale":True,"entryBlocked":True,
                    "entryBlockReason":"Aster-universumcache is verlopen; nieuwe instappen zijn geblokkeerd"})
        except (TypeError,ValueError):
            value.update({"stale":True,"entryBlocked":True,
                "entryBlockReason":"Geldigheid van Aster-universumdata ontbreekt; nieuwe instappen zijn geblokkeerd"})
        return value
    cached = _aster_universe_cache
    if cached and datetime.now(timezone.utc)<cached.expires_at:
        return replace(cached,requested_top_n=requested_top_n).public_dict()
    now = datetime.now(timezone.utc)
    empty = build_aster_universe_snapshot({"symbols": []}, [], requested_top_n, fetched_at=now)
    return replace(empty, stale=True, entry_block_reason="Aster-universum is nog niet server-side ververst; nieuwe instappen zijn geblokkeerd").public_dict()


def aster_strategy3_public(uid: str) -> dict[str, Any]:
    raw = aster_strategy3_reference(uid).get().to_dict() or {}
    settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else Strategy3Config().public_dict()
    owned = [x for x in raw.get("ownedLegs", []) if isinstance(x, dict)]
    roles = [str(x.get("role", "HARVEST")) for x in owned]
    account_snapshot = raw.get("accountSnapshot") if isinstance(raw.get("accountSnapshot"), dict) else {}
    universe = _configured_universe_contract(raw, int(settings.get("universeTopN", 100)))
    return {"strategy3": {"settings": settings, "effectiveLiveSettings": settings, "universe": universe,
        "settingsSource": "server", "phase": str(raw.get("phase", "DRAFT")),
        "enabled": bool(raw.get("enabled",False)), "liveReady": bool(raw.get("liveReady",False)),
        "paperOnly": not bool(raw.get("canaryValidated",False)), "canaryValidated":bool(raw.get("canaryValidated",False)),
        "configVersion": int(safe_float(raw.get("configVersion", settings.get("version", 1)))),
        "lastReason": str(raw.get("lastReason", "Nieuw — simulatie; standaard uit")),
        "lastSimulation": raw.get("lastSimulation") if isinstance(raw.get("lastSimulation"), dict) else None,
        "lastTickAt":raw.get("lastTickAt"), "activeTrades":len(owned),
        "accountActivePositions":int(safe_float(account_snapshot.get("accountActivePositions"))),
        "activePairs":len({str(x.get("symbol", "")) for x in owned}),
        "longLegs":sum(1 for x in owned if x.get("side")=="LONG"),
        "shortLegs":sum(1 for x in owned if x.get("side")=="SHORT"),
        "harvestLegs":sum(1 for x in roles if x=="HARVEST"),
        "shieldLegs":sum(1 for x in roles if x in {"PROTECTION","HARVEST_PROTECTION"}),
        "trailingActive":len(raw.get("trailingPeaks", {}) if isinstance(raw.get("trailingPeaks"),dict) else {}),
        "trailingBlocked":0, "unassignedPositions":int(safe_float(raw.get("unassignedPositions")))}}


def _read_strategy3_cost_evidence(uid: str, client: AsterV3Client, owned: list[OwnedLeg],
                                  *, now: datetime) -> dict[tuple[str, str], OwnedLeg]:
    """Read fee/funding evidence for Positions; never persist or place orders."""
    with _cache_lock:
        cached = _aster_strategy3_cost_cache.get(uid)
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
    trades: list[dict[str, Any]] = []
    income: list[dict[str, Any]] = []
    refreshed_symbols: set[str] = set()
    legs_by_symbol:dict[str,list[OwnedLeg]]={}
    for leg in owned:legs_by_symbol.setdefault(leg.symbol,[]).append(leg)
    for symbol, symbol_legs in sorted(legs_by_symbol.items()):
        start_time=min((leg.created_at_ms for leg in symbol_legs if leg.created_at_ms>0),default=0) or None
        try:
            values = client.user_trades(symbol, start_time=start_time, limit=1000)
            symbol_income = client.income_history(symbol=symbol, start_time=start_time, limit=1000)
        except (AsterApiError, AsterSubmissionUncertain, AsterValidationError, ValueError):
            continue
        rows=[row for row in values if isinstance(row,dict)] if isinstance(values,list) else []
        every_leg_has_fill=all(any(str(row.get("positionSide","")).upper()==leg.side and
            int(safe_float(row.get("time",row.get("timestamp",0))))>=leg.created_at_ms for row in rows)
            for leg in symbol_legs)
        history_complete=isinstance(values,list) and len(values)<1000 and isinstance(symbol_income,list) and len(symbol_income)<1000
        if every_leg_has_fill and history_complete:
            trades.extend(rows)
            income.extend(row for row in symbol_income if isinstance(row,dict))
            refreshed_symbols.add(symbol)
    checked_at_ms = int(now.timestamp() * 1000)
    enriched = enrich_confirmed_costs(owned, trades, income,
        refreshed_symbols=refreshed_symbols, checked_at_ms=checked_at_ms)
    result = {(leg.symbol, leg.side): leg for leg in enriched}
    with _cache_lock:
        _aster_strategy3_cost_cache[uid] = (time.monotonic(), result)
    return result


def _explicit_strategy1_owned_keys(raw: dict[str, Any]) -> set[tuple[str, str]]:
    """Read explicit Strategy-1 claims; an exchange snapshot is not ownership."""
    keys:set[tuple[str,str]]=set()
    rows=raw.get("ownedLegs") if isinstance(raw.get("ownedLegs"),list) else []
    for row in rows:
        if not isinstance(row,dict):continue
        strategy_id=str(row.get("strategy_id",row.get("strategyId",""))).lower()
        engine_type=str(row.get("engine_type",row.get("engineType",""))).lower()
        if strategy_id not in {"aster-strategy-1","strategy_1"} or engine_type not in {"strategy1","strategy_1"}:continue
        symbol=str(row.get("symbol","")).upper();side=str(row.get("side","")).upper()
        if symbol and side in {"LONG","SHORT"}:keys.add((symbol,side))
    return keys


def _aster_owned_keys(uid: str) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Return only explicit Strategy-1 and Strategy-2 ownership claims."""
    s1_raw=aster_automation_reference(uid).get().to_dict() or {};s1=_explicit_strategy1_owned_keys(s1_raw)
    s2_raw=aster_strategy2_reference(uid).get().to_dict() or {};s2=set()
    for row in s2_raw.get("ownedLegs",[]) if isinstance(s2_raw.get("ownedLegs"),list) else []:
        try:
            leg=owned_from_mapping(row);s2.add((leg.symbol,leg.side))
        except (TypeError,ValueError):pass
    return s1,s2


def _run_aster_strategy3_tick(uid:str,*,dry_run:bool=False)->dict[str,Any]:
    """One fail-closed S3 tick; the exchange remains source of truth."""
    ref=aster_strategy3_reference(uid);raw=ref.get().to_dict() or {};now=datetime.now(timezone.utc)
    persisted_settings=raw.get("settings") if isinstance(raw.get("settings"),dict) else {}
    canary_doc=ref.collection("canaries").document("s3-open-fill-close-v1").get().to_dict() or {}
    settings=replace(Strategy3Config.from_mapping(persisted_settings),mode=strategy3_persisted_runtime_mode(persisted_settings,canary_doc))
    enabled=bool(raw.get("enabled",False));monitor=bool(raw.get("monitor",False))
    if not monitor and not dry_run:return {"status":"stopped","reason":"Strategy 3 monitoring staat uit","ordersSent":0}
    gates=(os.getenv("ASTER_LIVE_EXECUTION_ENABLED","false").lower()=="true" and
        os.getenv("ASTER_STRATEGY3_LIVE_ENABLED","false").lower()=="true" and
        os.getenv("ASTER_STRATEGY3_RUNTIME_ENABLED","false").lower()=="true" and
        strategy3_account_canary_proven(raw,canary_doc))
    live=settings.mode=="live" and enabled and not dry_run
    if live and (not gates or not raw.get("canaryValidated") or not raw.get("liveReady")):
        return {"status":"blocked","reason":"Strategy 3 live-gates of canary zijn niet volledig vrijgegeven","ordersSent":0}
    secret=load_aster_secret({"uid":uid});client=AsterV3Client(signer_address=secret.signer_address,
        sign_message=local_eip712_signer(secret),live_authorized=live)
    try:hedge=client.position_mode();account=client.account_information();positions=client.position_risk();orders=client.open_orders()
    except (AsterApiError,ValueError) as exc:
        ref.set({"phase":"DATA_HOLD","lastReason":str(exc),"lastTickAt":now},merge=True)
        return {"status":"data-hold","reason":str(exc),"ordersSent":0}
    if not hedge:return {"status":"blocked","reason":"Aster Hedge Mode staat uit","ordersSent":0}
    if orders:return {"status":"reconciling","reason":"Open Aster-orders worden eerst gereconcilieerd","ordersSent":0}
    owned=[]
    for item in raw.get("ownedLegs",[]) if isinstance(raw.get("ownedLegs"),list) else []:
        try:
            leg=owned_from_mapping(item)
            if leg.strategy_id=="aster-strategy-3" and leg.engine_type=="strategy3":owned.append(leg)
        except (TypeError,ValueError):pass
    s1_keys,s2_keys=_aster_owned_keys(uid);s3_keys={(x.symbol,x.side) for x in owned}
    if s3_keys & (s1_keys|s2_keys):
        return {"status":"blocked","reason":"Strategy 3 ownership botst met een bestaande strategie","ordersSent":0}
    posmap=active_position_map(positions);active_keys=set(posmap);known=s1_keys|s2_keys|s3_keys
    unknown=active_keys-known
    if unknown:
        ref.set({"phase":"RECONCILING","unassignedPositions":len(unknown),"lastReason":"Actieve exposure zonder bewezen ownership","lastTickAt":now},merge=True)
        return {"status":"reconciling","reason":"Actieve exposure zonder bewezen ownership","ordersSent":0}
    fills=[];income=[]
    try:
        changed_symbols = changed_owned_symbols(owned, positions)
        for symbol in sorted(changed_symbols):fills.extend(client.user_trades(symbol,limit=500))
        if changed_symbols:
            income=client.income_history(limit=500)
        s3_positions=[row for key,row in posmap.items() if key in s3_keys]
        recovery=reconcile_owned_legs(persisted=owned,positions=s3_positions,open_orders=[],fills=fills,
            exchange_reliable=True,strategy_label="Strategy-3")
    except (AsterApiError,ValueError) as exc:
        return {"status":"data-hold","reason":f"Strategy-3 recovery niet betrouwbaar: {exc}","ordersSent":0}
    if not recovery.allow_risk_increase:
        ref.set({"phase":"RECONCILING","lastReason":"; ".join(recovery.reasons),"lastTickAt":now},merge=True)
        return {"status":"reconciling","reason":"; ".join(recovery.reasons),"ordersSent":0}
    for event in recovery.audit:ref.collection("audit").add({**event,"timestamp":now})
    owned=(enrich_confirmed_costs(list(recovery.legs),fills,income)
        if fills or income else list(recovery.legs));s3_keys={(x.symbol,x.side) for x in owned}
    wallet=safe_float(account.get("totalWalletBalance"));unreal=safe_float(account.get("totalUnrealizedProfit"))
    equity=safe_float(account.get("totalMarginBalance")) or wallet+unreal;maint=safe_float(account.get("totalMaintMargin"))
    long_exp=sum(abs(safe_float(x.get("positionAmt")))*safe_float(x.get("markPrice")) for x in positions if str(x.get("positionSide")).upper()=="LONG")
    short_exp=sum(abs(safe_float(x.get("positionAmt")))*safe_float(x.get("markPrice")) for x in positions if str(x.get("positionSide")).upper()=="SHORT")
    strategy_margin=sum(abs(safe_float(posmap.get((x.symbol,x.side),{}).get("positionAmt")))*safe_float(posmap.get((x.symbol,x.side),{}).get("markPrice"))/max(1,safe_float(posmap.get((x.symbol,x.side),{}).get("leverage")) or settings.leverage) for x in owned)
    hwm=max(safe_float(raw.get("adjustedHighWaterMark")),equity)
    portfolio=Strategy3PortfolioState(equity,hwm,maint/equity if equity>0 else 1,long_exp,short_exp,strategy_margin)
    peaks=dict(raw.get("trailingPeaks") or {}) if isinstance(raw.get("trailingPeaks"),dict) else {}
    action_cooldowns=dict(raw.get("actionCooldowns") or {}) if isinstance(raw.get("actionCooldowns"),dict) else {}
    now_ms=int(time.time()*1000)
    # A contract can temporarily reject a risk-increasing DCA because its
    # account/symbol notional cap is already reached.  Do not let that one leg
    # monopolise every following scheduler tick.  Risk-reducing closes are
    # deliberately never suppressed by this cooldown.
    action_cooldowns={key:value for key,value in action_cooldowns.items() if safe_float(value)>now_ms}
    priority={"ASSIGN_PROTECTION":0,"PARTIAL_TP":1,"TRAILING_TP":1,"FULL_TP":1,"ADD_DCA":2,"ARM_TRAILING":3,"HOLD":9};choices=[]
    for leg in owned:
        row=posmap.get((leg.symbol,leg.side))
        if not row:continue
        mark=safe_float(row.get("markPrice"));size=abs(safe_float(row.get("positionAmt")))*mark;key=f"{leg.symbol}|{leg.side}"
        state=Strategy3LegState(leg.side,size,safe_float(row.get("entryPrice")) or leg.weighted_entry,mark,leg.dca_count,
            safe_float(row.get("unRealizedProfit",row.get("unrealizedProfit"))),leg.fees,leg.funding,leg.role,
            safe_float(peaks.get(key)) if key in peaks else None)
        decision=decide_strategy3(settings,state,portfolio,close_fee=size*.0005)
        # Arming/updating trailing is bookkeeping, not an exchange action. Persist the
        # peak, but do not let it monopolise this tick or block rapid start entries.
        # A later tick can still select TRAILING_TP when the configured pullback occurs.
        if decision.kind=="ARM_TRAILING":
            peaks[key]=max(strategy3_net_return(state),safe_float(peaks.get(key)))
            continue
        if decision.kind=="ADD_DCA" and safe_float(action_cooldowns.get(f"{key}|ADD_DCA"))>now_ms:
            continue
        choices.append((priority.get(decision.kind,8),leg,state,decision))
    choices.sort(key=lambda x:x[0]);selected=choices[0] if choices and choices[0][3].kind!="HOLD" else None
    snapshot={"equity":equity,"highWaterMark":hwm,"drawdown":portfolio.drawdown,"marginRatio":portfolio.margin_ratio,
        "longExposure":long_exp,"shortExposure":short_exp,"strategyMargin":strategy_margin,"activeTrades":len(owned),"capturedAt":now}
    snapshot["accountActivePositions"] = len(active_keys)
    ref.set({"accountSnapshot":snapshot,"adjustedHighWaterMark":hwm,"ownedLegs":[owned_to_mapping(x) for x in owned],"unassignedPositions":0,"lastTickAt":now},merge=True)
    if selected:
        _,leg,state,decision=selected;key=f"{leg.symbol}|{leg.side}"
        if decision.kind=="ASSIGN_PROTECTION":
            owned=[replace(x,role="PROTECTION") if x==leg else x for x in owned]
            ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"trailingPeaks":peaks,"phase":"PROTECTION","lastReason":decision.reason},merge=True)
            return {"status":"ok","action":decision.kind,"ordersSent":0}
        if decision.kind=="ADD_DCA" and (not enabled or portfolio.margin_ratio>=settings.defensive_margin_ratio):
            return {"status":"waiting","action":"HOLD","reason":"DCA geblokkeerd door stop- of risicomodus","ordersSent":0}
        try:
            row=posmap[(leg.symbol,leg.side)];mark=safe_float(row.get("markPrice"));qty=abs(Decimal(str(row.get("positionAmt"))))
            plan=PairExecutionPlan(leg.symbol,qty,qty*Decimal(str(mark)),max(1,int(safe_float(row.get("leverage")))))
            if decision.kind=="ADD_DCA":
                info={str(x.get("symbol","")).upper():x for x in client.public_exchange_info().get("symbols",[])}
                plan=plan_aster_pair(info[leg.symbol],planning_brackets(client,client.leverage_brackets(),leg.symbol,settings.leverage),mark,decision.notional)
                plan=replace(plan,leverage=configure_maximum_usable_leverage(client,replace(plan,leverage=min(plan.leverage,settings.leverage))))
            if dry_run or not live:return {"status":"simulated","action":decision.kind,"ordersSent":0,"reason":decision.reason}
            context=Strategy3ExecutionContext(leg.cycle_id,settings.version,leg,True,True,gates)
            result=execute_strategy3_decision(client,decision,plan,context,risk_approved=lambda margin:
                portfolio.margin_ratio<settings.defensive_margin_ratio and strategy_margin+margin<=equity*settings.strategy_budget)
        except Exception as exc:
            # Aster -5018/-2027 and equivalent definite contract rejections
            # prove that no fill occurred.  For a risk-increasing DCA it is
            # therefore safe to cool down only this action and let subsequent
            # rapid-build ticks consider other free contracts.  Unknown order
            # outcomes and every risk-reducing close still fail closed.
            if decision.kind!="ADD_DCA" or not is_definite_contract_rejection(exc):
                raise
            cooldown_key=f"{key}|ADD_DCA"
            action_cooldowns[cooldown_key]=now_ms+30*60*1000
            reason=f"{leg.symbol} {leg.side} DCA tijdelijk overgeslagen: {exc}"
            ref.set({"actionCooldowns":action_cooldowns,"trailingPeaks":peaks,"phase":"RUNNING",
                "lastReason":reason,"lastTickAt":now},merge=True)
            ref.collection("audit").add({"event":"DCA_CONTRACT_REJECTION_SKIPPED","symbol":leg.symbol,
                "side":leg.side,"cycleId":leg.cycle_id,"reason":str(exc),"timestamp":now})
            return {"status":"ok","action":"DCA_SKIPPED","symbol":leg.symbol,"side":leg.side,
                "ordersSent":0,"reason":reason}
        rr=result[0].get("result",{});filled=safe_float(rr.get("executedQty")) or float(plan.quantity);price=safe_float(rr.get("avgPrice")) or mark
        _record_aster_order_attribution(ref,rr,strategy_id="aster-strategy-3",
            strategy_name=str(settings.name or "Strategy 3"),cycle_id=leg.cycle_id,
            config_version=settings.version,symbol=leg.symbol,side=leg.side,action=decision.kind)
        if decision.kind=="ADD_DCA":
            total=leg.quantity+filled;owned=[replace(x,quantity=total,weighted_entry=(leg.quantity*leg.weighted_entry+filled*price)/total,
                dca_count=leg.dca_count+1,last_order_at_ms=int(time.time()*1000)) if x==leg else x for x in owned]
        else:
            remaining=max(0,leg.quantity-filled);owned=[replace(x,quantity=remaining,role=decision.role) if x==leg and remaining>1e-12 else x for x in owned if x!=leg or remaining>1e-12]
            peaks.pop(key,None)
        ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"trailingPeaks":peaks,
            "actionCooldowns":action_cooldowns,"phase":"RUNNING","lastReason":decision.reason,"updatedAt":now},merge=True)
        ref.collection("audit").add({"event":decision.kind,"symbol":leg.symbol,"side":leg.side,"cycleId":leg.cycle_id,"timestamp":now})
        return {"status":"ok","action":decision.kind,"symbol":leg.symbol,"side":leg.side,"ordersSent":len(result)}
    if not enabled:
        ref.set({"trailingPeaks":peaks,"phase":"PROTECTIVE_ONLY","lastReason":"Strategy 3 staat veilig gestopt"},merge=True)
        return {"status":"waiting","action":"HOLD","ordersSent":0,"reason":"Strategy 3 staat veilig gestopt"}
    # maximumPositions is an account-wide safety ceiling. Existing manual,
    # legacy or other-strategy exposure consumes capacity even though Strategy 3
    # must never claim its ownership.
    account_side=account_entry_side(active_keys,settings.maximum_positions)
    if account_side is None:
        ref.set({"trailingPeaks":peaks,"phase":"RUNNING","rapidBuildRequested":False,
            "lastReason":f"Accountlimiet bereikt: {len(active_keys)} van {settings.maximum_positions} actieve posities"},merge=True)
        return {"status":"waiting","action":"HOLD","ordersSent":0,"reason":"Accountbrede positiegrens bereikt"}
    long_target,short_target=balanced_entry_targets(settings.maximum_positions);long_count,short_count=harvest_counts(owned)
    side=account_side
    if not side:
        ref.set({"trailingPeaks":peaks,"phase":"RUNNING","rapidBuildRequested":False,"lastReason":f"Doelbezetting bereikt: {long_count} LONG / {short_count} SHORT"},merge=True)
        return {"status":"waiting","action":"HOLD","ordersSent":0,"reason":"Doelbezetting bereikt"}
    if portfolio.margin_ratio>=settings.caution_margin_ratio or strategy_margin+settings.base_notional/max(1,settings.leverage)>equity*settings.strategy_budget:
        if bool(raw.get("rapidBuildRequested")):
            ref.set({"rapidBuildRequested":False,"phase":"RISK_HOLD","lastReason":"Snelle startopbouw gestopt door actuele Strategy-3-risicocontrole"},merge=True)
        return {"status":"waiting","action":"HOLD","ordersSent":0,"reason":"Nieuwe entry geblokkeerd door Strategy-3-risicobudget"}
    try:
        exchange_info=client.public_exchange_info()
        info={str(x.get("symbol","")).upper():x for x in exchange_info.get("symbols",[]) if str(x.get("status","")).upper()=="TRADING"}
        prices={str(x.get("symbol","")).upper():safe_float(x.get("price")) for x in client.ticker_prices()}
        market24=client.ticker_24h()
        changes={str(x.get("symbol","")).upper():safe_float(x.get("priceChangePercent")) for x in market24}
        universe=build_aster_universe_snapshot(exchange_info,market24,settings.universe_top_n)
        brackets=client.leverage_brackets()
    except (AsterApiError,ValueError) as exc:
        reason=f"Strategy-3 marktdata niet gereed: {exc}"
        blocked=aster_usdt_universe_snapshot(settings.universe_top_n,client=client).public_dict()
        ref.set({"phase":"DATA_HOLD","lastReason":reason,"lastTickAt":now,"universe":blocked},merge=True)
        return {"status":"data-hold","reason":reason,"ordersSent":0}
    universe_contract=universe.public_dict()
    ref.set({"universe":universe_contract},merge=True)
    if universe.entry_blocked:
        reason=universe_contract["entryBlockReason"]
        ref.set({"phase":"DATA_HOLD","lastReason":reason,"lastTickAt":now},merge=True)
        return {"status":"data-hold","reason":reason,"ordersSent":0,"universe":universe_contract}
    blocked_symbols={symbol for symbol,_ in active_keys|s1_keys|s2_keys|s3_keys};candidates=list(universe_contract["selectedSymbols"])
    candidates=[x for x in candidates if x in info and x in prices and x not in blocked_symbols];candidates.sort(key=lambda x:changes.get(x,0),reverse=side=="LONG")
    if dry_run or not live:
        reason="Droge Strategy-3-planning; geen order verzonden" if dry_run else "Live-mode is niet volledig bewezen"
        ref.set({"phase":"SIMULATED" if dry_run else "LIVE_HOLD","lastReason":reason,"lastTickAt":now},merge=True)
        return {"status":"simulated","action":"OPEN_BASE","side":side,"candidates":len(candidates),"ordersSent":0,"reason":reason}
    failures=[]
    for symbol in candidates:
        try:
            plan=plan_aster_pair(info[symbol],planning_brackets(client,brackets,symbol,settings.leverage),prices[symbol],settings.base_notional)
            plan=replace(plan,leverage=configure_maximum_usable_leverage(client,replace(plan,leverage=min(plan.leverage,settings.leverage))))
            cycle=f"s3c{int(time.time()*1000)}";decision=Strategy3Decision("OPEN_BASE",side,notional=settings.base_notional,reason="Gebalanceerde Strategy-3-entry")
            result=execute_strategy3_decision(client,decision,plan,Strategy3ExecutionContext(cycle,settings.version,None,True,True,gates),
                risk_approved=lambda margin:strategy_margin+margin<=equity*settings.strategy_budget)
            rr=result[0].get("result",{});qty=safe_float(rr.get("executedQty")) or float(plan.quantity);price=safe_float(rr.get("avgPrice")) or prices[symbol]
            _record_aster_order_attribution(ref,rr,strategy_id="aster-strategy-3",
                strategy_name=str(settings.name or "Strategy 3"),cycle_id=cycle,
                config_version=settings.version,symbol=symbol,side=side,action="OPEN_BASE")
            owned.append(OwnedLeg("aster-strategy-3","strategy3",symbol,side,cycle,settings.version,qty,price,0,"HARVEST",
                (str(rr.get("clientOrderId","")),),(),(),int(time.time()*1000),last_order_at_ms=int(time.time()*1000)))
            ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"trailingPeaks":peaks,"phase":"RUNNING","lastReason":f"{symbol} {side} bevestigd","updatedAt":now},merge=True)
            ref.collection("audit").add({"event":"INITIAL_OPEN_LEG","strategyId":"aster-strategy-3","symbol":symbol,"side":side,"cycleId":cycle,"configVersion":settings.version,"timestamp":now})
            return {"status":"ok","action":"OPEN_BASE","symbol":symbol,"side":side,"ordersSent":1}
        except ValueError as exc:
            # Contract minimum/step-size validation is deterministic and happens
            # before order submission. Never raise the user's configured amount;
            # skip this contract and continue with the next eligible candidate.
            failures.append(f"{symbol}: {exc}")
            continue
        except Exception as exc:
            if not is_definite_contract_rejection(exc):raise
            failures.append(f"{symbol}: {exc}")
    reason="; ".join(failures[:3]) or "Geen geldig vrij contract"
    ref.set({"phase":"WAITING","lastReason":reason,"lastTickAt":now},merge=True)
    return {"status":"waiting","action":"OPEN_BASE","ordersSent":0,"reason":reason}


def aster_strategy2_public(uid: str) -> dict[str, Any]:
    raw = aster_strategy2_reference(uid).get().to_dict() or {}
    settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else Strategy2Config().public_dict()
    snapshot=raw.get("accountSnapshot") if isinstance(raw.get("accountSnapshot"),dict) else {}
    owned=raw.get("ownedLegs") if isinstance(raw.get("ownedLegs"),list) else []
    universe=_configured_universe_contract(raw,int(settings.get("universeTopN",50)))
    return {"strategy2": {"settings": settings,"universe":universe,"phase": str(raw.get("phase", "DRAFT")),
        "liveReady": bool(raw.get("liveReady", False)), "enabled": bool(raw.get("enabled", False)),
        "monitor":bool(raw.get("monitor",False)),"canaryValidated":bool(raw.get("canaryValidated",False)),
        "runtimeEnabled":os.getenv("ASTER_STRATEGY2_LIVE_ENABLED","false").lower()=="true",
        "configVersion": int(safe_float(raw.get("configVersion", settings.get("version", 1)))),
        "lastReason":str(raw.get("lastReason","Nog niet gestart")),"lastTickAt":raw.get("lastTickAt"),
        "scheduler":strategy2_scheduler_status(raw),
        "activePairs":int(safe_float(snapshot.get("activePairs"))),
        "longLegs":sum(1 for x in owned if isinstance(x,dict) and x.get("side")=="LONG"),
        "shortLegs":sum(1 for x in owned if isinstance(x,dict) and x.get("side")=="SHORT")}}


def _run_aster_strategy2_tick(uid:str,*,dry_run:bool=False)->dict[str,Any]:
    ref=aster_strategy2_reference(uid);raw=ref.get().to_dict() or {};now=datetime.now(timezone.utc)
    settings=Strategy2Config.from_mapping(raw.get("settings"));enabled=bool(raw.get("enabled",False));monitor=bool(raw.get("monitor",False))
    if not monitor and not dry_run:return {"status":"stopped","reason":"Strategy 2 monitoring staat uit"}
    live=settings.mode=="live" and not dry_run
    if live and (not bool(raw.get("liveReady")) or not bool(raw.get("canaryValidated")) or os.getenv("ASTER_STRATEGY2_LIVE_ENABLED","false").lower()!="true"):
        reason="Strategy 2 live-uitvoering is niet volledig vrijgegeven: liveReady, canaryValidated of centrale poort ontbreekt"
        ref.set({"phase":"DATA_HOLD","lastReason":reason,"lastTickAt":now},merge=True)
        return {"status":"blocked","reason":reason}
    secret=load_aster_secret({"uid":uid});client=AsterV3Client(signer_address=secret.signer_address,sign_message=local_eip712_signer(secret),live_authorized=live)
    try: hedge=client.position_mode();account=client.account_information();positions=client.position_risk();orders=client.open_orders()
    except (AsterApiError,ValueError) as exc:
        ref.set({"phase":"DATA_HOLD","lastReason":str(exc),"lastTickAt":now},merge=True);return {"status":"data-hold","reason":str(exc)}
    if not hedge:
        reason="Aster Hedge Mode staat uit";ref.set({"phase":"DATA_HOLD","lastReason":reason,"lastTickAt":now},merge=True)
        return {"status":"blocked","reason":reason}
    if orders:
        reason="Open Aster-orders worden eerst gereconcilieerd";ref.set({"phase":"RECONCILING","lastReason":reason,"lastTickAt":now},merge=True)
        return {"status":"reconciling","reason":reason}
    owned=[]
    for item in raw.get("ownedLegs") if isinstance(raw.get("ownedLegs"),list) else []:
        try:owned.append(owned_from_mapping(item))
        except (TypeError,ValueError):pass
    if owned:
        fills=[]
        try:
            audit_events=[x.to_dict() or {} for x in ref.collection("audit").stream()]
            audited_symbols={str(x.get("symbol","")).upper() for x in audit_events if str(x.get("event","")).upper()=="INITIAL_OPEN_LEG"}
            active_keys=set(active_position_map(positions));known_keys={(x.symbol,x.side) for x in owned}
            missing_symbols={symbol for symbol,side in active_keys if (symbol,side) not in known_keys}
            changed_symbols=changed_owned_symbols(owned,positions)
            urgent=most_urgent_profitable_owned(settings,owned,positions)
            recovery_symbols=changed_symbols|(audited_symbols&missing_symbols)|({urgent.symbol} if urgent else set())
            for symbol in sorted(recovery_symbols):fills.extend(client.user_trades(symbol,limit=500))
            s3_raw=aster_strategy3_reference(uid).get().to_dict() or {};s3_keys=set();s3_legs=[]
            for item in s3_raw.get("ownedLegs",[]) if isinstance(s3_raw.get("ownedLegs"),list) else []:
                try:
                    s3_leg=owned_from_mapping(item)
                    if s3_leg.strategy_id=="aster-strategy-3" and s3_leg.engine_type=="strategy3":
                        s3_keys.add((s3_leg.symbol,s3_leg.side));s3_legs.append(s3_leg)
                except (TypeError,ValueError):pass
            owned,resolved_conflicts=remove_strategy3_proven_conflicts(strategy2_legs=owned,strategy3_legs=s3_legs)
            if resolved_conflicts:
                ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"updatedAt":now},merge=True)
                for item in resolved_conflicts:ref.collection("audit").add({"event":"S2_SHADOW_OWNERSHIP_REMOVED",**item,"timestamp":now})
            owned,recovered_ownership=recover_audited_ownership(persisted=owned,positions=positions,
                audit_events=audit_events,fills=fills,excluded_keys=s3_keys)
            if recovered_ownership:
                ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"updatedAt":now},merge=True)
                for item in recovered_ownership:ref.collection("audit").add({"event":"OWNERSHIP_RECOVERED_FROM_AUDIT",**item,"timestamp":now})
            income=client.income_history(limit=500) if recovery_symbols else []
            recovery=reconcile_owned_legs(persisted=owned,positions=positions,open_orders=orders,fills=fills,exchange_reliable=True)
        except (AsterApiError,ValueError) as exc:
            return {"status":"data-hold","reason":f"Fill/funding recovery niet betrouwbaar: {exc}","ordersSent":0}
        if not recovery.allow_risk_increase:
            ref.set({"phase":"RECONCILING","lastReason":"; ".join(recovery.reasons),"lastTickAt":now},merge=True)
            return {"status":"reconciling","reason":"; ".join(recovery.reasons),"ordersSent":0}
        owned=(enrich_confirmed_costs(list(recovery.legs),fills,income,refreshed_symbols=recovery_symbols,
                checked_at_ms=int(now.timestamp()*1000))
            if fills or income else list(recovery.legs))
    posmap=active_position_map(positions)
    confirmed_flat=[x for x in owned if (x.symbol,x.side) not in posmap]
    for leg in confirmed_flat:ref.collection("audit").add({"event":"CONFIRMED_FLAT","symbol":leg.symbol,"side":leg.side,"cycleId":leg.cycle_id,"timestamp":now})
    owned=[x for x in owned if (x.symbol,x.side) in posmap];owned_keys={(x.symbol,x.side) for x in owned}
    strategy_positions=[x for x in positions if (str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) in owned_keys]
    portfolio=strategy2_portfolio_state(settings,account,positions,owned,safe_float(raw.get("adjustedHighWaterMark")) or safe_float(account.get("totalMarginBalance")))
    snapshot={"equity":portfolio.equity,"highWaterMark":portfolio.adjusted_high_water_mark,"drawdown":portfolio.drawdown,
        "marginRatio":portfolio.margin_ratio,"longExposure":portfolio.long_exposure,"shortExposure":portfolio.short_exposure,
        "strategyExposure":portfolio.strategy_exposure,"strategyMargin":portfolio.strategy_margin,
        "activePairs":len({x.symbol for x in owned}),"capturedAt":now}
    ref.set({"accountSnapshot":snapshot,"adjustedHighWaterMark":portfolio.adjusted_high_water_mark,"ownedLegs":[owned_to_mapping(x) for x in owned],"lastTickAt":now},merge=True)
    blocked_dca_raw=raw.get("blockedDcaMinimums") if isinstance(raw.get("blockedDcaMinimums"),dict) else {}
    blocked_dca=(
        {(str(x).split("|",1)[0],str(x).split("|",1)[1]) for x in blocked_dca_raw.get("legs",[]) if "|" in str(x)}
        if int(safe_float(blocked_dca_raw.get("configVersion")))==settings.version else set()
    )
    # Existing position management precedes new exposure. Within TP candidates,
    # next_management_decision ranks the largest net surplus first.
    selected=portfolio_protection_decision(settings,portfolio,owned) or next_management_decision(settings,portfolio,owned,strategy_positions,blocked_dca) or same_pair_protection_decision(settings,portfolio,owned,strategy_positions)
    if selected and not management_preempts_initial_build(settings,owned,selected[1]):
        selected=None
    if selected:
        leg,decision=selected
        if decision.kind=="ADD_DCA" and (not enabled or portfolio.margin_ratio>=settings.defensive_margin_ratio):decision=Decision("HOLD",leg.side,reason="DCA geblokkeerd omdat Strategy 2 gestopt of defensief is",risk_reducing=True)
        if decision.kind=="ASSIGN_PROTECTION":
            owned=[replace(x,role="PROTECTION") if x==leg else x for x in owned]
            ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"phase":"PROTECTION","lastReason":decision.reason},merge=True)
            ref.collection("audit").add({"event":"ROLE_PROTECTION","symbol":leg.symbol,"side":leg.side,"reason":decision.reason,"timestamp":now})
            return {"status":"ok","action":decision.kind,"symbol":leg.symbol,"side":leg.side,"ordersSent":0}
        if decision.kind=="RELEASE_PROTECTION":
            owned=[replace(x,role="HARVEST") if x==leg else x for x in owned]
            ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"phase":"RUNNING","lastReason":decision.reason},merge=True)
            ref.collection("audit").add({"event":"ROLE_HARVEST","symbol":leg.symbol,"side":leg.side,"reason":decision.reason,"timestamp":now})
            return {"status":"ok","action":decision.kind,"symbol":leg.symbol,"side":leg.side,"ordersSent":0}
        if decision.kind=="OPEN_PROTECTION":
            source=posmap[(leg.symbol,leg.side)];price=safe_float(source.get("markPrice"))
            info={str(x.get("symbol","")).upper():x for x in client.public_exchange_info().get("symbols",[])}
            protection=plan_aster_pair(info[leg.symbol],_aster_brackets(client.leverage_brackets(leg.symbol),leg.symbol),price,decision.notional)
            protection=replace(protection,leverage=min(protection.leverage,settings.leverage))
            protection=replace(protection,leverage=configure_maximum_usable_leverage(client,protection))
            required=float(protection.notional_per_leg)/max(1,protection.leverage)
            if portfolio.strategy_margin+required>portfolio.equity*settings.strategy_budget:
                return {"status":"waiting","action":"BLOCKED","reason":"Strategy Margin Budget blokkeert extra protection","ordersSent":0}
            if dry_run or not live:return {"status":"simulated","action":decision.kind,"symbol":leg.symbol,"side":decision.side,"ordersSent":0,"reason":decision.reason}
            opened=execute_aster_leg(client,protection,side=PositionSide(decision.side),action="OPEN",id_prefix=f"s2h-{uid[-4:]}-{int(time.time())}",confirm=True)
            rr=opened.get("result",{});q=safe_float(rr.get("executedQty")) or float(protection.quantity);p=safe_float(rr.get("avgPrice")) or price
            _record_aster_order_attribution(ref,rr,strategy_id=settings.strategy_id,strategy_name="Dual Profit Harvest DCA",
                cycle_id=leg.cycle_id,config_version=settings.version,symbol=leg.symbol,side=str(decision.side),action="OPEN_PROTECTION")
            owned.append(OwnedLeg(settings.strategy_id,"strategy2",leg.symbol,str(decision.side),f"h{int(time.time())}",settings.version,q,p,0,"PROTECTION",(str(rr.get("clientOrderId","")),),(),(),int(time.time()*1000)))
            ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"phase":"PROTECTION","lastReason":decision.reason,"updatedAt":now},merge=True)
            ref.collection("audit").add({"event":"OPEN_PROTECTION","symbol":leg.symbol,"side":decision.side,"timestamp":now})
            return {"status":"ok","action":decision.kind,"symbol":leg.symbol,"side":decision.side,"ordersSent":1}
        if decision.kind!="HOLD":
            row=posmap[(leg.symbol,leg.side)];price=safe_float(row.get("markPrice"));qty=abs(Decimal(str(row.get("positionAmt"))))
            current=PairExecutionPlan(leg.symbol,qty,qty*Decimal(str(price)),max(1,int(safe_float(row.get("leverage")))))
            if decision.kind in {"ADD_DCA","PROTECTION_INCREASE"}:
                info={str(x.get("symbol","")).upper():x for x in client.public_exchange_info().get("symbols",[])}
                try:
                    current=plan_aster_pair(info[leg.symbol],_aster_brackets(client.leverage_brackets(leg.symbol),leg.symbol),price,decision.notional)
                except ValueError as exc:
                    if decision.kind!="ADD_DCA" or "minimale exchangeorder" not in str(exc):
                        raise
                    blocked_dca.add((leg.symbol,leg.side))
                    reason=f"{leg.symbol} {leg.side}: DCA overgeslagen; {exc}"
                    ref.set({"blockedDcaMinimums":{"configVersion":settings.version,"legs":[f"{symbol}|{side}" for symbol,side in sorted(blocked_dca)]},
                             "phase":"RUNNING","lastReason":reason,"lastTickAt":now,"updatedAt":now},merge=True)
                    ref.collection("audit").add({"event":"DCA_BLOCKED_EXCHANGE_MINIMUM","symbol":leg.symbol,"side":leg.side,
                        "reason":str(exc),"configVersion":settings.version,"timestamp":now})
                    return {"status":"waiting","action":"DCA_BLOCKED_MINIMUM","symbol":leg.symbol,"side":leg.side,
                        "ordersSent":0,"reason":reason}
                current=replace(current,leverage=min(current.leverage,settings.leverage))
                current=replace(current,leverage=configure_maximum_usable_leverage(client,current))
            if dry_run or not live:return {"status":"simulated","action":decision.kind,"symbol":leg.symbol,"side":leg.side,"ordersSent":0,"reason":decision.reason}
            context=ExecutionContext(settings.strategy_id,leg.cycle_id,settings.version,leg,True,True)
            result=execute_aster_strategy2_decision(client,decision,current,context,risk_approved=lambda margin:(decision.risk_reducing and portfolio.margin_ratio<settings.emergency_margin_ratio) or (portfolio.margin_ratio<settings.defensive_margin_ratio and portfolio.strategy_margin+margin<=portfolio.equity*settings.strategy_budget))
            for execution in result:
                _record_aster_order_attribution(ref,execution.get("result",{}),strategy_id=settings.strategy_id,
                    strategy_name="Dual Profit Harvest DCA",cycle_id=leg.cycle_id,config_version=settings.version,
                    symbol=leg.symbol,side=leg.side,action=decision.kind)
            if decision.kind in {"ADD_DCA","PROTECTION_INCREASE"}:
                rr=result[0].get("result",{});fill_qty=safe_float(rr.get("executedQty")) or float(current.quantity);fill_price=safe_float(rr.get("avgPrice")) or price
                total=leg.quantity+fill_qty;avg=(leg.quantity*leg.weighted_entry+fill_qty*fill_price)/max(total,1e-12)
                owned=[replace(x,quantity=total,weighted_entry=avg,dca_count=x.dca_count+(1 if decision.kind=="ADD_DCA" else 0),role="PROTECTION" if decision.kind=="PROTECTION_INCREASE" else x.role,last_order_at_ms=int(time.time()*1000)) if x==leg else x for x in owned]
            else:
                closed_result=result[0].get("result",{});closed_qty=safe_float(closed_result.get("executedQty")) or float(current.quantity)
                remaining=max(0.0,leg.quantity-closed_qty);owned=[replace(x,quantity=remaining) if x==leg and remaining>1e-12 else x for x in owned if x!=leg or remaining>1e-12]
                if decision.kind=="FULL_TP" and enabled and settings.auto_restart:
                    info={str(x.get("symbol","")).upper():x for x in client.public_exchange_info().get("symbols",[])}
                    reopen=plan_aster_pair(info[leg.symbol],_aster_brackets(client.leverage_brackets(leg.symbol),leg.symbol),price,settings.base_notional)
                    reopen=replace(reopen,leverage=min(reopen.leverage,settings.leverage))
                    reopen=replace(reopen,leverage=configure_maximum_usable_leverage(client,reopen))
                    reopen_margin=float(reopen.notional_per_leg)/max(1,reopen.leverage)
                    if portfolio.strategy_margin+reopen_margin>portfolio.equity*settings.strategy_budget:
                        ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"phase":"WAITING","lastReason":"TP gesloten; herstart geblokkeerd door actueel Strategy Margin Budget","updatedAt":now},merge=True)
                        return {"status":"waiting","action":"FULL_TP","symbol":leg.symbol,"side":leg.side,"ordersSent":len(result),"reason":"Herstart geblokkeerd door actueel Strategy Margin Budget"}
                    reopen_cycle=f"c{int(time.time())}"
                    reopened=execute_aster_leg(client,reopen,side=PositionSide(leg.side),action="OPEN",id_prefix=f"s2r-{uid[-4:]}-{int(time.time())}",confirm=True)
                    result.append(reopened);rr=reopened.get("result",{});rq=safe_float(rr.get("executedQty")) or float(reopen.quantity);rp=safe_float(rr.get("avgPrice")) or price
                    _record_aster_order_attribution(ref,rr,strategy_id=settings.strategy_id,strategy_name="Dual Profit Harvest DCA",
                        cycle_id=reopen_cycle,config_version=settings.version,symbol=leg.symbol,side=leg.side,action="AUTO_RESTART")
                    owned.append(OwnedLeg(settings.strategy_id,"strategy2",leg.symbol,leg.side,reopen_cycle,settings.version,rq,rp,0,"HARVEST",(str(rr.get("clientOrderId","")),),(),(),int(time.time()*1000)))
            ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"phase":"RUNNING","lastReason":decision.reason,"updatedAt":now},merge=True)
            ref.collection("audit").add({"event":decision.kind,"symbol":leg.symbol,"side":leg.side,"cycleId":leg.cycle_id,"timestamp":now})
            return {"status":"ok","action":decision.kind,"symbol":leg.symbol,"side":leg.side,"ordersSent":len(result)}
    if not enabled or not scanner_allowed(settings,portfolio,owned):
        reason="Strategy 2 staat veilig gestopt" if not enabled else "Geen beheeractie; pair- of risicolimiet bereikt"
        ref.set({"phase":"PROTECTIVE_ONLY" if not enabled else "WAITING","lastReason":reason},merge=True);return {"status":"waiting","action":"HOLD","reason":reason,"ordersSent":0}
    active_keys={(str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) for x in positions if abs(safe_float(x.get("positionAmt")))>0}
    initial_build_complete=bool(raw.get("initialBuildComplete",False))
    long_target,short_target=balanced_entry_targets(settings.maximum_pairs)
    long_count,short_count=harvest_counts(owned)
    if long_count>=long_target and short_count>=short_target:
        initial_build_complete=True
        if not bool(raw.get("initialBuildComplete",False)):
            ref.set({"initialBuildComplete":True,"phase":"RUNNING","lastReason":f"Gebalanceerde start compleet: {long_count} LONG / {short_count} SHORT","updatedAt":now},merge=True)
    try:
        exchange_info=client.public_exchange_info();info_rows=exchange_info.get("symbols",[]);rows={str(x.get("symbol","")).upper():x for x in info_rows if str(x.get("status","")).upper()=="TRADING"}
        prices={str(x.get("symbol","")).upper():safe_float(x.get("price")) for x in client.ticker_prices()}
        market24=client.ticker_24h()
        changes={str(x.get("symbol","")).upper():safe_float(x.get("priceChangePercent")) for x in market24}
        universe=build_aster_universe_snapshot(exchange_info,market24,settings.universe_top_n)
        all_brackets=client.leverage_brackets()
    except (AsterApiError,ValueError) as exc:
        blocked=aster_usdt_universe_snapshot(settings.universe_top_n,client=client).public_dict()
        ref.set({"phase":"DATA_HOLD","lastReason":str(exc),"lastTickAt":now,"universe":blocked},merge=True)
        return {"status":"data-hold","reason":str(exc),"ordersSent":0,"universe":blocked}
    universe_contract=universe.public_dict();ref.set({"universe":universe_contract},merge=True)
    if universe.entry_blocked:
        reason=universe_contract["entryBlockReason"]
        ref.set({"phase":"DATA_HOLD","lastReason":reason,"lastTickAt":now},merge=True)
        return {"status":"data-hold","reason":reason,"ordersSent":0,"universe":universe_contract}
    codes=[symbol for symbol in universe_contract["selectedSymbols"] if symbol in rows and symbol in prices]
    order_limit=entry_order_limit(initial_build_complete,owned,settings.maximum_pairs)
    if dry_run or not live:
        return {"status":"simulated","action":"INITIAL_BUILD" if not initial_build_complete else "OPEN_LEG","plannedOrders":order_limit,
            "targetLong":long_target,"targetShort":short_target,"ordersSent":0}
    opened_legs=[];used_strategy_margin=portfolio.strategy_margin;candidate_failures=[];budget_blocked=False
    for index in range(order_limit):
        entry_side=next_balanced_entry_side(owned,settings.maximum_pairs)
        if not entry_side:break
        candidates=[symbol for symbol in codes if (symbol,entry_side) not in active_keys]
        candidates.sort(key=lambda symbol:changes.get(symbol,0),reverse=entry_side=="LONG")
        plan=None;symbol="";opened=None
        for candidate in candidates:
            try:
                value=plan_aster_pair(rows[candidate],planning_brackets(client,all_brackets,candidate,settings.leverage),prices[candidate],settings.base_notional)
                value=replace(value,leverage=min(value.leverage,settings.leverage))
                accepted=configure_maximum_usable_leverage(client,value)
                value=replace(value,leverage=accepted)
                # The UI value is leveraged position notional, not margin and
                # never a two-sided total.  Refuse a silent undersized order.
                if float(value.notional_per_leg)+.01 < settings.base_notional:
                    raise ValueError(f"{candidate}: geplande positie ${float(value.notional_per_leg):.2f} is kleiner dan ingestelde ${settings.base_notional:.2f}")
                required=float(value.notional_per_leg)/max(1,value.leverage)
                if used_strategy_margin+required>portfolio.equity*settings.strategy_budget:
                    budget_blocked=True
                    candidate_failures.append(f"{candidate}: Strategy Margin Budget")
                    break
                try:
                    opened=execute_aster_leg(client,value,side=PositionSide(entry_side),action="OPEN",id_prefix=f"s2i-{uid[-4:]}-{int(time.time()*1000)}-{index}-{candidate[:5].lower()}",confirm=True)
                except Exception as exc:
                    if not is_definite_contract_rejection(exc):
                        raise
                    candidate_failures.append(f"{candidate}: {exc}")
                    ref.collection("audit").add({"event":"ENTRY_CANDIDATE_REJECTED","symbol":candidate,"side":entry_side,
                        "reason":str(exc),"configVersion":settings.version,"timestamp":datetime.now(timezone.utc)})
                    continue
                plan=value;symbol=candidate;break
            except ValueError as exc:
                candidate_failures.append(f"{candidate}: {exc}")
                continue
            except Exception as exc:
                if not is_definite_contract_rejection(exc):
                    raise
                candidate_failures.append(f"{candidate}: {exc}")
                ref.collection("audit").add({"event":"ENTRY_CANDIDATE_REJECTED","symbol":candidate,"side":entry_side,
                    "reason":str(exc),"configVersion":settings.version,"timestamp":datetime.now(timezone.utc)})
                continue
        if not plan or opened is None:break
        required=float(plan.notional_per_leg)/max(1,plan.leverage)
        cycle=f"c{int(time.time()*1000)}-{index}"
        rr=opened.get("result",{});q=safe_float(rr.get("executedQty")) or float(plan.quantity);p=safe_float(rr.get("avgPrice")) or prices[symbol]
        _record_aster_order_attribution(ref,rr,strategy_id=settings.strategy_id,strategy_name="Dual Profit Harvest DCA",
            cycle_id=cycle,config_version=settings.version,symbol=symbol,side=entry_side,
            action="INITIAL_OPEN_LEG" if not initial_build_complete else "OPEN_LEG")
        owned.append(OwnedLeg(settings.strategy_id,"strategy2",symbol,entry_side,cycle,settings.version,q,p,0,"HARVEST",(str(rr.get("clientOrderId","")),),(),(),int(time.time()*1000)))
        active_keys.add((symbol,entry_side));used_strategy_margin+=required;opened_legs.append({"symbol":symbol,"side":entry_side})
        # Persist after every confirmed fill: a later timeout must never erase
        # ownership of the positions already opened in this initial batch.
        ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"phase":"INITIAL_BUILD","lastReason":f"Initiële opbouw: {len(opened_legs)} positie(s) bevestigd","updatedAt":datetime.now(timezone.utc)},merge=True)
        ref.collection("audit").add({"event":"INITIAL_OPEN_LEG" if not initial_build_complete else "OPEN_LEG","symbol":symbol,"side":entry_side,"cycleId":cycle,
            "configuredBaseNotional":settings.base_notional,"filledNotional":q*p,"acceptedLeverage":opened.get("leverage",plan.leverage),"configVersion":settings.version,"timestamp":datetime.now(timezone.utc)})
    long_count,short_count=harvest_counts(owned);complete=long_count>=long_target and short_count>=short_target
    detail=("; ".join(candidate_failures[:3]) if candidate_failures else
        ("Strategy Margin Budget bereikt" if budget_blocked else f"{len(codes)} kandidaten gecontroleerd"))
    reason=(f"Gebalanceerde start compleet: {long_count} LONG / {short_count} SHORT" if complete else
        f"Initiële opbouw gepauzeerd op {long_count} LONG / {short_count} SHORT. {detail}")
    ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"initialBuildComplete":complete,"phase":"RUNNING" if complete else "INITIAL_BUILD","lastReason":reason,"updatedAt":datetime.now(timezone.utc)},merge=True)
    return {"status":"ok" if opened_legs else "waiting","action":"INITIAL_BUILD" if not initial_build_complete else "OPEN_LEG",
        "opened":opened_legs,"longCount":long_count,"shortCount":short_count,"targetLong":long_target,"targetShort":short_target,"ordersSent":len(opened_legs),"reason":reason}


def aster_automation_public(uid: str) -> dict[str, Any]:
    value = aster_automation_reference(uid).get().to_dict() or {}
    settings = value.get("settings") if isinstance(value.get("settings"), dict) else {}
    return {
        "automationEnabled": bool(value.get("enabled", False)),
        "automationMonitoring": bool(value.get("monitor", False)),
        "automationPhase": str(value.get("phase", "STOPPED")),
        "automationReason": str(value.get("lastReason", "Niet gestart")),
        "automationLastTickAt": value.get("lastTickAt"),
        "automationSettings": settings or AsterStrategySettings().public_dict(),
        "automationUniverse": _configured_universe_contract(value, int((setti…43861 tokens truncated…in {4, 5}:
                        control_ref.set({"paused": True, "pauseReason": "MEXC heeft een automatische order geannuleerd of ongeldig verklaard"}, merge=True)
                        return {"uid": uid, "status": "paused-invalid-order"}
                except MexcApiError:
                    pass
            accepted.append(item)
        cycle_orders = [item for item in accepted if int(safe_float(item.get("cycle"))) == state.cycle and item.get("status") in {"accepted", "filled"}]
        session_fees = sum(safe_float(item.get("takerFee")) for item in cycle_orders)
        session_realized = sum(safe_float(item.get("profit")) for item in cycle_orders)
        accepted_dca = [item for item in cycle_orders if item.get("action") == "ADD_LONG"]
        if accepted_dca:
            latest_dca = max(accepted_dca, key=lambda item: int(safe_float(item.get("dcaIndex"))))
            state = MexcAutoState(
                state.session_start_equity,
                max(state.dca_count, int(safe_float(latest_dca.get("dcaIndex")))),
                safe_float(latest_dca.get("marketPrice")) or state.last_dca_price,
                max(state.last_order_time, int(safe_float(latest_dca.get("signalTimestamp")))),
                state.phase,
                state.cycle,
            )

        # A completed cycle compounds from the new real equity only after every
        # BTC leg is flat.  Manual closes are adopted on the next tick.
        if not long and not short and state.phase not in {"WAIT", "CLOSED"}:
            # Market orders normally appear immediately. Give MEXC five minutes
            # to reconcile an accepted open/add order; never submit a replacement.
            if state.last_order_time and int(time.time()) - state.last_order_time < 300:
                control_ref.set({"lastAction": "HOLD", "lastReason": "Wacht op MEXC-positiereconciliatie", "lastTickAt": datetime.now(timezone.utc)}, merge=True)
                return {"uid": uid, "status": "reconciling"}
            state = MexcAutoState(equity, cycle=state.cycle + 1)
        if (long or short) and state.phase == "CLOSED":
            if state.last_order_time and int(time.time()) - state.last_order_time < 300:
                control_ref.set({"lastAction": "HOLD", "lastReason": "Wacht op bevestiging van volledige sluiting", "lastTickAt": datetime.now(timezone.utc)}, merge=True)
                return {"uid": uid, "status": "closing"}
            control_ref.set({"paused": True, "pauseReason": "Sluitorders zijn niet binnen vijf minuten volledig verwerkt", "lastTickAt": datetime.now(timezone.utc)}, merge=True)
            return {"uid": uid, "status": "paused-close-mismatch"}
        if not long and not short and state.phase == "CLOSED":
            if bool(control.get("protectiveOnly", False)) or not bool(control.get("enabled", False)):
                control_ref.set({"monitor": False, "lastReason": "Gestopt en alle BTC-posities zijn gesloten", "lastTickAt": datetime.now(timezone.utc)}, merge=True)
                return {"uid": uid, "status": "stopped-flat"}
            state = MexcAutoState(equity, cycle=state.cycle + 1)

        if long and state.phase == "WAIT":
            state = MexcAutoState(state.session_start_equity, state.dca_count, state.last_dca_price or safe_float(long.get("entryPrice")), state.last_order_time, "LONG", state.cycle)

        execution = client.candles("BTC_USDT", settings.execution_timeframe, 60)
        risk = client.candles("BTC_USDT", settings.risk_timeframe, 60)
        market = mexc_signal_from_candles(execution, risk)
        gross = safe_float((long or {}).get("notionalUsd")) + safe_float((short or {}).get("notionalUsd"))
        net = abs(safe_float((long or {}).get("notionalUsd")) - safe_float((short or {}).get("notionalUsd")))
        mmr = max(safe_float((long or short or {}).get("maintenanceMarginRate")), safe_float(contract.get("maintenanceMarginRate")))
        liquidation_fee = safe_float(contract.get("liquidationFeeRate"))
        liquidation_distance = 1.0 if net <= 0 else max(0.0, min(1.0, (equity - gross * (mmr + liquidation_fee)) / net))
        margin_ratio = (gross * (mmr + liquidation_fee) / equity) if equity > 0 else 1.0
        account = MexcAutoAccountSnapshot(
            current_equity=equity,
            available_equity=safe_float(usdt.get("availableOpen")),
            long_notional=safe_float((long or {}).get("notionalUsd")),
            short_notional=safe_float((short or {}).get("notionalUsd")),
            weighted_long_entry=safe_float((long or {}).get("entryPrice")),
            weighted_short_entry=safe_float((short or {}).get("entryPrice")),
            margin_used=safe_float(usdt.get("positionMargin")),
            margin_ratio=margin_ratio,
            liquidation_distance=liquidation_distance,
            net_session_pnl=equity - state.session_start_equity,
        )
        action = decide_mexc_automation(settings, state, account, market)
        if dry_run:
            result = {
                "uid": uid, "status": "simulated", "action": action.kind,
                "reason": action.reason, "targetNotional": action.target_notional,
                "signal": {"price": market.price, "riskScore": market.risk_score, "recoveryScore": market.recovery_score, "atrPercent": market.atr_percent, "lowerLow": market.lower_low, "timestamp": market.timestamp},
                "snapshot": {"equity": equity, "available": account.available_equity, "longNotional": account.long_notional, "shortNotional": account.short_notional, "marginRatio": account.margin_ratio, "liquidationDistance": account.liquidation_distance, "netSessionPnl": account.net_session_pnl},
                "settings": settings.public_dict(),
            }
            control_ref.set({"lastSimulation": result, "lastSimulationAt": datetime.now(timezone.utc)}, merge=True)
            return result
        if bool(control.get("protectiveOnly", False)) and action.kind not in {"CLOSE_ALL", "CLOSE_SHORT", "HOLD"}:
            action = type(action)("HOLD", reason="Handelsstop actief; alleen take-profit en absolute veiligheid blijven actief")
        if action.kind == "PAUSE":
            control_ref.set({"paused": True, "pauseReason": action.reason, "lastAction": action.kind, "lastReason": action.reason, "lastTickAt": datetime.now(timezone.utc)}, merge=True)
            return {"uid": uid, "status": "paused", "reason": action.reason}
        next_state = _execute_mexc_automation_action(uid, client, control_ref, state, action, positions, contract, price, market.timestamp)
        control_ref.set({
            "state": _mexc_state_dict(next_state), "lastAction": action.kind,
            "lastReason": action.reason, "lastSignal": {
                "price": market.price, "riskScore": market.risk_score,
                "recoveryScore": market.recovery_score, "atrPercent": market.atr_percent,
                "lowerLow": market.lower_low, "timestamp": market.timestamp,
            },
            "lastSnapshot": {
                "equity": equity, "available": account.available_equity,
                "longNotional": account.long_notional, "shortNotional": account.short_notional,
                "marginRatio": account.margin_ratio, "liquidationDistance": account.liquidation_distance,
                "netSessionPnl": account.net_session_pnl,
            },
            "lastTickAt": datetime.now(timezone.utc), "updatedAt": datetime.now(timezone.utc),
            "sessionFees": session_fees, "sessionRealizedPnl": session_realized,
        }, merge=True)
        return {"uid": uid, "status": "ok", "action": action.kind, "reason": action.reason}
    except MexcCanaryUncertain as exc:
        control_ref.set({"paused": True, "pauseReason": str(exc), "lastTickAt": datetime.now(timezone.utc)}, merge=True)
        return {"uid": uid, "status": "paused-uncertain", "reason": str(exc)}
    except (MexcApiError, ValueError) as exc:
        # Connectivity/data failures never create a guessed order. Monitoring
        # remains enabled so the next scheduler tick can recover automatically.
        control_ref.set({"lastAction": "HOLD", "lastReason": str(exc), "lastTickAt": datetime.now(timezone.utc)}, merge=True)
        return {"uid": uid, "status": "data-hold", "reason": str(exc)}


@app.put("/v1/me/mexc/automation/settings")
def save_mexc_automation_settings(request: MexcAutomationSettingsRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    strategy_version = str(request.settings.get("strategyVersion", request.settings.get("strategy_version", "")))
    if strategy_version == "hedge_dca_v3":
        settings = V3Settings.from_dict(request.settings)
        if errors := settings.validate():
            raise HTTPException(422, "; ".join(errors))
        ref = mexc_automation_reference(str(user["uid"]))
        ref.set({"uid": str(user["uid"]), "settings": settings.public_dict(), "updatedAt": datetime.now(timezone.utc)}, merge=True)
        return {"saved": True, "settings": settings.public_dict(), **mexc_automation_public(str(user["uid"]))}
    settings = MexcAutoSettings.from_dict(request.settings)
    if errors := settings.validate():
        raise HTTPException(422, "; ".join(errors))
    ref = mexc_automation_reference(str(user["uid"]))
    ref.set({"uid": str(user["uid"]), "settings": settings.public_dict(), "updatedAt": datetime.now(timezone.utc)}, merge=True)
    return {"saved": True, "settings": settings.public_dict(), **mexc_automation_public(str(user["uid"]))}


@app.post("/v1/me/mexc/automation/start")
def start_mexc_automation(request: MexcAutomationStartRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    require_verified_email(user)
    if not request.confirm:
        raise HTTPException(422, "Bevestig automatische handel met echt geld expliciet")
    if os.getenv("MEXC_LIVE_EXECUTION_ENABLED", "false").lower() != "true":
        raise HTTPException(409, "MEXC-orderuitvoering staat centraal vergrendeld")
    if os.getenv("MEXC_AUTOMATION_EXECUTION_ENABLED", "false").lower() != "true":
        raise HTTPException(409, "MEXC-automatisering staat centraal vergrendeld")
    credentials = load_mexc_credentials(user)
    status = inspect_mexc(credentials)
    if not status["liveReady"] or status["executionLeverage"] != 200 or status["executionMarginMode"] != "cross":
        raise HTTPException(409, "MEXC Cross 200× preflight is niet volledig geslaagd")
    strategy_version = str(request.settings.get("strategyVersion", request.settings.get("strategy_version", "")))
    if strategy_version == "hedge_dca_v3":
        settings = V3Settings.from_dict(request.settings)
        if errors := settings.validate():
            raise HTTPException(422, "; ".join(errors))
        ref = mexc_automation_reference(str(user["uid"]))
        ref.set({
            "uid": str(user["uid"]), "enabled": True, "monitor": True,
            "protectiveOnly": False, "paused": False, "pauseReason": "",
            "settings": settings.public_dict(), "v3State": v3_state_to_dict(V3State()),
            "lastReason": "V3 bevestigd; wacht op veilige cloudtick",
            "activatedAt": datetime.now(timezone.utc), "updatedAt": datetime.now(timezone.utc),
        }, merge=True)
        return {"started": True, **mexc_automation_public(str(user["uid"]))}
    settings = MexcAutoSettings.from_dict(request.settings)
    if errors := settings.validate():
        raise HTTPException(422, "; ".join(errors))
    ref = mexc_automation_reference(str(user["uid"]))
    existing = ref.get().to_dict() or {}
    state = _mexc_auto_state(existing, status["equity"])
    if not existing.get("state"):
        first_position = status.get("positions", [{}])[0] if status.get("positions") else {}
        state = MexcAutoState(status["equity"], last_dca_price=safe_float(first_position.get("entryPrice")))
    ref.set({
        "uid": str(user["uid"]), "enabled": True, "monitor": True,
        "protectiveOnly": False, "paused": False, "pauseReason": "",
        "settings": settings.public_dict(), "state": _mexc_state_dict(state),
        "lastReason": "Automatisering bevestigd; wacht op veilige cloudtick",
        "activatedAt": datetime.now(timezone.utc), "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {"started": True, **mexc_automation_public(str(user["uid"]))}


@app.post("/v1/me/mexc/automation/simulate")
def simulate_mexc_automation(request: MexcAutomationSettingsRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    strategy_version = str(request.settings.get("strategyVersion", request.settings.get("strategy_version", "")))
    if strategy_version == "hedge_dca_v3":
        settings = V3Settings.from_dict(request.settings)
        if errors := settings.validate():
            raise HTTPException(422, "; ".join(errors))
        return _run_mexc_v3_tick(str(user["uid"]), dry_run=True, ignore_monitor=True,
                                 settings_override=settings.public_dict())
    settings = MexcAutoSettings.from_dict(request.settings)
    if errors := settings.validate():
        raise HTTPException(422, "; ".join(errors))
    return _run_mexc_automation_tick(str(user["uid"]), dry_run=True, ignore_monitor=True, settings_override=settings.public_dict())


@app.post("/v1/me/mexc/automation/stop")
def stop_mexc_automation(request: MexcAutomationStopRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(422, "Bevestig de handelsstop expliciet")
    # Existing exposure remains monitored for take-profit and absolute safety;
    # no new Long, DCA or hedge exposure may be opened.
    ref = mexc_automation_reference(str(user["uid"]))
    ref.set({"enabled": False, "monitor": True, "protectiveOnly": True, "lastReason": "Handelsstop: geen nieuwe exposure", "updatedAt": datetime.now(timezone.utc)}, merge=True)
    return {"stopped": True, **mexc_automation_public(str(user["uid"]))}


def _acquire_mexc_automation_lease(reference) -> bool:
    transaction = db.transaction()

    @firestore.transactional
    def acquire(txn) -> bool:
        value = reference.get(transaction=txn).to_dict() or {}
        now = datetime.now(timezone.utc)
        lease = value.get("leaseUntil")
        if isinstance(lease, datetime) and lease > now:
            return False
        txn.set(reference, {"leaseUntil": now + timedelta(minutes=3)}, merge=True)
        return True

    return acquire(transaction)


@app.post("/internal/mexc-automation/tick")
def run_mexc_automation_scheduler(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    verify_internal_cloud_request(authorization)
    if os.getenv("MEXC_AUTOMATION_EXECUTION_ENABLED", "false").lower() != "true":
        return {"processed": 0, "status": "centrally-disabled", "results": []}
    controls = list(db.collection("mexcAutomation").where("monitor", "==", True).stream())
    results = []
    for item in controls[:100]:
        reference = mexc_automation_reference(item.id)
        if not _acquire_mexc_automation_lease(reference):
            results.append({"uid": item.id, "status": "lease-busy"})
            continue
        try:
            results.append(_run_mexc_automation_tick(item.id))
        finally:
            reference.set({"leaseUntil": datetime.now(timezone.utc)}, merge=True)
    return {"processed": len(results), "results": results}


@app.post("/internal/mexc-automation/{uid}/simulate")
def run_mexc_automation_internal_simulation(uid: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    verify_internal_cloud_request(authorization)
    if not uid or len(uid) > 128:
        raise HTTPException(422, "Ongeldige gebruiker")
    return _run_mexc_automation_tick(uid, dry_run=True, ignore_monitor=True)


@app.post("/internal/aster-automation/tick")
def run_aster_automation_scheduler(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    verify_internal_cloud_request(authorization)
    controls=list(db.collection("asterAutomation").where("monitor","==",True).stream());results=[]
    for item in controls[:100]:
        reference=aster_automation_reference(item.id)
        if not _acquire_mexc_automation_lease(reference):
            results.append({"uid":item.id,"status":"lease-busy"});continue
        try: results.append(_run_aster_automation_tick(item.id))
        except Exception as exc:
            message=f"Veilige schedulerfout: {exc}"
            reference.set({"phase":"DATA_HOLD","lastReason":message,"lastTickAt":datetime.now(timezone.utc)},merge=True)
            results.append({"uid":item.id,"status":"data-hold","reason":message})
        finally: reference.set({"leaseUntil":datetime.now(timezone.utc)},merge=True)
    strategy2_controls=list(db.collection("asterStrategy2").where("monitor","==",True).stream())
    strategy2_results=[]
    for item in strategy2_controls[:100]:
        reference=aster_strategy2_reference(item.id)
        if not _acquire_mexc_automation_lease(reference):
            strategy2_results.append({"uid":item.id,"status":"lease-busy"});continue
        try:strategy2_results.append({"uid":item.id,**_run_aster_strategy2_tick(item.id)})
        except Exception as exc:
            message=f"Veilige Strategy-2-schedulerfout: {exc}"
            reference.set({"phase":"DATA_HOLD","lastReason":message,"lastTickAt":datetime.now(timezone.utc)},merge=True)
            strategy2_results.append({"uid":item.id,"status":"data-hold","reason":message})
        finally:reference.set({"leaseUntil":datetime.now(timezone.utc)},merge=True)
    strategy3_controls=list(db.collection("asterStrategy3").where("monitor","==",True).stream())
    strategy3_results=[]
    for item in strategy3_controls[:100]:
        reference=aster_strategy3_reference(item.id)
        if not _acquire_mexc_automation_lease(reference):
            strategy3_results.append({"uid":item.id,"status":"lease-busy"});continue
        try:
            state=item.to_dict() or {}
            if bool(state.get("rapidBuildRequested")) and bool(state.get("enabled")):
                strategy3_results.append({"uid":item.id,"status":"rapid-build",**_run_strategy3_rapid_batch(item.id,10)})
            else:strategy3_results.append({"uid":item.id,**_run_aster_strategy3_tick(item.id)})
        except Exception as exc:
            message=f"Veilige Strategy-3-schedulerfout: {exc}"
            reference.set({"phase":"DATA_HOLD","rapidBuildRequested":False,"lastReason":message,"lastTickAt":datetime.now(timezone.utc)},merge=True)
            strategy3_results.append({"uid":item.id,"status":"data-hold","reason":message})
        finally:reference.set({"leaseUntil":datetime.now(timezone.utc)},merge=True)
    return {"processed":len(results)+len(strategy2_results)+len(strategy3_results),"strategy1":results,"strategy2":strategy2_results,"strategy3":strategy3_results}


@app.post("/internal/aster-strategy3/tick")
def run_aster_strategy3_scheduler(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Run only the normal Strategy-3 loop; rapid build and other engines stay isolated."""
    verify_internal_cloud_request(authorization)
    live_gates = (
        os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
        and os.getenv("ASTER_STRATEGY3_LIVE_ENABLED", "false").lower() == "true"
        and os.getenv("ASTER_STRATEGY3_RUNTIME_ENABLED", "false").lower() == "true"
    )
    if not live_gates:
        return {"processed": 0, "status": "centrally-disabled", "strategy3": []}

    controls = list(db.collection("asterStrategy3").where("monitor", "==", True).stream())
    strategy3_results = []
    for item in controls[:100]:
        reference = aster_strategy3_reference(item.id)
        if not _acquire_mexc_automation_lease(reference):
            strategy3_results.append({"uid": item.id, "status": "lease-busy"})
            continue
        try:
            state = item.to_dict() or {}
            if bool(state.get("rapidBuildRequested")):
                reference.set({
                    "rapidBuildRequested": False,
                    "rapidBuildBlockedReason": "Dedicated live scheduler allows normal one-action ticks only",
                    "updatedAt": datetime.now(timezone.utc),
                }, merge=True)
            strategy3_results.append({"uid": item.id, **_run_aster_strategy3_tick(item.id)})
        except Exception as exc:
            message = f"Veilige Strategy-3-schedulerfout: {exc}"
            reference.set({
                "phase": "DATA_HOLD",
                "rapidBuildRequested": False,
                "lastReason": message,
                "lastTickAt": datetime.now(timezone.utc),
            }, merge=True)
            strategy3_results.append({"uid": item.id, "status": "data-hold", "reason": message})
        finally:
            reference.set({"leaseUntil": datetime.now(timezone.utc)}, merge=True)
    return {"processed": len(strategy3_results), "strategy3": strategy3_results}


@app.post("/internal/aster-automation/{uid}/simulate")
def run_aster_internal_simulation(uid: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    verify_internal_cloud_request(authorization)
    if not uid or len(uid)>128: raise HTTPException(422,"Ongeldige gebruiker")
    return _run_aster_automation_tick(uid,dry_run=True)


@app.post("/internal/aster-strategy2/{uid}/simulate")
def run_aster_strategy2_internal_simulation(uid:str,authorization:str|None=Header(default=None))->dict[str,Any]:
    verify_internal_cloud_request(authorization)
    if not uid or len(uid)>128:raise HTTPException(422,"Ongeldige gebruiker")
    return _run_aster_strategy2_tick(uid,dry_run=True)


@app.post("/internal/aster-strategy3/{uid}/simulate")
def run_aster_strategy3_internal_simulation(uid:str,authorization:str|None=Header(default=None))->dict[str,Any]:
    verify_internal_cloud_request(authorization)
    if not uid or len(uid)>128:raise HTTPException(422,"Ongeldige gebruiker")
    return _run_aster_strategy3_tick(uid,dry_run=True)


@app.get("/v1/me/hyperliquid/scanner/status")
def hyperliquid_scanner_status(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    return hyperliquid_scanner_public(str(user["uid"]))


@app.put("/v1/me/hyperliquid/scanner/settings")
def save_hyperliquid_scanner_settings(request: HyperliquidScannerSettingsRequest,
                                      user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    settings = _hyperliquid_scanner_settings(request.settings)
    uid = str(user["uid"])
    now = datetime.now(timezone.utc)
    batch = db.batch()
    batch.set(hyperliquid_scanner_reference(uid), {
        "uid": uid, "settings": settings.public_dict(), "updatedAt": now,
    }, merge=True)
    # There is one capacity value. Native preflight, web and the scheduler all
    # consume this exact Firestore value instead of maintaining duplicates.
    batch.set(user_reference(user).collection("settings").document("trading"), {
        "maxActivePositions": settings.max_active_deals, "updatedAt": now,
    }, merge=True)
    batch.commit()
    return {"saved": True, **hyperliquid_scanner_public(uid)}


@app.post("/v1/me/hyperliquid/scanner/simulate")
def simulate_hyperliquid_scanner(request: HyperliquidScannerSettingsRequest,
                                 user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    settings = _hyperliquid_scanner_settings(request.settings)
    return _run_hyperliquid_scanner_tick(
        str(user["uid"]), dry_run=True, ignore_monitor=True,
        settings_override=settings.public_dict(),
    )


@app.post("/v1/me/hyperliquid/scanner/start")
def start_hyperliquid_scanner(request: HyperliquidScannerStartRequest,
                              user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    require_verified_email(user)
    if not request.confirm:
        raise HTTPException(422, "Bevestig Scan & Buy met echt geld expliciet")
    if os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        raise HTTPException(409, "Hyperliquid-orderuitvoering staat centraal vergrendeld")
    address = linked_wallet(user)
    verified_agent_wallet(user, address)
    live = user_reference(user).collection("executionControls").document("liveTrading").get().to_dict() or {}
    if not bool(live.get("enabled", False)):
        raise HTTPException(409, "Activeer eerst persoonlijke Hyperliquid-livehandel")
    settings = _hyperliquid_scanner_settings(request.settings)
    uid = str(user["uid"])
    now = datetime.now(timezone.utc)
    batch = db.batch()
    batch.set(hyperliquid_scanner_reference(uid), {
        "uid": uid, "enabled": True, "monitor": True, "protectiveOnly": False,
        "phase": "queued", "lastReason": "Bevestigd; wacht op veilige cloudscan",
        "settings": settings.public_dict(), "activatedAt": now, "updatedAt": now,
    }, merge=True)
    batch.set(user_reference(user).collection("settings").document("trading"), {
        "maxActivePositions": settings.max_active_deals, "updatedAt": now,
    }, merge=True)
    batch.commit()
    return {"started": True, **hyperliquid_scanner_public(uid)}


@app.post("/v1/me/hyperliquid/scanner/stop")
def stop_hyperliquid_scanner(request: HyperliquidScannerStopRequest,
                             user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(422, "Bevestig de scannerstop expliciet")
    uid = str(user["uid"])
    hyperliquid_scanner_reference(uid).set({
        "enabled": False, "monitor": False, "protectiveOnly": False,
        "phase": "stopped", "lastReason": "Handmatig gestopt; geen nieuwe orders",
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {"stopped": True, **hyperliquid_scanner_public(uid)}


def _acquire_hyperliquid_scanner_lease(reference) -> bool:
    transaction = db.transaction()

    @firestore.transactional
    def acquire(txn) -> bool:
        value = reference.get(transaction=txn).to_dict() or {}
        now = datetime.now(timezone.utc)
        lease = value.get("leaseUntil")
        if isinstance(lease, datetime) and lease > now:
            return False
        txn.set(reference, {"leaseUntil": now + timedelta(minutes=12)}, merge=True)
        return True

    return acquire(transaction)


@app.post("/internal/hyperliquid-scanner/tick")
def run_hyperliquid_scanner_scheduler(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    verify_internal_cloud_request(authorization)
    if os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        return {"processed": 0, "status": "centrally-disabled", "results": []}
    controls = list(db.collection("hyperliquidScanners").where("monitor", "==", True).stream())
    results: list[dict[str, Any]] = []
    for item in controls[:100]:
        reference = hyperliquid_scanner_reference(item.id)
        if not _acquire_hyperliquid_scanner_lease(reference):
            results.append({"uid": item.id, "status": "lease-busy"})
            continue
        try:
            results.append(_run_hyperliquid_scanner_tick(item.id))
        except Exception as exc:
            reference.set({
                "phase": "data-hold", "lastReason": str(exc)[:300],
                "lastTickAt": datetime.now(timezone.utc), "updatedAt": datetime.now(timezone.utc),
            }, merge=True)
            results.append({"uid": item.id, "status": "data-hold", "reason": str(exc)[:300]})
        finally:
            reference.set({"leaseUntil": datetime.now(timezone.utc)}, merge=True)
    return {"processed": len(results), "results": results}


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
        "ordersEnabled": os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() == "true",
    }


@app.put("/v1/me/execution/live")
def set_live_trading(request: LiveTradingToggleRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = linked_wallet(user)
    verified_agent_wallet(user, address)
    enabled = bool(request.enabled)
    if enabled:
        require_verified_email(user)
    user_reference(user).collection("executionControls").document("liveTrading").set({
        "enabled": enabled, "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {
        "enabled": enabled,
        "ordersEnabled": enabled and os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() == "true",
    }


def _epoch_millis(value: Any) -> int:
    if hasattr(value, "timestamp"):
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return 0
    return 0


def _external_cash_flow(address: str, started_at: Any) -> tuple[float, bool]:
    """Return deposits minus withdrawals since cycle start.

    Trading PnL and manual closes are deliberately absent. Hyperliquid's
    official non-funding ledger contains deposits/transfers/withdrawals; only
    real account cash in/out changes the performance baseline.
    """
    started_ms = _epoch_millis(started_at)
    if started_ms <= 0:
        return 0.0, False
    try:
        response = httpx.post(
            f"{constants.MAINNET_API_URL}/info",
            json={
                "type": "userNonFundingLedgerUpdates",
                "user": address,
                "startTime": started_ms,
                "endTime": int(time.time() * 1000),
            },
            timeout=10.0,
        )
        response.raise_for_status()
        updates = response.json()
        net = 0.0
        for update in updates if isinstance(updates, list) else []:
            delta = (update or {}).get("delta", {}) or {}
            kind = str(delta.get("type", "")).lower()
            usdc = abs(float(delta.get("usdc", 0) or 0))
            fee = abs(float(delta.get("fee", 0) or 0))
            if kind == "deposit":
                net += usdc
            elif kind == "withdraw":
                net -= usdc + fee
        return net, True
    except Exception:
        return 0.0, False


def _cycle_payload(data: dict[str, Any], current_value: float, address: str) -> dict[str, Any]:
    original_start = float(data.get("startPortfolioValue", 0) or 0)
    cash_flow, cash_flow_complete = _external_cash_flow(address, data.get("startedAt"))
    target_percentage = float(data.get("targetPercentage", 10) or 10)
    values = cycle_payload_values(original_start, current_value, target_percentage, cash_flow)
    return {
        "status": str(data.get("status", "inactive")),
        "startPortfolioValue": values["adjustedStartPortfolioValue"],
        "originalStartPortfolioValue": original_start,
        "externalCashFlowUsd": cash_flow,
        "cashFlowDataComplete": cash_flow_complete,
        "currentPortfolioValue": current_value,
        "targetPercentage": target_percentage,
        "targetPortfolioValue": values["targetPortfolioValue"],
        "growthPercentage": values["growthPercentage"],
        "remainingUsd": values["remainingUsd"],
        "progressPercentage": values["progressPercentage"],
        "startedAt": data.get("startedAt"),
        "startedAtEpochMs": _epoch_millis(data.get("startedAt")),
    }


@app.post("/v1/me/trading/cycle/start")
def start_trading_cycle(request: TradingCycleStartRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = linked_wallet(user)
    verified_agent_wallet(user, address)
    cycle_ref = user_reference(user).collection("executionControls").document("tradingCycle")
    existing = cycle_ref.get().to_dict() or {}
    current_value = request.portfolio_value if request.portfolio_value is not None else request.available_to_trade
    if current_value is None:
        current_value = safe_float(_hyperliquid_account_truth(address).get("portfolioValue"))
    existing_status = str(existing.get("status", "inactive"))
    open_positions = list(all_positions(address))
    start_decision = cycle_start_decision(existing_status, len(open_positions))
    if start_decision == "continue":
        return {**_cycle_payload(existing, current_value, address), "continuedExistingCycle": True}
    if start_decision == "blocked":
        raise HTTPException(
            409,
            f"Nieuwe cyclus geblokkeerd: Hyperliquid bevestigt nog {len(open_positions)} actieve positie(s)",
        )
    if current_value <= 0:
        raise HTTPException(422, "Portfoliowaarde ontbreekt; de cyclus is niet gestart")
    now = datetime.now(timezone.utc)
    data = {"status": "active", "startPortfolioValue": current_value, "targetPercentage": request.target_percentage, "startedAt": now, "updatedAt": now}
    cycle_ref.set(data)
    return _cycle_payload(data, current_value, address)


@app.post("/v1/me/trading/cycle/status")
def trading_cycle_status(request: TradingCycleEvaluateRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = linked_wallet(user)
    data = user_reference(user).collection("executionControls").document("tradingCycle").get().to_dict() or {}
    current_value = request.portfolio_value if request.portfolio_value is not None else request.available_to_trade
    if current_value is None:
        current_value = safe_float(_hyperliquid_account_truth(address).get("portfolioValue"))
    return _cycle_payload(data, current_value, address)


@app.put("/v1/me/trading/cycle/target")
def update_trading_cycle_target(request: TradingCycleTargetRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    cycle_ref = user_reference(user).collection("executionControls").document("tradingCycle")
    data = cycle_ref.get().to_dict() or {}
    if data.get("status") != "active":
        raise HTTPException(409, "Er is geen actieve DCA-portfoliocyclus")
    current_target = float(data.get("targetPercentage", 10) or 10)
    if request.target_percentage < current_target:
        raise HTTPException(422, "Tijdens een actieve cyclus kan het doel alleen worden verhoogd")
    address = linked_wallet(user)
    current_value = safe_float(_hyperliquid_account_truth(address).get("portfolioValue"))
    data.update({"targetPercentage": request.target_percentage, "updatedAt": datetime.now(timezone.utc)})
    cycle_ref.set(data, merge=True)
    return _cycle_payload(data, current_value, address)


@app.post("/v1/me/trading/cycle/evaluate")
def evaluate_trading_cycle(request: TradingCycleEvaluateRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    reference = user_reference(user)
    cycle_ref = reference.collection("executionControls").document("tradingCycle")
    data = cycle_ref.get().to_dict() or {}
    address = linked_wallet(user)
    current_value = request.portfolio_value if request.portfolio_value is not None else request.available_to_trade
    if current_value is None:
        current_value = safe_float(_hyperliquid_account_truth(address).get("portfolioValue"))
    payload = _cycle_payload(data, current_value, address)
    if data.get("status") != "active" or current_value + 1e-9 < payload["targetPortfolioValue"]:
        return {**payload, "targetReached": False, "closed": []}
    if os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        orders_locked()
    transaction = db.transaction()

    @firestore.transactional
    def claim(txn):
        latest = cycle_ref.get(transaction=txn).to_dict() or {}
        if latest.get("status") != "active":
            return False
        now = datetime.now(timezone.utc)
        txn.set(cycle_ref, {"status": "closing", "targetReachedAt": now, "updatedAt": now}, merge=True)
        txn.set(reference.collection("executionControls").document("liveTrading"), {"enabled": False, "disabledReason": "portfolio_target_reached", "updatedAt": now}, merge=True)
        return True

    if not claim(transaction):
        return {**payload, "targetReached": True, "closed": [], "duplicate": True}
    wallet = verified_agent_wallet(user, address)
    exchange = Exchange(
        wallet, constants.MAINNET_API_URL, account_address=address,
        perp_dexs=execution_perp_dex_names(),
    )
    positions_snapshot = list(all_positions(address))

    def cancel_reduce_only(symbol: str) -> int:
        cancelled = 0
        for order in all_frontend_open_orders(address):
            if str(order.get("coin", "")).upper() == symbol and bool(order.get("reduceOnly", False)):
                exchange.cancel(symbol, int(order["oid"]))
                cancelled += 1
        return cancelled

    def close_position(symbol: str, size: float) -> None:
        mids = exchange.info.all_mids(symbol.split(":", 1)[0] if ":" in symbol else "")
        mark = float(mids[symbol])
        response = exchange.market_close(symbol, sz=size, px=mark, slippage=MAX_SLIPPAGE)
        statuses = (((response or {}).get("response") or {}).get("data") or {}).get("statuses") or []
        if not statuses or not any("filled" in status for status in statuses):
            raise ValueError(f"sluiting niet bevestigd: {statuses}")

    close_report = execute_close_all(positions_snapshot, cancel_reduce_only, close_position)
    invalidate_positions(address)
    remaining_positions = [str(position.get("coin", "")).upper() for position in all_positions(address)]
    failures = list(close_report["failed"])
    for symbol in remaining_positions:
        if not any(item.get("symbol") == symbol for item in failures):
            failures.append({"symbol": symbol, "reason": "positie bleef na Close All zichtbaar"})
    final_value = safe_float(_hyperliquid_account_truth(address).get("portfolioValue")) or current_value
    final_status = "completed" if not failures else "completed_with_failures"
    cycle_ref.set({
        "status": final_status,
        "endPortfolioValue": final_value,
        "closed": close_report["closed"],
        "failed": failures,
        "completedAt": datetime.now(timezone.utc),
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {
        **_cycle_payload({**data, "status": final_status}, final_value, address),
        "targetReached": True,
        "closed": close_report["closed"],
        "failed": failures,
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
    if request.strategy_id == "strategy_3":
        if False and request.leverage > 5:
            raise HTTPException(422, "DCA Pulse staat maximaal 5× hefboom toe")
        if False and not (request.take_profit_enabled or request.trailing_take_profit_enabled or request.stop_loss_enabled):
            raise HTTPException(422, "DCA Pulse vereist minimaal één actieve uitstapbeveiliging")
        if False and not request.stop_loss_enabled:
            raise HTTPException(422, "DCA Pulse vereist voor live handel altijd een harde stop-loss")
        universe = aster_usdt_universe_snapshot(request.top_universe_size).public_dict()
        if universe["entryBlocked"]:
            raise HTTPException(503, str(universe["entryBlockReason"]))
        allowed = {str(symbol).upper().removesuffix("USDT") for symbol in universe["selectedSymbols"]}
        base_symbol = request.symbol.split(":")[-1].split("/")[0].split("-")[0].upper()
        candidates = {base_symbol}
        if base_symbol.startswith("K") and len(base_symbol) > 2:
            candidates.add(base_symbol[1:])
        if base_symbol.startswith("1000") and len(base_symbol) > 5:
            candidates.add(base_symbol[4:])
        if not candidates.intersection(allowed):
            raise HTTPException(422, f"DCA Pulse staat uitsluitend actuele Aster USDT Top-{request.top_universe_size}-markten toe")
    address = linked_wallet(user)
    settings = reference.collection("settings").document("trading").get().to_dict() or {}
    maximum = int(settings.get("maxActivePositions", settings.get("maxActiveTrades", 40)))
    configured_value = float(settings.get("positionSizeUsd", request.position_value_usd))
    if request.strategy_id != "strategy_3" and request.position_value_usd > configured_value + 0.001:
        raise HTTPException(422, "Orderbedrag is hoger dan het persoonlijk ingestelde instapbedrag")
    if request.strategy_id == "strategy_3" and False:
        account = _hyperliquid_account_truth(address, asset=request.symbol)
        equity = safe_float(account.get("portfolioValue"))
        current_notional = sum(abs(float(p.get("positionValue", 0) or 0)) for p in all_positions(address))
        if equity <= 0:
            raise HTTPException(422, "Portfoliowaarde ontbreekt; DCA-order blijft geblokkeerd")
        if request.position_value_usd > max(10.0, equity * 0.10):
            raise HTTPException(422, "De basisorder is groter dan 10% van de portfoliowaarde")
        if current_notional + request.position_value_usd > equity * 0.75:
            raise HTTPException(422, "De totale blootstelling zou boven 75% van de portfoliowaarde komen")
    plan = build_execution_plan(ExecutionPlanRequest(
        idempotency_key=request.idempotency_key, kind="entry",
        **request.model_dump(exclude={
            "idempotency_key", "max_adverse_percentage", "strategy_id",
            "take_profit_enabled", "trailing_take_profit_enabled",
            "trailing_deviation_percentage", "stop_loss_enabled", "top_universe_size",
        })
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
    target = 0.0
    tp_order_id = None
    # A trailing exit is maintained by DCA Pulse after its activation target.
    # Therefore a static TP must not close the position at the activation price.
    if request.take_profit_enabled and not request.trailing_take_profit_enabled:
        raw_target = fill_price * (1.0 - request.profit_percentage / 100.0 if request.short else 1.0 + request.profit_percentage / 100.0)
        target = round(float(f"{raw_target:.5g}"), price_decimals)
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

    stop_price = 0.0
    sl_order_id = None
    if request.stop_loss_enabled:
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
        "strategyId": request.strategy_id,
        "trailingTakeProfitEnabled": request.trailing_take_profit_enabled,
        "trailingDeviationPercentage": request.trailing_deviation_percentage,
        "updatedAt": datetime.now(timezone.utc),
    }
    batch = db.batch()
    batch.set(intent_ref, result, merge=True)
    batch.set(lease_ref, {"active": False, "updatedAt": datetime.now(timezone.utc)}, merge=True)
    if request.strategy_id == "strategy_3":
        dca_symbol_id = hashlib.sha256(f"{uid}:{plan['symbol'].upper()}".encode()).hexdigest()
        batch.set(reference.collection("dcaDeals").document(dca_symbol_id), {
            "symbol": plan["symbol"], "strategyId": request.strategy_id,
            "shortDirection": request.short,
            "initialEntryPrice": fill_price, "lastOrderPrice": fill_price,
            "safetyOrdersCompleted": 0, "updatedAt": datetime.now(timezone.utc),
        })
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
    failed: list[dict[str, str]] = []

    for position in positions:
        symbol = str(position.get("coin", "")).strip()
        if not symbol:
            continue
        has_tp = symbol.upper() in take_profit_symbols
        has_sl = symbol.upper() in stop_loss_symbols
        needs_static_tp = request.take_profit_enabled and not request.trailing_take_profit_enabled
        needs_sl = request.stop_loss_enabled
        if request.strategy_id == "strategy_3":
            # Settings changes also apply to running DCA Pulse positions. Remove
            # obsolete static exits before evaluating which protection is needed.
            for order in open_orders:
                if str(order.get("coin", "")).upper() != symbol.upper() or not bool(order.get("reduceOnly", False)):
                    continue
                order_type = str(order.get("orderType", "")).lower()
                if ("take profit" in order_type and not needs_static_tp) or ("stop" in order_type and not needs_sl):
                    try:
                        exchange.cancel(symbol, int(order["oid"]))
                    except Exception as exc:
                        failed.append({"symbol": symbol, "reason": f"oude bescherming kon niet worden verwijderd: {str(exc)[:120]}"})
                        continue
            if not needs_static_tp:
                has_tp = False
            if not needs_sl:
                has_sl = False
        if (has_tp or not needs_static_tp) and (has_sl or not needs_sl):
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
            if needs_static_tp and not has_tp:
                response = exchange.order(
                    symbol, signed_size < 0, abs(signed_size), target,
                    {"trigger": {"triggerPx": target, "isMarket": True, "tpsl": "tp"}},
                    reduce_only=True,
                )
                status = response["response"]["data"]["statuses"][0]
                if "resting" not in status:
                    raise ValueError(str(status.get("error", "TP niet bevestigd")))
            if needs_sl and not has_sl:
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
        "takeProfitEnabled": request.take_profit_enabled,
        "trailingTakeProfitEnabled": request.trailing_take_profit_enabled,
        "stopLossEnabled": request.stop_loss_enabled,
        "positionsChecked": len(positions),
        "alreadyProtected": already_protected,
        "repaired": repaired,
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
        "closedAtTarget": [],
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
def dca_add_on(request: DcaAddOnRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Execute one idempotent averaging order and rebuild protection for the full position."""
    if os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        orders_locked()
    reference = user_reference(user)
    live_ref = reference.collection("executionControls").document("liveTrading")
    live = live_ref.get().to_dict() or {}
    if not live.get("enabled", False):
        raise HTTPException(423, "Scan & Buy staat voor dit account uit")
    if request.safety_order_index > request.max_safety_orders:
        raise HTTPException(422, "Het ingestelde maximum aantal DCA-orders is bereikt")
    if request.strategy_id != "strategy_3" and not (request.take_profit_enabled or request.trailing_take_profit_enabled or request.stop_loss_enabled):
        raise HTTPException(422, "Minimaal één actieve uitstapbeveiliging is vereist")
    if request.strategy_id == "strategy_3":
        ranked = []
        allowed = {str(item.get("symbol", "")).upper() for item in ranked}
        base_symbol = request.symbol.split(":")[-1].split("/")[0].split("-")[0].upper()
        candidates = {base_symbol}
        if base_symbol.startswith("K") and len(base_symbol) > 2:
            candidates.add(base_symbol[1:])
        if base_symbol.startswith("1000") and len(base_symbol) > 5:
            candidates.add(base_symbol[4:])
        if False and not candidates.intersection(allowed):
            raise HTTPException(422, "DCA Pulse staat uitsluitend actuele Aster USDT Top-N-markten toe")
        if False and request.leverage > 5:
            raise HTTPException(422, "DCA Pulse staat maximaal 5× hefboom toe")
        if False and not request.stop_loss_enabled:
            raise HTTPException(422, "DCA Pulse vereist voor live handel altijd een harde stop-loss")

    address = linked_wallet(user)
    wallet = verified_agent_wallet(user, address)
    settings = reference.collection("settings").document("trading").get().to_dict() or {}
    maximum = int(settings.get("maxActivePositions", settings.get("maxActiveTrades", 40)))
    if request.strategy_id != "strategy_3":
        configured_value = float(settings.get("positionSizeUsd", request.position_value_usd))
        if request.position_value_usd > configured_value + 0.001:
            raise HTTPException(422, "Bijkoopbedrag is hoger dan het persoonlijk ingestelde instapbedrag")
    elif False:
        account = _hyperliquid_account_truth(address, asset=request.symbol)
        equity = safe_float(account.get("portfolioValue"))
        current_notional = sum(abs(float(p.get("positionValue", 0) or 0)) for p in all_positions(address))
        if equity <= 0:
            raise HTTPException(422, "Portfoliowaarde ontbreekt; DCA-order blijft geblokkeerd")
        if request.max_deal_value_usd > max(20.0, equity * 0.30):
            raise HTTPException(422, "De geplande DCA-deal is groter dan 30% van de portfoliowaarde")
        if request.position_value_usd > max(10.0, equity * 0.10):
            raise HTTPException(422, "Deze DCA-order is groter dan 10% van de portfoliowaarde")
        if current_notional + request.position_value_usd > equity * 0.75:
            raise HTTPException(422, "De totale blootstelling zou boven 75% van de portfoliowaarde komen")
    plan = build_execution_plan(ExecutionPlanRequest(
        idempotency_key=request.idempotency_key,
        symbol=request.symbol,
        kind="add_on",
        short=request.short,
        position_value_usd=request.position_value_usd,
        leverage=request.leverage,
        signal_price=request.signal_price,
        profit_percentage=request.profit_percentage,
    ), address, maximum)
    existing = next(
        (p for p in all_positions(address) if str(p.get("coin", "")).upper() == request.symbol.upper()),
        None,
    )
    current_value = abs(float((existing or {}).get("positionValue", 0) or 0))
    if current_value + plan["positionValueUsd"] > request.max_deal_value_usd * 1.01:
        raise HTTPException(422, "Deze DCA-order overschrijdt de maximale geplande dealwaarde")

    uid = str(user["uid"])
    intent_id = hashlib.sha256(f"{uid}:{request.idempotency_key}".encode()).hexdigest()
    symbol_id = hashlib.sha256(f"{uid}:{request.symbol.upper()}".encode()).hexdigest()
    intent_ref = reference.collection("executions").document(intent_id)
    deal_ref = reference.collection("dcaDeals").document(symbol_id)
    transaction = db.transaction()

    @firestore.transactional
    def claim(txn):
        previous_intent = intent_ref.get(transaction=txn)
        if previous_intent.exists:
            data = previous_intent.to_dict() or {}
            if data.get("status") == "completed":
                return data
            raise HTTPException(409, "Deze DCA-order is al in behandeling")
        deal = deal_ref.get(transaction=txn).to_dict() or {}
        completed = int(deal.get("safetyOrdersCompleted", 0))
        if request.strategy_id == "strategy_3":
            if request.safety_order_index != completed + 1:
                raise HTTPException(409, "DCA-volgorde wijkt af; accountcontrole vereist")
            if completed >= request.max_safety_orders:
                raise HTTPException(409, "Het ingestelde maximum aantal DCA-orders is bereikt")
        now = datetime.now(timezone.utc)
        txn.set(intent_ref, {
            "status": "claimed_before_broadcast", "symbol": request.symbol,
            "strategyId": request.strategy_id, "safetyOrderIndex": request.safety_order_index,
            "createdAt": now, "updatedAt": now,
        })
        if request.strategy_id == "strategy_3":
            txn.set(deal_ref, {
                "symbol": request.symbol, "strategyId": request.strategy_id,
                "safetyOrdersCompleted": request.safety_order_index,
                "maxSafetyOrdersAtExecution": request.max_safety_orders, "updatedAt": now,
            }, merge=True)
        return None

    duplicate = claim(transaction)
    if duplicate:
        return {"accepted": True, "duplicate": True, **duplicate}

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
        live_ref.set({"enabled": False, "disabledReason": "dca_broadcast_failed", "updatedAt": datetime.now(timezone.utc)}, merge=True)
        raise HTTPException(502, "DCA-order niet volledig bevestigd; Scan & Buy is veilig gestopt") from exc

    try:
        invalidate_positions(address)
        updated = next(
            p for p in all_positions(address)
            if str(p.get("coin", "")).upper() == request.symbol.upper()
        )
        full_size = abs(float(updated.get("szi", 0) or 0))
        average_entry = float(updated.get("entryPx", 0) or 0)
        if full_size <= 0 or average_entry <= 0:
            raise ValueError("bijgewerkte positie ontbreekt")
        for order in all_frontend_open_orders(address):
            if str(order.get("coin", "")).upper() == request.symbol.upper() and bool(order.get("reduceOnly", False)):
                exchange.cancel(plan["symbol"], int(order["oid"]))

        asset = exchange.info.name_to_asset(plan["symbol"])
        decimals = max(0, 6 - exchange.info.asset_to_sz_decimals[asset])
        target = 0.0
        stop_price = 0.0
        if request.take_profit_enabled and not request.trailing_take_profit_enabled:
            raw_target = average_entry * (1.0 - request.profit_percentage / 100.0 if request.short else 1.0 + request.profit_percentage / 100.0)
            target = round(float(f"{raw_target:.5g}"), decimals)
            status = exchange.order(
                plan["symbol"], request.short, full_size, target,
                {"trigger": {"triggerPx": target, "isMarket": True, "tpsl": "tp"}}, reduce_only=True,
            )["response"]["data"]["statuses"][0]
            if "resting" not in status:
                raise ValueError("nieuwe take-profit niet bevestigd")
        if request.stop_loss_enabled:
            raw_stop = average_entry * (1.0 + request.max_adverse_percentage / 100.0 if request.short else 1.0 - request.max_adverse_percentage / 100.0)
            stop_price = round(float(f"{raw_stop:.5g}"), decimals)
            status = exchange.order(
                plan["symbol"], request.short, full_size, stop_price,
                {"trigger": {"triggerPx": stop_price, "isMarket": True, "tpsl": "sl"}}, reduce_only=True,
            )["response"]["data"]["statuses"][0]
            if "resting" not in status:
                raise ValueError("nieuwe stop-loss niet bevestigd")
    except Exception as exc:
        emergency_close = None
        try:
            emergency_close = exchange.market_close(plan["symbol"], slippage=MAX_SLIPPAGE)
        except Exception:
            pass
        intent_ref.set({"status": "dca_filled_protection_failed_locked", "emergencyClose": emergency_close, "updatedAt": datetime.now(timezone.utc)}, merge=True)
        live_ref.set({"enabled": False, "disabledReason": "dca_protection_failed", "updatedAt": datetime.now(timezone.utc)}, merge=True)
        raise HTTPException(502, "DCA-order gevuld maar bescherming kon niet worden herbouwd; noodsluiting gestart") from exc

    result = {
        "status": "completed", "accepted": True, "duplicate": False,
        "symbol": plan["symbol"], "short": request.short, "filledSize": filled_size,
        "fillPrice": fill_price, "targetPrice": target, "stopPrice": stop_price,
        "entryOrderId": entry_order_id, "strategyId": request.strategy_id,
        "safetyOrderIndex": request.safety_order_index, "updatedAt": datetime.now(timezone.utc),
    }
    intent_ref.set(result, merge=True)
    if request.strategy_id == "strategy_3":
        deal_ref.set({
            "shortDirection": request.short,
            "lastOrderPrice": fill_price,
            "safetyOrdersCompleted": request.safety_order_index,
            "updatedAt": datetime.now(timezone.utc),
        }, merge=True)
    invalidate_positions(address)
    return {k: v for k, v in result.items() if k not in ("status", "updatedAt")}


@app.get("/v1/me/dca/deals")
def dca_deals(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Central DCA counters keep every signed-in device consistent."""
    address = linked_wallet(user)
    positions = {str(item.get("coin", "")).upper(): item for item in all_positions(address)}
    deals: list[dict[str, Any]] = []
    for snapshot in user_reference(user).collection("dcaDeals").stream():
        data = snapshot.to_dict() or {}
        symbol = str(data.get("symbol", "")).upper()
        position = positions.get(symbol)
        if not symbol or position is None:
            continue
        entry = float(position.get("entryPx", 0) or 0)
        deals.append({
            "symbol": symbol,
            "strategyId": str(data.get("strategyId", "strategy_3")),
            "shortDirection": bool(data.get("shortDirection", float(position.get("szi", 0) or 0) < 0)),
            "initialEntryPrice": float(data.get("initialEntryPrice", entry) or entry),
            "lastOrderPrice": float(data.get("lastOrderPrice", entry) or entry),
            "safetyOrdersCompleted": int(data.get("safetyOrdersCompleted", 0) or 0),
        })
    return {"deals": deals}


@app.post("/v1/me/positions/{symbol}/close")
def close_position_manually(symbol: str, request: ManualCloseRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Explicitly confirmed reduce-only close for one open position, green or red."""
    if not request.confirm:
        raise HTTPException(422, "Bevestiging voor handmatig sluiten ontbreekt")
    if request.percentage not in ALLOWED_CLOSE_PERCENTAGES:
        raise HTTPException(422, "Sluitpercentage moet 25, 50, 75 of 100 zijn")
    if os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        orders_locked()
    address = linked_wallet(user)
    wallet = verified_agent_wallet(user, address)
    position = next(
        (p for p in all_positions(address) if str(p.get("coin", "")).upper() == symbol.upper()),
        None,
    )
    if position is None:
        raise HTTPException(404, "De actieve positie bestaat niet meer")
    exchange = Exchange(
        wallet, constants.MAINNET_API_URL, account_address=address,
        perp_dexs=execution_perp_dex_names(),
    )
    cancelled = 0
    try:
        # A partial reduce-only close leaves existing protective triggers in
        # place; they cannot reverse the position. A full close removes them.
        if request.percentage == 100:
            for order in all_frontend_open_orders(address):
                if str(order.get("coin", "")).upper() == symbol.upper() and bool(order.get("reduceOnly", False)):
                    exchange.cancel(symbol, int(order["oid"]))
                    cancelled += 1
        original_size = abs(float(position.get("szi", 0) or 0))
        size = close_size(original_size, request.percentage)
        mark = float(exchange.info.all_mids(symbol.split(":", 1)[0] if ":" in symbol else "")[symbol])
        exchange.market_close(symbol, sz=size, px=mark, slippage=MAX_SLIPPAGE)
    except Exception as exc:
        raise HTTPException(502, "Positie kon niet volledig reduce-only worden gesloten") from exc
    invalidate_positions(address)
    return {
        "closed": True,
        "symbol": symbol,
        "percentage": request.percentage,
        "closedSize": size,
        "remainingSizeEstimate": max(0.0, original_size - size),
        "cancelledOrders": cancelled,
    }


def _bitcoin_interval(duration_seconds: int) -> str:
    return {60: "1m", 300: "5m", 900: "15m", 3600: "1h", 14400: "4h", 86400: "1d"}[duration_seconds]


def _bitcoin_mark() -> float:
    return float(info.all_mids()["BTC"])


def _bitcoin_backtest(duration_seconds: int) -> dict[str, Any]:
    cached = _bitcoin_backtest_cache.get(duration_seconds)
    if cached and time.time() - cached[0] < min(60.0, max(10.0, duration_seconds / 2.0)):
        return cached[1]
    now_ms = int(time.time() * 1000)
    candles = info.candles_snapshot(
        "BTC", _bitcoin_interval(duration_seconds),
        now_ms - duration_seconds * 1000 * 1105, now_ms,
    )
    candles = sorted(candles, key=lambda item: int(item.get("t", 0) or 0))
    result = rolling_backtest(
        [float(item.get("c", 0) or 0) for item in candles],
        [int(item.get("t", 0) or 0) for item in candles],
        1000,
    )
    _bitcoin_backtest_cache[duration_seconds] = (time.time(), result)
    return result


def _serialize_bitcoin_trade(snapshot) -> dict[str, Any]:
    data = snapshot.to_dict() or {}
    result = {**data, "id": snapshot.id}
    for field in ("openedAt", "scheduledCloseAt", "closedAt", "createdAt"):
        value = result.get(field)
        if hasattr(value, "isoformat"):
            result[field] = value.isoformat()
    return result


def _close_bitcoin_trade(uid: str, trade_id: str, *, reason: str) -> dict[str, Any]:
    reference = db.collection("users").document(uid)
    trade_ref = reference.collection("bitcoinTrades").document(trade_id)
    trade = trade_ref.get().to_dict() or {}
    if not trade:
        raise HTTPException(404, "Bitcoin-trade bestaat niet")
    if trade.get("status") == "closed":
        return {**trade, "id": trade_id, "duplicate": True}
    if trade.get("status") not in {"open", "closing", "close_failed"}:
        raise HTTPException(409, "Bitcoin-trade heeft geen sluitbare status")
    user_data = reference.get().to_dict() or {}
    address = str(user_data.get("walletAddress", "")).lower()
    if not (address.startswith("0x") and len(address) == 42):
        raise HTTPException(409, "Gekoppelde wallet ontbreekt")
    trade_ref.set({"status": "closing", "closeReason": reason, "updatedAt": datetime.now(timezone.utc)}, merge=True)
    position = next((p for p in all_positions(address, force=True) if str(p.get("coin", "")).upper() == "BTC"), None)
    exit_price = _bitcoin_mark()
    if position is not None:
        wallet = verified_agent_wallet({"uid": uid}, address)
        exchange = Exchange(wallet, constants.MAINNET_API_URL, account_address=address, perp_dexs=execution_perp_dex_names())
        try:
            size = abs(float(position.get("szi", 0) or 0))
            response = exchange.market_close("BTC", sz=size, px=exit_price, slippage=MAX_SLIPPAGE)
            statuses = (((response or {}).get("response") or {}).get("data") or {}).get("statuses") or []
            filled = next((item.get("filled") for item in statuses if isinstance(item, dict) and item.get("filled")), None)
            if not filled:
                raise ValueError(f"sluiting niet bevestigd: {statuses}")
            exit_price = float(filled.get("avgPx", exit_price) or exit_price)
        except Exception as exc:
            trade_ref.set({"status": "close_failed", "closeError": str(exc)[:300], "updatedAt": datetime.now(timezone.utc)}, merge=True)
            raise HTTPException(502, "Automatische BTC-sluiting is nog niet bevestigd; server blijft herstel proberen") from exc
    entry_price = float(trade.get("entryPrice", 0) or 0)
    result_pct = price_result(bool(trade.get("short", False)), entry_price, exit_price)
    stake = float(trade.get("stakeUsd", 0) or 0)
    pnl = stake * result_pct / 100.0
    now = datetime.now(timezone.utc)
    final = {
        "status": "closed", "exitPrice": exit_price, "resultPercentage": result_pct,
        "realizedPnlUsdEstimate": pnl, "closedAt": now, "closeReason": reason, "updatedAt": now,
    }
    trade_ref.set(final, merge=True)
    invalidate_positions(address)
    return {**trade, **final, "id": trade_id, "duplicate": False}


def _schedule_bitcoin_close(uid: str, trade_id: str, close_at: datetime) -> str:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "tradementor-production")
    location = os.getenv("BTC_TASK_LOCATION", "europe-west1")
    queue = os.getenv("BTC_TASK_QUEUE", "bitcoin-trade-close")
    base_url = os.getenv("BTC_TASK_BASE_URL", "https://tradementor-api-cyyaq5otyq-ez.a.run.app").rstrip("/")
    service_account = os.getenv("BTC_TASK_SERVICE_ACCOUNT", f"{project}@appspot.gserviceaccount.com")
    parent = tasks_client.queue_path(project, location, queue)
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(close_at)
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{base_url}/internal/bitcoin-trades/{uid}/{trade_id}/close",
            "oidc_token": {"service_account_email": service_account, "audience": base_url},
        },
        "schedule_time": timestamp,
    }
    return tasks_client.create_task(request={"parent": parent, "task": task}).name


@app.post("/v1/me/bitcoin/signal")
def bitcoin_signal(request: BitcoinSignalRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if request.duration_seconds not in ALLOWED_DURATIONS:
        raise HTTPException(422, "Ongeldige Bitcoin-looptijd")
    now_ms = int(time.time() * 1000)
    interval = _bitcoin_interval(request.duration_seconds)
    candles = info.candles_snapshot("BTC", interval, now_ms - request.duration_seconds * 1000 * 80, now_ms)
    closes = [float(item.get("c", 0) or 0) for item in candles]
    signal = directional_signal(closes)
    price = _bitcoin_mark()
    now = datetime.now(timezone.utc)
    prediction_ref = user_reference(user).collection("bitcoinPredictions").document()
    prediction_ref.set({
        "durationSeconds": request.duration_seconds, "direction": signal["direction"],
        "confidence": signal["confidence"], "reason": signal["reason"], "predictionPrice": price,
        "predictedAt": now, "expiresAtEpochMs": now_ms + request.duration_seconds * 1000,
    })
    return {**signal, "price": price, "durationSeconds": request.duration_seconds, "predictionId": prediction_ref.id}


@app.get("/v1/me/bitcoin/state")
def bitcoin_state(duration_seconds: int = Query(default=300), user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if duration_seconds not in ALLOWED_DURATIONS:
        raise HTTPException(422, "Ongeldige Bitcoin-looptijd")
    reference = user_reference(user)
    current_price = _bitcoin_mark()
    backtest = _bitcoin_backtest(duration_seconds)
    serialized_predictions = backtest["predictions"]
    wins = int(backtest["won"])
    resolved = wins + int(backtest["lost"])
    trades = [_serialize_bitcoin_trade(item) for item in reference.collection("bitcoinTrades").limit(100).stream()]
    active = next((item for item in trades if item.get("status") in {"open", "closing", "close_failed"}), None)
    return {
        "currentPrice": current_price, "activeTrade": active, "trades": trades,
        "predictions": serialized_predictions[:1000], "resolvedPredictions": resolved,
        "wonPredictions": wins, "lostPredictions": resolved - wins,
        "averageWinningPercentage": float(backtest["averageWinningPercentage"]),
        "successPercentage": (wins / resolved * 100.0) if resolved else 0.0,
        "minimumStakeUsd": MIN_STAKE_USD, "maximumStakeUsd": MAX_STAKE_USD,
    }


@app.post("/v1/me/bitcoin/trades")
def open_bitcoin_trade(request: BitcoinTradeOpenRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(422, "Bevestiging ontbreekt")
    try:
        validate_trade(request.duration_seconds, request.stake_usd)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        orders_locked()
    reference = user_reference(user)
    address = linked_wallet(user)
    if any(str(p.get("coin", "")).upper() == "BTC" for p in all_positions(address, force=True)):
        raise HTTPException(409, "Er bestaat al een Bitcoin-positie; gelijktijdige BTC-trades zijn geblokkeerd")
    open_trades = [s for s in reference.collection("bitcoinTrades").limit(20).stream() if (s.to_dict() or {}).get("status") in {"open", "closing", "close_failed"}]
    if open_trades:
        raise HTTPException(409, "Er loopt al een Bitcoin Trade Casino-positie")
    recent = [s.to_dict() or {} for s in reference.collection("bitcoinTrades").limit(20).stream()]
    latest_epoch = max((_epoch_millis(item.get("openedAt")) for item in recent), default=0)
    if int(time.time() * 1000) - latest_epoch < 10_000:
        raise HTTPException(429, "Wacht minimaal 10 seconden tussen Bitcoin-orders")
    account = _hyperliquid_account_truth(address, asset="BTC")
    available = direction_available(account, request.short)
    if request.stake_usd > available:
        raise HTTPException(422, "Onvoldoende vrij beschikbaar saldo voor deze inzet")
    wallet = verified_agent_wallet(user, address)
    exchange = Exchange(wallet, constants.MAINNET_API_URL, account_address=address, perp_dexs=execution_perp_dex_names())
    mark = _bitcoin_mark()
    decimals = info.asset_to_sz_decimals[info.name_to_asset("BTC")]
    factor = 10 ** decimals
    size = math.floor((request.stake_usd / mark) * factor) / factor
    if size <= 0 or size * mark < MIN_STAKE_USD:
        raise HTTPException(422, "Afgeronde Bitcoin-order is kleiner dan de minimuminzet")
    exchange.update_leverage(1, "BTC", is_cross=True)
    response = exchange.market_open("BTC", not request.short, size, px=mark, slippage=MAX_SLIPPAGE)
    statuses = (((response or {}).get("response") or {}).get("data") or {}).get("statuses") or []
    filled = next((item.get("filled") for item in statuses if isinstance(item, dict) and item.get("filled")), None)
    if not filled:
        raise HTTPException(502, "Bitcoin-instap is niet door Hyperliquid bevestigd")
    fill_price = float(filled.get("avgPx", mark) or mark)
    now = datetime.now(timezone.utc)
    close_at = now + timedelta(seconds=request.duration_seconds)
    trade_id = hashlib.sha256(f"{user['uid']}:{request.idempotency_key}".encode()).hexdigest()
    trade_ref = reference.collection("bitcoinTrades").document(trade_id)
    trade_ref.set({
        "status": "open", "symbol": "BTC", "short": request.short, "stakeUsd": request.stake_usd,
        "filledSize": float(filled.get("totalSz", size) or size), "entryPrice": fill_price,
        "durationSeconds": request.duration_seconds, "openedAt": now, "scheduledCloseAt": close_at,
        "estimatedEntryFeeUsd": request.stake_usd * 0.00045, "updatedAt": now,
    })
    try:
        task_name = _schedule_bitcoin_close(str(user["uid"]), trade_id, close_at)
        trade_ref.set({"closeTaskName": task_name}, merge=True)
    except Exception as exc:
        _close_bitcoin_trade(str(user["uid"]), trade_id, reason="planning_failed_emergency_close")
        raise HTTPException(502, "Timerplanning mislukte; de geopende positie is direct veilig gesloten") from exc
    invalidate_positions(address)
    return _serialize_bitcoin_trade(trade_ref.get())


@app.post("/v1/me/bitcoin/trades/{trade_id}/close")
def close_bitcoin_trade_manually(trade_id: str, request: BitcoinTradeCloseRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(422, "Bevestiging ontbreekt")
    return _close_bitcoin_trade(str(user["uid"]), trade_id, reason="manual")


@app.post("/internal/bitcoin-trades/{uid}/{trade_id}/close")
def close_bitcoin_trade_scheduled(uid: str, trade_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    base_url = os.getenv("BTC_TASK_BASE_URL", "https://tradementor-api-cyyaq5otyq-ez.a.run.app").rstrip("/")
    expected_email = os.getenv("BTC_TASK_SERVICE_ACCOUNT", f"{os.getenv('GOOGLE_CLOUD_PROJECT', 'tradementor-production')}@appspot.gserviceaccount.com")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Cloud Tasks-token ontbreekt")
    try:
        claims = google_id_token.verify_oauth2_token(authorization.removeprefix("Bearer ").strip(), google_auth_requests.Request(), audience=base_url)
        if str(claims.get("email", "")).lower() != expected_email.lower():
            raise ValueError("onverwacht serviceaccount")
    except Exception as exc:
        raise HTTPException(401, "Ongeldige Cloud Tasks-identiteit") from exc
    return _close_bitcoin_trade(uid, trade_id, reason="timer_expired")
