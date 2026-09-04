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
import asyncio
from urllib.parse import quote
from dataclasses import replace
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import firebase_admin
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
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
from aster_universe import AsterUniverseSnapshot, build_snapshot as build_aster_universe_snapshot, entry_fill_symbols, normalize_top_n, server_snapshot_contract, side_entry_candidates, stale_snapshot as stale_aster_universe_snapshot
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
from aster_history import closed_trades_from_fills, realized_events_from_income, merge_realized_events, merge_recent_trade_activity, recent_trade_activity_from_fills, trade_events_from_fills
from aster_strategy import AsterStrategySettings
from aster_strategy2 import PortfolioState as Strategy2PortfolioState, Strategy2Config, validate_worst_case, trend_bollinger_entry_check
from aster_strategy2_simulation import standard_suite as strategy2_standard_suite, failure_suite as strategy2_failure_suite
from aster_strategy2_state import OwnedLeg, reconcile_owned_legs
from aster_strategy2_readiness import build_readiness_report
from aster_canary import choose_flat_symbol, existing_canary_action
from aster_strategy2 import Decision
from aster_cost_evidence import bounded_history_symbols, cost_refresh_symbols, paged_user_trades, refresh_owned_costs
from aster_strategy_status import (operating_status_contract, ownership_reason_contract,
    position_count_contract, proven_owned_rows, reconciled_ownership_update)
from aster_strategy2_execution import ExecutionContext, Strategy2RiskBlocked, execute_decision as execute_aster_strategy2_decision
from aster_strategy2_runtime import owned_from_mapping, owned_to_mapping, recover_audited_ownership, portfolio_state as strategy2_portfolio_state
from aster_strategy2_runtime import next_management_decision, next_dca_decision, scanner_allowed, active_position_map, cost_evidence_max_age_seconds
from aster_strategy2_runtime import changed_owned_symbols, most_urgent_profitable_owned, isolate_unproven_ownership
from aster_strategy2_runtime import enrich_confirmed_costs
from aster_strategy2_runtime import scheduler_status as strategy2_scheduler_status, strategy2_fixed_dca_ladder, strategy2_position_tp_contract
from aster_strategy2_runtime import transfer_active_ownership_to_strategy2
from aster_strategy2_runtime import portfolio_protection_decision, same_pair_protection_decision
from aster_strategy2_runtime import balanced_entry_targets, harvest_counts, next_balanced_entry_side, queued_entry_order_limit, management_preempts_initial_build
from aster_strategy2_queue import MAX_ORDERS_PER_ACCOUNT_SCAN, QUEUE_FEATURE_FLAG
from aster_strategy2_focus_adapter import build_focus_shadow_report, focus_state_from_mapping, focus_state_to_mapping, advance_focus_shadow_state
from aster_strategy2_focus_adapter import current_focus_markets
from aster_strategy2_focus import FocusState, rank_focus_pairs, next_dca_trigger
from aster_strategy2_focus_live import run_focus_live_step
from aster_realtime import AsterRealtimeWorker, RealtimeMarketEvent, liquidation_distance_pct
from aster_strategy2_focus_cycle import cycle_state_to_mapping, reset_cycle
from aster_multi_bb import ENGINE as MULTI_BB_ENGINE, MultiBbConfig, run_multi_bb_step, leverage_tier_preview
from money_grabber import NetValueEvidence, start_round as start_money_grabber_round
from money_grabber_runtime import Position as MoneyGrabberPosition, ScanSnapshot as MoneyGrabberScanSnapshot, plan_scan as plan_money_grabber_scan, shadow_report as money_grabber_shadow_report
from money_grabber_state import pair_from_mapping as money_pair_from_mapping, round_from_mapping as money_round_from_mapping
from aster_strategy2_runtime import initial_build_high_water_mark
from aster_portfolio_replay import ReplayCandle, ReplaySeed, comparison_conclusion, config_with_overrides, run_portfolio_replay
from aster_strategy import Account as AsterStrategyAccount, Leg as AsterStrategyLeg, Pair as AsterStrategyPair
from aster_automation import TickMarket as AsterTickMarket, decide_tick as decide_aster_tick
from aster_execution import PairExecutionPlan, plan_pair as plan_aster_pair, execute_pair_once as execute_aster_pair
from aster_gateway import ContractRules
from aster_execution import execute_leg_once as execute_aster_leg, execute_harvest_reset as execute_aster_harvest
from aster_execution import execute_close_all as execute_aster_close_all
from aster_execution import configure_maximum_usable_leverage
from aster_execution import NewPositionLeverageBlocked, is_definite_contract_rejection
from aster_execution import contract_brackets, planning_brackets
from aster_close_guard import AsterCloseBlocked, BLOCK_MESSAGE, CloseEvidence
from aster_profit_close import MINIMUM_PROFIT_USD, position_profit, profit_preview, profitable_positions
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
from portfolio_growth import PORTFOLIO_GROWTH_START_DATE, average_daily_return, daily_return_percentage, estimate_close_value, external_cashflow_since, is_exposure_order, utc_ms
from admin_platform import classify_bot_health, safe_recovery_plan, incident_key
from reliability_monitor import event_key as reliability_event_key, event_payload as reliability_event_payload, counts as reliability_counts, overall as reliability_overall
from hyperliquid_account_state import direction_available, normalize_hyperliquid_account_state
from firebase_identity import check_revoked_tokens, identity_app, recent_id_token
from read_only_source import read_source_url


class Strategy2OrderBudgetExhausted(RuntimeError):
    """The persistent account-scan budget is full before another POST."""


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
_bot_health_platform_cache: tuple[float, dict[str, int]] = (0.0, {})


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


class AsterStrategy2FocusResetRequest(BaseModel):
    confirm: bool


class MoneyGrabberRoundStartRequest(BaseModel):
    confirm: bool
    preview_fingerprint: str = Field(min_length=16, max_length=128)


class AsterCloseAllRequest(BaseModel):
    confirm: bool
    quote_id: str = Field(min_length=16, max_length=120)
    idempotency_key: str = Field(min_length=16, max_length=120)


class PortfolioGrowthBaselineRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000_000)
    currency: str = Field(pattern="^USD$")
    confirm: bool


class PortfolioGrowthResetRequest(PortfolioGrowthBaselineRequest):
    reason: str = Field(min_length=10, max_length=500)


class AsterManualCloseRequest(BaseModel):
    confirm: bool
    side: str = Field(pattern="^(LONG|SHORT)$")
    expected_quantity: float = Field(gt=0)
    idempotency_key: str = Field(min_length=16, max_length=120)


class AsterProfitableCloseRequest(BaseModel):
    confirm: bool
    idempotency_key: str = Field(min_length=16, max_length=120)


class AsterCanaryRequest(BaseModel):
    confirm: bool
    notional_usd: float = Field(default=10.0, ge=5.0, le=12.0)


class AsterStrategy2CanaryRequest(BaseModel):
    """Separately bounded Strategy-2 open/fill/close canary."""
    confirm: bool
    notional_usd: float = Field(default=20.0, ge=5.0, le=20.0)


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


def portfolio_growth_reference(uid: str):
    return db.collection("users").document(uid).collection("portfolioGrowth").document("aster")


def _aster_close_all_active(uid: str) -> bool:
    value=portfolio_growth_reference(uid).get().to_dict() or {};lock=value.get("closeLock")
    if not isinstance(lock,dict) or not bool(lock.get("active")):return False
    until=lock.get("until")
    return not isinstance(until,datetime) or until>datetime.now(timezone.utc)


def _block_order_during_close_all(uid:str):
    def guard(_intent:AsterOrderIntent)->None:
        if _aster_close_all_active(uid):raise AsterValidationError("Accountgebonden Alles-sluiten-lock blokkeert deze order")
    return guard


def ensure_aster_strategy2_control(uid: str) -> dict[str, Any]:
    """Register every linked user with Strategy 2 without enabling trading.

    Existing state is never overwritten.  This closes the scheduler-discovery
    gap for migrated Aster users that have a valid secret but no Strategy-2
    control document yet.  Live execution still requires the user's persisted
    readiness, canary and explicit start confirmation.
    """
    ref=aster_strategy2_reference(uid);snapshot=ref.get()
    if snapshot.exists:return snapshot.to_dict() or {}
    now=datetime.now(timezone.utc)
    initial={"settings":Strategy2Config().public_dict(),"enabled":False,"monitor":False,
        "phase":"DRAFT","lastReason":"Strategy 2 automatisch geregistreerd; wacht op persoonlijke live-bevestiging",
        "liveReady":False,"canaryValidated":False,"unassignedPositions":0,
        "exclusiveOwnership":True,"createdAt":now,"updatedAt":now}
    try:ref.create(initial)
    except google_exceptions.AlreadyExists:pass
    return ref.get().to_dict() or initial


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


def _server_universe_contract(ref: Any, raw: dict[str, Any], requested_top_n: int) -> dict[str, Any]:
    """Return and persist a server-confirmed snapshot even when a bot is off.

    Strategy 2 and the isolated Strategy-3 service run in different Cloud Run
    projects, so process memory and a project-local Firestore document cannot
    be their shared source of truth.  Each service refreshes the same pure
    Aster contract directly from Aster and persists the resulting evidence in
    its own strategy document.  This method has no private signer and cannot
    submit an order.
    """
    stored = raw.get("universe") if isinstance(raw.get("universe"), dict) else None
    refreshed, should_persist = server_snapshot_contract(stored, requested_top_n, aster_usdt_universe_snapshot)
    if should_persist:
        ref.set({"universe": refreshed, "universeUpdatedAt": datetime.now(timezone.utc)}, merge=True)
    return refreshed


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


def aster_strategy2_public(uid: str) -> dict[str, Any]:
    ref = aster_strategy2_reference(uid)
    raw = ref.get().to_dict() or {}
    settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else MultiBbConfig().public_dict()
    if str(settings.get("engine",settings.get("strategyKind","")))==MULTI_BB_ENGINE:
        enabled=bool(raw.get("enabled",False)); monitor=bool(raw.get("monitor",False)); report=raw.get("multiBbReport") if isinstance(raw.get("multiBbReport"),dict) else {}
        managed=raw.get("multiBbPositions") if isinstance(raw.get("multiBbPositions"),dict) else {}
        long_count=sum(1 for key in managed if str(key).endswith("|LONG")); short_count=sum(1 for key in managed if str(key).endswith("|SHORT"))
        runtime_enabled=os.getenv("ASTER_STRATEGY2_LIVE_ENABLED","false").lower()=="true"
        return {"strategy2":{"settings":settings,"engine":MULTI_BB_ENGINE,"phase":str(raw.get("phase","CONFIGURED")),
            "displayPhase":"UIT" if not enabled else str(raw.get("phase","RUNNING")),"enabled":enabled,"monitor":monitor,
            "liveReady":bool(raw.get("liveReady",False)),"canaryValidated":bool(raw.get("canaryValidated",False)),"runtimeEnabled":runtime_enabled,
            "configVersion":int(safe_float(raw.get("configVersion",settings.get("version",1)))),"lastReason":str(raw.get("lastReason","Nog niet gestart")),
            "lastTickAt":raw.get("lastTickAt"),"activePairs":len({str(k).split("|",1)[0] for k in managed}),"activeLegs":len(managed),
            "longLegs":long_count,"shortLegs":short_count,"positionCounts":{"uniqueMarketCount":len({str(k).split("|",1)[0] for k in managed}),
                "positionLegCount":len(managed),"longLegs":long_count,"shortLegs":short_count},"multiBb":report,"multiBbPositions":managed,
            "universe":{"topN":int(settings.get("universeTopN",30)),"ranking":report.get("rankedTopN",[])},
            "operation":{"newEntries":{"blocked":not enabled,"reason":"bot staat uit" if not enabled else "directe slotvulling + Top-N + leveragefilter"},
                "existingPositionManagement":{"reason":"Exchange truth + TP/DCA beheer"}},"candidateScan":{"checked":len(report.get("rankedTopN",[])),"reasons":[]},
            "orderQueue":{"enabled":False,"maximumOrdersPerScan":MAX_ORDERS_PER_ACCOUNT_SCAN,"lastScanActions":report.get("actions",[])}}}
    owned=proven_owned_rows(raw.get("ownedLegs",[]),strategy_id="aster-strategy-2",engine_type="strategy2")
    universe=_server_universe_contract(ref,raw,int(settings.get("universeTopN",50)))
    counts=position_count_contract(owned,scope="strategy2-proven-owned")
    enabled=bool(raw.get("enabled",False));monitor=bool(raw.get("monitor",False))
    runtime_enabled=os.getenv("ASTER_STRATEGY2_LIVE_ENABLED","false").lower()=="true"
    account_snapshot=raw.get("accountSnapshot") if isinstance(raw.get("accountSnapshot"),dict) else {}
    captured=account_snapshot.get("capturedAt")
    if isinstance(captured,datetime):
        captured=captured.replace(tzinfo=timezone.utc) if captured.tzinfo is None else captured.astimezone(timezone.utc)
    exchange_data_fresh=bool(isinstance(captured,datetime) and timedelta(0)<=datetime.now(timezone.utc)-captured<=timedelta(seconds=120))
    operation=operating_status_contract(enabled=enabled,monitor=monitor,runtime_enabled=runtime_enabled,
        owned_leg_count=counts["positionLegCount"],universe=universe,exchange_data_fresh=exchange_data_fresh)
    queue_enabled=(os.getenv(QUEUE_FEATURE_FLAG,"false").lower()=="true" and bool(raw.get("orderQueueEnabled",False)))
    queue_state=raw.get("orderQueueState") if isinstance(raw.get("orderQueueState"),dict) else {}
    scan_history=[dict(x) for x in raw.get("scanActionHistory",[]) if isinstance(x,dict)] if isinstance(raw.get("scanActionHistory"),list) else []
    # orderAttributions is durable proof shared by queue and direct Strategy-2 execution.
    attributed=[dict(x) for x in raw.get("orderAttributions",[]) if isinstance(x,dict)] if isinstance(raw.get("orderAttributions"),list) else []
    dca_seen:dict[tuple[str,str,str],int]={};attribution_actions=[]
    def attribution_time(row:dict[str,Any])->float:
        value=row.get("recordedAt")
        if isinstance(value,datetime):return value.timestamp()
        try:return datetime.fromisoformat(str(value).replace("Z","+00:00")).timestamp()
        except (TypeError,ValueError):return 0.0
    for item in sorted(attributed,key=attribution_time):
        kind=str(item.get("action","")).upper();symbol=str(item.get("symbol","")).upper();side=str(item.get("side","")).upper()
        if not symbol or side not in {"LONG","SHORT"}:continue
        if kind not in {"INITIAL_OPEN_LEG","OPEN_LEG","ADD_DCA","PROTECTION_INCREASE","OPEN_PROTECTION","FULL_TP","PARTIAL_TP","TAKE_PROFIT_CLOSE","RISK_REDUCE","AUTO_RESTART","PENDING_REOPEN"}:continue
        cycle=str(item.get("cycleId",""));key=(symbol,side,cycle);dca_number=None
        if kind=="ADD_DCA":dca_seen[key]=dca_seen.get(key,0)+1;dca_number=dca_seen[key]+1
        attribution_actions.append({"clientOrderId":str(item.get("clientOrderId","")),"symbol":symbol,"side":side,"kind":kind,
            "action":"CLOSE" if kind in {"FULL_TP","PARTIAL_TP","TAKE_PROFIT_CLOSE","RISK_REDUCE"} else "OPEN",
            "dcaNumber":dca_number,"executedAt":item.get("recordedAt"),"cycleId":cycle})
    merged_actions:dict[str,dict[str,Any]]={}
    for item in [*attribution_actions,*scan_history]:
        identity=str(item.get("clientOrderId","")).strip() or "|".join(str(item.get(k,"")) for k in ("symbol","side","kind","executedAt"))
        merged_actions[identity]={**merged_actions.get(identity,{}),**item}
    def scan_action_time(row:dict[str,Any])->float:
        value=row.get("executedAt")
        if isinstance(value,datetime):return value.timestamp()
        try:return datetime.fromisoformat(str(value).replace("Z","+00:00")).timestamp()
        except (TypeError,ValueError):return 0.0
    scan_history=sorted(merged_actions.values(),key=scan_action_time)[-MAX_ORDERS_PER_ACCOUNT_SCAN:]
    mg_round=raw.get("moneyGrabberRound") if isinstance(raw.get("moneyGrabberRound"),dict) else None
    mg_pairs=raw.get("moneyGrabberPairs") if isinstance(raw.get("moneyGrabberPairs"),list) else []
    focus_live_mode=str(settings.get("tradingMode",""))=="focus" and str(settings.get("mode",""))=="live"
    focus_state=(raw.get("focusLiveState") if focus_live_mode else raw.get("focusShadowState"))
    focus_state=focus_state if isinstance(focus_state,dict) else {}
    focus_report=(raw.get("focusLiveReport") if focus_live_mode else raw.get("focusShadowReport"))
    focus_report=focus_report if isinstance(focus_report,dict) else {}
    active_focus_slot_ids={str(row.get("role","")).split(":",1)[1] for row in owned
        if str(row.get("role","")).upper().startswith("FOCUS_SLOT:") and not str(row.get("role","")).upper().startswith("FOCUS_SLOT_HEDGE:")}
    raw_focus_slots=raw.get("focusLiveSlots",[]) if isinstance(raw.get("focusLiveSlots"),list) else []
    public_focus_slots=[dict(row) for row in raw_focus_slots if isinstance(row,dict) and str(row.get("slotId","")).strip() in active_focus_slot_ids]
    desired_focus_slots=max(0,int(safe_float(raw.get("focusDesiredSlotCount",settings.get("focusDesiredSlotCount",len(settings.get("focusSlots",[])) if isinstance(settings.get("focusSlots"),list) else 0)))))
    airbag_states=[dict(x.get("airbag")) for x in raw_focus_slots if isinstance(x,dict) and isinstance(x.get("airbag"),dict)]
    airbag_active=[x for x in airbag_states if safe_float(x.get("hedgeRatio"))>0.002]
    airbag_summary={"enabled":bool(settings.get("focusAirbagEnabled",False)),"activeCount":len(airbag_active),
        "maxHedgeRatio":max([safe_float(x.get("hedgeRatio")) for x in airbag_states] or [0.0]),"hedgePnl":sum(safe_float(x.get("hedgePnl")) for x in airbag_states)}
    return {"strategy2": {"settings": settings,"universe":universe,"phase": str(raw.get("phase", "DRAFT")),
        "displayPhase":"UIT" if not enabled else str(raw.get("phase","DRAFT")),
        "liveReady": bool(raw.get("liveReady", False)), "enabled": enabled,
        "monitor":monitor,"canaryValidated":bool(raw.get("canaryValidated",False)),
        "runtimeEnabled":runtime_enabled,"operation":operation,"positionCounts":counts,
        "configVersion": int(safe_float(raw.get("configVersion", settings.get("version", 1)))),
        "lastReason":str(raw.get("lastReason","Nog niet gestart")),"lastTickAt":raw.get("lastTickAt"),
        "scheduler":strategy2_scheduler_status(raw),"candidateScan":raw.get("candidateScan",{}),
        "accountPositionCount":int(safe_float(account_snapshot.get("accountPositionCount"))),
        "provenStrategy2LegCount":counts["positionLegCount"],
        "activePairs":counts["uniqueMarketCount"],"activeLegs":counts["positionLegCount"],
        "longLegs":counts["longLegs"],"shortLegs":counts["shortLegs"],
        "moneyGrabber":{"enabled":bool(settings.get("moneyGrabberEnabled",False)),
            "activated":bool(raw.get("moneyGrabberActivated",False)),"round":mg_round,"pairs":mg_pairs,
            "freeSymbols":max(0,counts["uniqueMarketCount"]-len(mg_pairs)),
            "partialSymbols":sum(str(x.get("status",""))=="PARTIAL_PROTECTION" for x in mg_pairs if isinstance(x,dict)),
            "lockedSymbols":sum(str(x.get("status",""))=="LOCKED" for x in mg_pairs if isinstance(x,dict)),
            "recoverySymbols":sum(str(x.get("status",""))=="RECOVERY" for x in mg_pairs if isinstance(x,dict))},
        "focus":{**focus_state,"state":focus_state,"slots":public_focus_slots if focus_live_mode else [],"desiredSlotCount":desired_focus_slots,"airbagSummary":airbag_summary,"report":focus_report,
            "metrics":raw.get("focusShadowMetrics",{}) if isinstance(raw.get("focusShadowMetrics"),dict) else {},
            "ordersSent":int(safe_float(raw.get("focusLiveOrdersSent"))) if focus_live_mode else 0,
            "live":bool(focus_live_mode and enabled),"shadowEnabled":bool(settings.get("focusShadowEnabled",False)),
            "updatedAt":raw.get("focusLiveAt") if focus_live_mode else raw.get("focusShadowAt")},
        "orderQueue":{"enabled":queue_enabled,"maximumOrdersPerScan":MAX_ORDERS_PER_ACCOUNT_SCAN,
            "scanId":str(queue_state.get("scanId","")),"ordersUsed":int(safe_float(queue_state.get("ordersUsed"))),
            "haltedUncertain":bool(queue_state.get("haltedUncertain",False)),
            "lastScanActions":scan_history[-MAX_ORDERS_PER_ACCOUNT_SCAN:],
            "lastScanCompletedAt":raw.get("lastTickAt") or queue_state.get("completedAt",queue_state.get("updatedAt")),
            "pendingReopenCount":len(queue_state.get("pendingReopens",[])) if isinstance(queue_state.get("pendingReopens"),list) else 0}}}


def _run_focus_shadow_scheduler_step(uid:str,ref:Any,raw:dict[str,Any],settings:Strategy2Config,now:datetime)->dict[str,Any]|None:
    """Advance one persisted hypothetical Focus step; exchange mutation is structurally unavailable."""
    if settings.trading_mode!="focus" or not settings.focus_shadow_enabled:return None
    previous=focus_state_from_mapping(raw.get("focusShadowState"));previous_metrics=raw.get("focusShadowMetrics") if isinstance(raw.get("focusShadowMetrics"),dict) else {}
    try:
        secret=load_aster_secret({"uid":uid})
        shadow_client=AsterV3Client(signer_address=secret.signer_address,sign_message=local_eip712_signer(secret),live_authorized=False)
        report=build_focus_shadow_report(client=shadow_client,raw_state=raw,timestamp_ms=int(now.timestamp()*1000))
        next_state=advance_focus_shadow_state(report,previous,leverage=settings.leverage,timestamp_ms=int(now.timestamp()*1000))
        decision=report.get("decision") if isinstance(report.get("decision"),dict) else {}
        kind=str(decision.get("kind","HOLD")).upper();notional=max(0.0,safe_float(decision.get("notional")))
        action_fee=notional*.0005 if kind in {"OPEN","DCA","PARTIAL_TP","CLOSE"} else 0.0
        if action_fee>0 and next_state.theoretical_portfolio_value>0:
            next_state=replace(next_state,theoretical_portfolio_value=max(0.0,next_state.theoretical_portfolio_value-action_fee))
        ranking=report.get("ranking") if isinstance(report.get("ranking"),list) else []
        active_symbol=next_state.active_pair or previous.active_pair
        market=next((x for x in ranking if isinstance(x,dict) and str(x.get("symbol","")).upper()==active_symbol),None)
        price=safe_float((market or {}).get("price"));unrealized=(price-next_state.weighted_entry)*next_state.total_quantity if price>0 and next_state.weighted_entry>0 else 0.0
        actual=((report.get("currentStrategy2") or {}) if isinstance(report.get("currentStrategy2"),dict) else {})
        actual_equity=safe_float(actual.get("portfolioEquity"));base_value=next_state.theoretical_portfolio_value or actual_equity
        theoretical_equity=base_value+unrealized;previous_high=safe_float(previous_metrics.get("highWaterMark"),theoretical_equity)
        high=max(previous_high,theoretical_equity);drawdown=max(0.0,(high-theoretical_equity)/high) if high>0 else 0.0
        fees=safe_float(previous_metrics.get("fees"))+action_fee;actions=int(safe_float(previous_metrics.get("tradeActions")))+(1 if kind!="HOLD" else 0)
        cycles=int(safe_float(previous_metrics.get("cycles")))+(1 if kind=="CLOSE" else 0)
        duration_sum=safe_float(previous_metrics.get("cycleDurationSecondsSum"))
        if kind=="CLOSE" and previous.opened_at_ms>0:duration_sum+=max(0.0,(int(now.timestamp()*1000)-previous.opened_at_ms)/1000)
        peak_margin=max(safe_float(previous_metrics.get("peakUsedMargin")),next_state.used_margin,previous.used_margin)
        metrics={"portfolioEquity":theoretical_equity,"realizedPnl":next_state.realized_pnl,"unrealizedPnl":unrealized,
            "maxDrawdown":max(safe_float(previous_metrics.get("maxDrawdown")),drawdown),"fees":fees,"tradeActions":actions,
            "dcaCount":next_state.dca_count,"capitalUsedMargin":next_state.used_margin,"peakUsedMargin":peak_margin,
            "returnPerUsedMargin":((next_state.realized_pnl+unrealized-fees)/peak_margin if peak_margin>0 else 0.0),
            "profitPerMarginDollar":((next_state.realized_pnl+unrealized-fees)/peak_margin if peak_margin>0 else 0.0),
            "highWaterMark":high,"cycles":cycles,"cycleDurationSecondsSum":duration_sum,
            "averageCycleDurationSeconds":(duration_sum/cycles if cycles>0 else 0.0)}
        report["state"]=focus_state_to_mapping(next_state);report["performance"]=metrics;report["ordersSent"]=0;report["readOnly"]=True
        stored_state=focus_state_to_mapping(next_state)
        ref.set({"focusShadowState":stored_state,"focusShadowReport":report,"focusShadowMetrics":metrics,"focusShadowAt":now,"focusShadowOrdersSent":0},merge=True)
        ref.collection("focusShadowAudit").add({"timestamp":now,"ordersSent":0,"cycleId":stored_state.get("cycleId",""),
            "selectedPair":stored_state.get("activePair",""),"selectionReason":report.get("selectionReason",""),
            "decision":report.get("decision",{}),"ranking":report.get("ranking",[]),"state":stored_state,"performance":metrics,
            "currentStrategy2":report.get("currentStrategy2",{}),"theoreticalActions":report.get("theoreticalActions",[])})
        return report
    except (AsterApiError,AsterValidationError,KeyError,TypeError,ValueError) as exc:
        failure={"readOnly":True,"ordersSent":0,"wouldSendCount":0,"reason":f"Focus Shadow scheduler fail-closed: {exc}"}
        ref.set({"focusShadowReport":failure,"focusShadowAt":now,"focusShadowOrdersSent":0},merge=True)
        return failure


def _run_aster_strategy2_tick(uid:str,*,dry_run:bool=False,order_budget:int|None=None,
                              before_order:Any=None,management_only:bool=False,event_symbol:str="",
                              event_mark_price:float|None=None)->dict[str,Any]:
    focus_queue_reserver=before_order
    if _aster_close_all_active(uid):
        return {"status":"blocked","reason":"Accountgebonden Alles-sluiten-lock actief","ordersSent":0}
    ref=aster_strategy2_reference(uid);raw=ref.get().to_dict() or {};now=datetime.now(timezone.utc)
    pending_reopens=list(raw.get("pendingReopens",[])) if isinstance(raw.get("pendingReopens"),list) else []
    raw_settings=raw.get("settings") if isinstance(raw.get("settings"),dict) else {}
    if str(raw_settings.get("engine",raw_settings.get("strategyKind","")))!=MULTI_BB_ENGINE:
        if bool(raw.get("enabled")) or bool(raw.get("monitor")):
            ref.set({"enabled":False,"monitor":False,"phase":"CONFIG_REQUIRED","lastReason":"Legacy strategie verwijderd; nieuwe Multi BB-configuratie vereist","updatedAt":now},merge=True)
        return {"status":"stopped","reason":"Legacy strategie is verwijderd; configureer de nieuwe Multi BB-strategie","ordersSent":0}
    try: settings=MultiBbConfig.from_mapping(raw_settings)
    except ValueError as exc:
        ref.set({"enabled":False,"monitor":False,"phase":"CONFIG_ERROR","lastReason":str(exc),"updatedAt":now},merge=True)
        return {"status":"blocked","reason":str(exc),"ordersSent":0}
    enabled=bool(raw.get("enabled",False));monitor=bool(raw.get("monitor",False))
    if not monitor and not dry_run:return {"status":"stopped","reason":"Multi BB monitoring staat uit","ordersSent":0}
    live=settings.mode=="live" and not dry_run
    canary_authorized=bool(raw.get("canaryValidated"))
    central_live_enabled=os.getenv("ASTER_STRATEGY2_LIVE_ENABLED","false").lower()=="true"
    if live and (not canary_authorized or not central_live_enabled):
        reason="Strategy 2 live-uitvoering is niet volledig vrijgegeven: canaryValidated of centrale poort ontbreekt"
        ref.set({"phase":"DATA_HOLD","lastReason":reason,"lastTickAt":now},merge=True)
        return {"status":"blocked","reason":reason}
    # liveReady is durable account authorization, proven by the completed
    # canary. A transient readiness check (for example while an exchange order
    # is open) must never revoke it and deadlock the runtime before it can
    # reconcile that order.
    if live and canary_authorized and not bool(raw.get("liveReady")):
        raw={**raw,"liveReady":True}
        ref.set({"liveReady":True,"liveReadyRecoveredAt":now,
            "liveReadyRecoveryReason":"COMPLETED_CANARY_AUTHORIZATION"},merge=True)
    secret=load_aster_secret({"uid":uid});client=AsterV3Client(signer_address=secret.signer_address,sign_message=local_eip712_signer(secret),live_authorized=live,before_order_submit=_block_order_during_close_all(uid))
    try: hedge=client.position_mode();account=client.account_information();positions=client.position_risk();orders=client.open_orders()
    except (AsterApiError,ValueError) as exc:
        ref.set({"phase":"DATA_HOLD","lastReason":str(exc),"lastTickAt":now},merge=True);return {"status":"data-hold","reason":str(exc)}
    if not hedge:
        reason="Aster Hedge Mode staat uit";ref.set({"phase":"DATA_HOLD","lastReason":reason,"lastTickAt":now},merge=True)
        return {"status":"blocked","reason":reason}
    # The legacy Focus/Strategy-2 planners are retired. The new engine owns all active decisions.
    return run_multi_bb_step(client=client,ref=ref,raw_state=raw,settings=settings,uid=uid,account=account,positions=positions,
        open_orders=orders,timestamp_ms=int(now.timestamp()*1000),dry_run=dry_run,order_budget=order_budget,before_order=before_order)
    # Realtime Simple Mode must make DCA/release decisions from the exact websocket
    # mark event that triggered this evaluation. REST position_risk markPrice may lag
    # the stream enough to leave LIVE below DCA without execution. Preserve all
    # quantities/entries from Aster exchange truth; override only markPrice for the
    # matching event symbol during this single decision tick.
    event_symbol_norm=str(event_symbol).upper().strip()
    event_mark=safe_float(event_mark_price)
    if event_symbol_norm and event_mark>0:
        positions=[({**row,"markPrice":event_mark} if str(row.get("symbol","")).upper()==event_symbol_norm else row)
            for row in positions]
    _run_focus_shadow_scheduler_step(uid,ref,raw,settings,now)
    owned=[]
    for item in raw.get("ownedLegs") if isinstance(raw.get("ownedLegs"),list) else []:
        try:owned.append(owned_from_mapping(item))
        except (TypeError,ValueError):pass
    fills=[];cost_failures={}
    try:
        active_keys=set(active_position_map(positions));known_keys={(x.symbol,x.side) for x in owned}
        missing_symbols={symbol for symbol,side in active_keys if (symbol,side) not in known_keys}
        # The audit collection is recovery evidence, not normal tick input.
        # Healthy accounts already have durable ownedLegs for every active exchange leg,
        # so replaying an ever-growing audit history cannot change the decision. Only
        # enter the historical recovery path when an active exchange leg is actually
        # missing from persisted Strategy-2 ownership. This keeps recovery semantics
        # identical while removing unbounded Firestore I/O from the steady-state tick.
        audit_events=[]
        # Recovery evidence is needed only for exchange legs missing from durable
        # Strategy-2 ownership. Query those symbols directly instead of replaying
        # the complete, ever-growing account audit history. This preserves every
        # open/flat event for the affected symbols while making steady-state ticks
        # independent of total audit size. A known transient Firestore stream
        # transport failure gets one read-only retry; a second failure still
        # propagates and therefore remains fail-closed.
        for recovery_symbol in sorted(missing_symbols):
            query=ref.collection("audit").where("symbol","==",recovery_symbol)
            try:
                rows=list(query.stream())
            except AttributeError as exc:
                if "_UnaryStreamMultiCallable" not in str(exc) or "_retry" not in str(exc):
                    raise
                rows=list(query.stream())
            audit_events.extend(x.to_dict() or {} for x in rows)
        audited_symbols={str(x.get("symbol","")).upper() for x in audit_events
            if str(x.get("event","")).upper() in {"INITIAL_OPEN_LEG","OPEN_LEG","OPEN_PROTECTION"}
            and str(x.get("strategyId",x.get("strategy_id","aster-strategy-2")))=="aster-strategy-2"}
        changed_symbols=changed_owned_symbols(owned,positions)
        refresh_symbols=set(cost_refresh_symbols(owned,positions,maximum_background=4,maximum_total=6))
        # Cost refresh below already reads complete fills and income.  Do not
        # duplicate those fill calls merely for the background rotation.
        recovery_symbols=changed_symbols|(audited_symbols&missing_symbols)
        for symbol in sorted(recovery_symbols):
            starts=[leg.created_at_ms for leg in owned if leg.symbol==symbol and leg.created_at_ms>0]
            fills.extend(paged_user_trades(client,symbol,start_time=min(starts) if starts else None))
        s3_keys:set[tuple[str,str]]=set()
        # Repair a confirmed fill/audit refresh race before exclusive ownership
        # completeness is evaluated.  Both evidence sources must match the
        # active exchange leg; manual or otherwise unproven positions remain
        # unknown and therefore fail closed below.  This path never sends an
        # order and commits the recovered ownership rows with their audit rows.
        owned,recovered_ownership=recover_audited_ownership(persisted=owned,positions=positions,
            audit_events=audit_events,fills=fills,excluded_keys=s3_keys)
        if recovered_ownership:
            recovery_batch=db.batch();recovered_at=datetime.now(timezone.utc)
            recovery_batch.set(ref,{"ownedLegs":[owned_to_mapping(x) for x in owned],"updatedAt":recovered_at},merge=True)
            for item in recovered_ownership:
                recovery_batch.set(ref.collection("audit").document(),
                    {"event":"OWNERSHIP_RECOVERED_FROM_AUDIT",**item,"timestamp":recovered_at})
            recovery_batch.commit()
            refresh_symbols|={str(item.get("symbol","")).upper() for item in recovered_ownership}
        # Strategy 1/3 are retired. Their stored ownership may be read exactly once
        # as migration evidence for an already-open exchange leg, but can never
        # act as an owner, blocker, scheduler input, or trading decision afterward.
        legacy_s3_raw=aster_strategy3_reference(uid).get().to_dict() or {}
        legacy_s1_raw=aster_automation_reference(uid).get().to_dict() or {}
        legacy_s3_legs:list[OwnedLeg]=[];legacy_s1_legs:list[OwnedLeg]=[]
        for item in legacy_s3_raw.get("ownedLegs",[]) if isinstance(legacy_s3_raw.get("ownedLegs"),list) else []:
            try:
                leg=owned_from_mapping(item)
                if leg.strategy_id=="aster-strategy-3" and leg.engine_type=="strategy3":legacy_s3_legs.append(leg)
            except (TypeError,ValueError):pass
        for item in legacy_s1_raw.get("ownedLegs",[]) if isinstance(legacy_s1_raw.get("ownedLegs"),list) else []:
            try:legacy_s1_legs.append(owned_from_mapping(item))
            except (TypeError,ValueError):pass
        normalized,normalization_missing,normalization_errors=transfer_active_ownership_to_strategy2(
            positions=positions,strategy2_legs=owned,strategy3_legs=legacy_s3_legs,strategy1_legs=legacy_s1_legs)
        if not normalization_errors:
            previous_keys={(x.symbol,x.side,x.strategy_id,x.engine_type) for x in owned}
            normalized_keys={(x.symbol,x.side,x.strategy_id,x.engine_type) for x in normalized}
            if normalized_keys!=previous_keys and normalized:
                owned=normalized
                ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"updatedAt":now,
                    "legacyOwnershipNormalizedAt":now,"unassignedPositions":len(normalization_missing)},merge=True)
                ref.collection("audit").add({"event":"LEGACY_OWNERSHIP_NORMALIZED_TO_STRATEGY2",
                    "positionCount":len(owned),"remainingUnassigned":len(normalization_missing),"timestamp":now})
        # After normalization there is exactly one active ownership namespace.
        # Any leg still missing proof is isolated as unknown below, never as an
        # S1/S3 collision and never as an account-wide seat-refill blocker.
        s1_keys:set[tuple[str,str]]=set()
        s2_keys={(leg.symbol,leg.side) for leg in owned}
        unknown=active_keys-(s1_keys|s2_keys|s3_keys)
        proven_owned,_,stored_only_s2=isolate_unproven_ownership(persisted=owned,positions=positions)
        ownership_isolated=bool(unknown or stored_only_s2)
        if ownership_isolated:
            reason="Onbewezen exposure per leg geïsoleerd; alleen bewezen Strategy-2-posities blijven risicoreducerend beheerbaar"
            previous_unassigned=int(safe_float(raw.get("unassignedPositions")))
            previous_stored=int(safe_float(raw.get("storedOnlyStrategy2Legs")))
            ref.set({"phase":"PROTECTIVE_ONLY","lastReason":reason,"lastTickAt":now,
                "unassignedPositions":len(unknown),"storedOnlyStrategy2Legs":len(stored_only_s2)},merge=True)
            if previous_unassigned!=len(unknown) or previous_stored!=len(stored_only_s2):
                ref.collection("audit").add({"event":"OWNERSHIP_MISMATCH_ISOLATED",
                    "exchangeOnlyCount":len(unknown),"storedOnlyCount":len(stored_only_s2),"timestamp":now})
        owned=proven_owned
        s2_keys={(leg.symbol,leg.side) for leg in owned}
        strategy_rows=[row for key,row in active_position_map(positions).items() if key in s2_keys]
        recovery=reconcile_owned_legs(persisted=owned,positions=strategy_rows,open_orders=orders,fills=fills,exchange_reliable=True)
    except (AsterApiError,ValueError) as exc:
        return {"status":"data-hold","reason":f"Fill/funding recovery niet betrouwbaar: {exc}","ordersSent":0}
    if not recovery.allow_risk_increase:
        # Recovery uncertainty is leg-local. Existing uncertain legs are isolated
        # from risk-increasing management, while unrelated empty seats may refill.
        ownership_isolated=True
        reason="; ".join(recovery.reasons)
        ref.set({"phase":"PROTECTIVE_ONLY","lastReason":f"{reason}; vrije stoelen blijven doorstromen","lastTickAt":now},merge=True)
        ref.collection("audit").add({"event":"RECOVERY_ISOLATED_FROM_SEAT_REFILL","reason":reason,"timestamp":now})
    missing_fill_keys={(leg.symbol,leg.side) for leg in recovery.legs if not leg.fill_ids}
    owned,cost_failures=refresh_owned_costs(client,list(recovery.legs),refresh_symbols,
        checked_at_ms=int(now.timestamp()*1000),recover_fill_ids=True)
    recovered_fill_legs=[leg for leg in owned if (leg.symbol,leg.side) in missing_fill_keys and leg.fill_ids]
    for leg in recovered_fill_legs:
        ref.collection("audit").add({"event":"FILL_EVIDENCE_RECOVERED","symbol":leg.symbol,
            "side":leg.side,"cycleId":leg.cycle_id,"fillCount":len(leg.fill_ids),"timestamp":now})
    posmap=active_position_map(positions)
    confirmed_flat=[x for x in owned if (x.symbol,x.side) not in posmap]
    for leg in confirmed_flat:ref.collection("audit").add({"event":"CONFIRMED_FLAT","symbol":leg.symbol,"side":leg.side,"cycleId":leg.cycle_id,"timestamp":now})
    owned=[x for x in owned if (x.symbol,x.side) in posmap];owned_keys={(x.symbol,x.side) for x in owned}
    strategy_positions=[x for x in positions if (str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) in owned_keys]
    initial_build_complete=bool(raw.get("initialBuildComplete",False))
    cycle_hwm=initial_build_high_water_mark(account=account,positions=positions,owned=owned,
        previous_hwm=safe_float(raw.get("adjustedHighWaterMark")),initial_build_complete=initial_build_complete)
    portfolio=strategy2_portfolio_state(settings,account,positions,owned,cycle_hwm)
    snapshot={"equity":portfolio.equity,"highWaterMark":portfolio.adjusted_high_water_mark,"drawdown":portfolio.drawdown,
        "marginRatio":portfolio.margin_ratio,"longExposure":portfolio.long_exposure,"shortExposure":portfolio.short_exposure,
        "strategyExposure":portfolio.strategy_exposure,"strategyMargin":portfolio.strategy_margin,
        "activePairs":len({x.symbol for x in owned}),"accountPositionCount":len(active_position_map(positions)),
        "provenStrategy2LegCount":len(owned),"capturedAt":now}
    ref.set({"accountSnapshot":snapshot,"adjustedHighWaterMark":portfolio.adjusted_high_water_mark,"ownedLegs":[owned_to_mapping(x) for x in owned],"lastTickAt":now},merge=True)
    # Money Grabber scheduler integration starts in mandatory shadow mode. It
    # is account-scoped, only exists after explicit round activation, and can
    # never submit through this path. The separate execution gate remains OFF.
    mg_round_raw=raw.get("moneyGrabberRound")
    if settings.money_grabber_enabled and bool(raw.get("moneyGrabberActivated")) and isinstance(mg_round_raw,dict):
        try:
            mg_round=money_round_from_mapping(mg_round_raw)
            mg_pairs=tuple(money_pair_from_mapping(x) for x in raw.get("moneyGrabberPairs",[]) if isinstance(x,dict))
            mg_positions=[]
            owned_map={(x.symbol,x.side):x for x in owned}
            for row in strategy_positions:
                symbol=str(row.get("symbol","")).upper();side=str(row.get("positionSide","")).upper();leg=owned_map.get((symbol,side))
                mark=safe_float(row.get("markPrice"));qty=abs(safe_float(row.get("positionAmt")));notional=qty*mark
                if not leg or notional<=0:continue
                mg_positions.append(MoneyGrabberPosition(symbol,side,notional,leg.weighted_entry,mark,
                    safe_float(row.get("unRealizedProfit",row.get("unrealizedPnl"))),leg.funding,leg.fees,
                    notional*.0005,notional*.001,leg.costs_updated_at_ms>0))
            mg_gross=sum(x.notional for x in mg_positions)
            mg_open_orders=[x for x in orders if (str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) in owned_keys]
            mg_scan=MoneyGrabberScanSnapshot(uid,f"scheduler-{int(now.timestamp()*1000)}",mg_round,mg_pairs,tuple(mg_positions),
                NetValueEvidence(portfolio.equity,expected_exit_fees=mg_gross*.0005,slippage_buffer=mg_gross*.001,
                    fresh=True,reliable=not cost_failures,captured_at_ms=int(now.timestamp()*1000)),
                hedge,not ownership_isolated,True,not mg_open_orders,True,portfolio.available_balance>0,max(.01,mg_gross*.00025))
            mg_shadow=money_grabber_shadow_report(plan_money_grabber_scan(settings,mg_scan))
            ref.set({"moneyGrabberSchedulerShadow":mg_shadow,"moneyGrabberShadowAt":now,
                "moneyGrabberExecutionEnabled":False},merge=True)
        except (KeyError,TypeError,ValueError) as exc:
            ref.set({"moneyGrabberSchedulerShadow":{"readOnly":True,"ordersSent":0,"wouldSendCount":0,
                "reasons":[f"Money Grabber-state vereist herstel: {exc}"]},"moneyGrabberShadowAt":now,
                "moneyGrabberExecutionEnabled":False},merge=True)
    blocked_dca_raw=raw.get("blockedDcaMinimums") if isinstance(raw.get("blockedDcaMinimums"),dict) else {}
    blocked_dca=(
        {(str(x).split("|",1)[0],str(x).split("|",1)[1]) for x in blocked_dca_raw.get("legs",[]) if "|" in str(x)}
        if int(safe_float(blocked_dca_raw.get("configVersion")))==settings.version else set()
    )
    blocked_management_raw=raw.get("blockedManagementActions") if isinstance(raw.get("blockedManagementActions"),dict) else {}
    blocked_management={key:value for key,value in blocked_management_raw.items() if safe_float(value)>now.timestamp()*1000}
    blocked_actions={(parts[0],parts[1],parts[2]) for key in blocked_management for parts in [str(key).split("|",2)]
        if len(parts)==3}
    # Existing position management precedes new exposure. Within TP candidates,
    # next_management_decision ranks the largest net surplus first.
    now_ms=int(now.timestamp()*1000)
    cost_evidence_limit_ms=cost_evidence_max_age_seconds(owned)*1000
    management_owned=[leg for leg in owned if not str(leg.role).upper().startswith("FOCUS_SLOT_AIRBAG:") and leg.costs_updated_at_ms>0 and now_ms-leg.costs_updated_at_ms<=cost_evidence_limit_ms]
    fresh_cost_keys={(leg.symbol,leg.side) for leg in management_owned}
    open_order_keys={(str(order.get("symbol","")).upper(),str(order.get("positionSide","")).upper())
        for order in orders if str(order.get("symbol","")).strip()}
    # Never stack an automatic action on the same leg while Aster still has an
    # open order for it. Other proven legs remain manageable; open orders only
    # block new exposure account-wide.
    management_owned=[leg for leg in management_owned if (leg.symbol,leg.side) not in open_order_keys]
    event_symbol=str(event_symbol).upper().strip()
    if management_only and event_symbol:
        management_owned=[leg for leg in management_owned if leg.symbol==event_symbol]
    management_keys={(leg.symbol,leg.side) for leg in management_owned}
    management_positions=[row for row in strategy_positions if (str(row.get("symbol","")).upper(),str(row.get("positionSide","")).upper()) in management_keys]
    cost_holds=[f"{leg.symbol} {leg.side}: {cost_failures.get(leg.symbol,'fees/funding ouder dan vijf minuten')}"
        for leg in owned if not str(leg.role).upper().startswith("FOCUS_SLOT_AIRBAG:") and (leg.symbol,leg.side) not in fresh_cost_keys]
    seat_shortage=len(owned)<settings.maximum_pairs
    if settings.trading_mode=="focus":seat_shortage=False
    protection_selected=(None if seat_shortage else portfolio_protection_decision(settings,portfolio,management_owned))
    if protection_selected and (protection_selected[0].symbol,protection_selected[0].side,protection_selected[1].kind) in blocked_actions:
        protection_selected=None
    # A proven take-profit close has absolute Strategy-2 priority. Protection,
    # emergency state, carried reopen work and new exposure may be evaluated
    # afterwards, but none may retain or delay a winning leg.
    management_selected=next_management_decision(settings,portfolio,management_owned,management_positions,blocked_dca,blocked_actions)
    take_profit_selected=(management_selected if management_selected and
        management_selected[1].kind in {"FULL_TP","PARTIAL_TP"} else None)
    # Focus uses the same pure planner as Shadow. Safety/emergency protection may
    # preempt it; otherwise Focus exit/partial/DCA/entry precede legacy management.
    focus_emergency=bool(protection_selected and protection_selected[1].kind in {"EMERGENCY_REDUCE","CLOSE_PROTECTION"})
    if settings.trading_mode=="focus" and enabled and not focus_emergency:
        focus_result=run_focus_live_step(client=client,ref=ref,raw_state={**raw,"ownedLegs":[owned_to_mapping(x) for x in owned]},
            settings=settings,uid=uid,account=account,positions=positions,timestamp_ms=now_ms,dry_run=dry_run,
            order_budget=order_budget,reserve_order=focus_queue_reserver,open_orders=orders)
        if focus_result and str(focus_result.get("action",""))!="FOCUS_HOLD":
            ref.set({"lastTickAt":now},merge=True)
            return focus_result
    pending_reopen_cooldown_until=(int(safe_float(pending_reopens[0].get("cooldownUntilMs")))
        if pending_reopens and isinstance(pending_reopens[0],dict) else 0)
    pending_reopen_attempt_ready=pending_reopen_cooldown_until<=now_ms
    if not ownership_isolated and not protection_selected and not take_profit_selected and pending_reopens and pending_reopen_attempt_ready and enabled and not management_only:
        if order_budget is not None and order_budget<1:
            return {"status":"budget-exhausted","action":"PENDING_REOPEN","ordersSent":0}
        pending=dict(pending_reopens[0]);symbol=str(pending.get("symbol","")).upper();side=str(pending.get("side","")).upper()
        if not symbol or side not in {"LONG","SHORT"}:
            pending_reopens.pop(0);ref.set({"pendingReopens":pending_reopens,"updatedAt":now},merge=True)
            return {"status":"waiting","action":"INVALID_PENDING_REOPEN","ordersSent":0}
        if (symbol,side) in posmap:
            # Exchange truth already contains the replacement. Do not submit a
            # duplicate; leave reconciliation/ownership recovery authoritative.
            pending_reopens.pop(0);ref.set({"pendingReopens":pending_reopens,"updatedAt":now},merge=True)
            return {"status":"reconciling","action":"PENDING_REOPEN_ALREADY_PRESENT","ordersSent":0}
        try:
            info={str(x.get("symbol","")).upper():x for x in client.public_exchange_info().get("symbols",[])}
            prices={str(x.get("symbol","")).upper():safe_float(x.get("price")) for x in client.ticker_prices()}
            reopen=plan_aster_pair(info[symbol],_aster_brackets(client.leverage_brackets(symbol),symbol),prices[symbol],settings.base_notional)
            reopen=replace(reopen,leverage=settings.leverage)
            required=float(reopen.notional_per_leg)/max(1,reopen.leverage)
            if required*1.05>portfolio.available_balance or portfolio.strategy_margin+required>portfolio.equity*settings.strategy_budget:
                pending["attempts"]=int(safe_float(pending.get("attempts")))+1
                pending["reason"]="ACTUAL_MARGIN_OR_STRATEGY_BUDGET"
                pending_reopens[0]=pending
                ref.set({"pendingReopens":pending_reopens,"phase":"WAITING",
                    "lastReason":f"{symbol} {side}: pending heropening wacht op voldoende actuele margin; vrije stoelen blijven doorstromen","updatedAt":now},merge=True)
                # A carried reopen is optional replacement work. It may wait
                # for its own margin/budget without monopolising this scan.
            else:
                if dry_run or not live:
                    return {"status":"simulated","action":"PENDING_REOPEN","symbol":symbol,"side":side,"ordersSent":0}
                package=str(pending.get("packageId",pending.get("package_id","pending")))
                reopened=execute_aster_leg(client,reopen,side=PositionSide(side),action="OPEN",
                    id_prefix=f"s2q-r-{hashlib.sha256((uid+package).encode()).hexdigest()[:12]}",confirm=True,
                    new_position_leverage=settings.leverage,
                    before_submit=(lambda intent:before_order(intent,{"kind":"PENDING_REOPEN","cycleId":str(pending.get("closedCycleId","")),"packageId":package,
                        "leverage":reopen.leverage,"marginUsd":float(reopen.notional_per_leg)/max(1,reopen.leverage),"dcaNumber":None})) if before_order else None)
                rr=reopened.get("result",{});rq=safe_float(rr.get("executedQty"));rp=safe_float(rr.get("avgPrice"))
                if rq<=0 or rp<=0:raise RuntimeError("Bevestigde pending heropening mist werkelijk gevulde hoeveelheid of prijs")
                cycle=f"reopen-{str(pending.get('closedCycleId',pending.get('closed_cycle_id','cycle')))}"
                replacement=OwnedLeg(settings.strategy_id,"strategy2",symbol,side,cycle,settings.version,rq,rp,0,"HARVEST",
                    (str(rr.get("clientOrderId","")),),(),(),int(time.time()*1000),last_order_at_ms=int(time.time()*1000))
                pending_reopens.pop(0);owned.append(replacement)
                batch=db.batch();batch.set(ref,{"ownedLegs":[owned_to_mapping(x) for x in owned],"pendingReopens":pending_reopens,
                    "phase":"RUNNING","lastReason":f"{symbol} {side}: uitgestelde heropening bevestigd","updatedAt":now},merge=True)
                batch.set(ref.collection("audit").document(),{"event":"PENDING_REOPEN_CONFIRMED","symbol":symbol,"side":side,
                    "cycleId":cycle,"packageId":package,"timestamp":now});batch.commit()
                return {"status":"ok","action":"PENDING_REOPEN","symbol":symbol,"side":side,"ordersSent":1}
        except Exception as exc:
            if not isinstance(exc,NewPositionLeverageBlocked) and not is_definite_contract_rejection(exc):raise
            pending["attempts"]=int(safe_float(pending.get("attempts")))+1;pending["reason"]=str(exc)
            pending["cooldownUntilMs"]=int(now.timestamp()*1000)+30*60*1000;pending_reopens[0]=pending
            ref.set({"pendingReopens":pending_reopens,"phase":"WAITING","lastReason":f"{symbol} {side}: heropening definitief afgewezen; cooldown actief","updatedAt":now},merge=True)
            # A symbol-local reopen rejection must not monopolise the complete
            # account tick.  Keep the exact reopen queued with its cooldown,
            # consume no order slot, and continue with other proven management
            # actions or normal new-entry candidates below.
    # Every confirmed Strategy-2 leg is managed from the moment it opens. Empty
    # seats may never suppress a due DCA. TP remains absolute priority; while
    # capacity is still being filled, a proven DCA runs before new exposure.
    # Protection/role bookkeeping keeps the existing full-capacity behavior.
    dca_selected=next_dca_decision(settings,portfolio,management_owned,management_positions,blocked_dca,blocked_actions)
    if seat_shortage:
        selected=take_profit_selected or dca_selected
    else:
        selected=(take_profit_selected or protection_selected or management_selected or
            same_pair_protection_decision(settings,portfolio,management_owned,management_positions,blocked_actions))
    if selected and not management_preempts_initial_build(settings,owned,selected[1]):
        selected=None
    if ownership_isolated and selected and not selected[1].risk_reducing:
        selected=None
    if selected:
        leg,decision=selected
        if decision.kind=="ADD_DCA" and not enabled:decision=Decision("HOLD",leg.side,reason="DCA geblokkeerd omdat Strategy 2 gestopt is",risk_reducing=True)
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
                action_key=f"{leg.symbol}|{leg.side}|OPEN_PROTECTION"
                blocked_management[action_key]=int(now.timestamp()*1000)+5*60*1000
                reason="Strategy Margin Budget blokkeert extra protection; andere posities blijven beheerbaar"
                ref.set({"blockedManagementActions":blocked_management,"phase":"PROTECTION","lastReason":reason,
                         "lastTickAt":now,"updatedAt":now},merge=True)
                ref.collection("audit").add({"event":"PROTECTION_BUDGET_SKIPPED","symbol":leg.symbol,
                    "side":leg.side,"retryAfterSeconds":300,"timestamp":now})
                return {"status":"waiting","action":"PROTECTION_BUDGET_SKIPPED","symbol":leg.symbol,
                    "side":leg.side,"reason":reason,"ordersSent":0}
            if dry_run or not live:return {"status":"simulated","action":decision.kind,"symbol":leg.symbol,"side":decision.side,"ordersSent":0,"reason":decision.reason}
            protection_prefix=(f"s2q-h-{hashlib.sha256((uid+leg.cycle_id+leg.symbol+str(decision.side)).encode()).hexdigest()[:12]}"
                if before_order else f"s2h-{uid[-4:]}-{int(time.time())}")
            opened=execute_aster_leg(client,protection,side=PositionSide(decision.side),action="OPEN",
                id_prefix=protection_prefix,confirm=True,
                before_submit=(lambda intent:before_order(intent,{"kind":"OPEN_PROTECTION","cycleId":leg.cycle_id,
                    "leverage":protection.leverage,"marginUsd":float(protection.notional_per_leg)/max(1,protection.leverage),"dcaNumber":None})) if before_order else None)
            rr=opened.get("result",{});q=safe_float(rr.get("executedQty")) or float(protection.quantity);p=safe_float(rr.get("avgPrice")) or price
            _record_aster_order_attribution(ref,rr,strategy_id=settings.strategy_id,strategy_name="Dual Profit Harvest DCA",
                cycle_id=leg.cycle_id,config_version=settings.version,symbol=leg.symbol,side=str(decision.side),action="OPEN_PROTECTION")
            owned.append(OwnedLeg(settings.strategy_id,"strategy2",leg.symbol,str(decision.side),f"h{int(time.time())}",settings.version,q,p,0,"PROTECTION",(str(rr.get("clientOrderId","")),),(),(),int(time.time()*1000)))
            ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"phase":"PROTECTION","lastReason":decision.reason,"updatedAt":now},merge=True)
            ref.collection("audit").add({"event":"OPEN_PROTECTION","symbol":leg.symbol,"side":decision.side,"timestamp":now})
            return {"status":"ok","action":decision.kind,"symbol":leg.symbol,"side":decision.side,"ordersSent":1}
        if decision.kind!="HOLD":
            if order_budget is not None and order_budget<1:
                return {"status":"budget-exhausted","action":decision.kind,"ordersSent":0}
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
                if decision.kind=="ADD_DCA":
                    required_margin=float(current.notional_per_leg)/max(1,current.leverage)
                    if portfolio.available_balance < required_margin*1.05:
                        reason=f"{leg.symbol} {leg.side}: DCA wacht op voldoende actuele Aster available margin"
                        ref.set({"phase":"WAITING","lastReason":reason,"lastTickAt":now,"updatedAt":now},merge=True)
                        ref.collection("audit").add({"event":"DCA_BLOCKED_AVAILABLE_MARGIN","symbol":leg.symbol,"side":leg.side,
                            "requiredMargin":required_margin,"availableBalance":portfolio.available_balance,"timestamp":now})
                        return {"status":"waiting","action":"DCA_BLOCKED_AVAILABLE_MARGIN","symbol":leg.symbol,"side":leg.side,"ordersSent":0,"reason":reason}
            if dry_run or not live:return {"status":"simulated","action":decision.kind,"symbol":leg.symbol,"side":leg.side,"ordersSent":0,"reason":decision.reason}
            context=ExecutionContext(settings.strategy_id,leg.cycle_id,settings.version,leg,True,True,
                account_uid=uid,cost_evidence_fresh=(leg.symbol,leg.side) in fresh_cost_keys,
                audit=lambda event: ref.collection("audit").add({**event,"timestamp":now}),
                before_submit=(lambda intent:before_order(intent,{"kind":decision.kind,"cycleId":leg.cycle_id,
                    "leverage":current.leverage,"marginUsd":float(current.notional_per_leg)/max(1,current.leverage),
                    "dcaNumber":leg.dca_count+1 if decision.kind=="ADD_DCA" else None})) if before_order else None)
            try:
                result=execute_aster_strategy2_decision(client,decision,current,context,risk_approved=lambda margin:
                    decision.risk_reducing or
                    (decision.kind=="ADD_DCA" and portfolio.available_balance>=margin*1.05) or
                    (decision.kind!="ADD_DCA" and portfolio.margin_ratio<settings.emergency_margin_ratio and
                     portfolio.drawdown<settings.emergency_drawdown and
                     portfolio.strategy_margin+margin<=portfolio.equity*settings.strategy_budget))
            except AsterCloseBlocked:
                action_key=f"{leg.symbol}|{leg.side}|{decision.kind}"
                blocked_management[action_key]=int(now.timestamp()*1000)+5*60*1000
                reason=f"{BLOCK_MESSAGE}; andere posities blijven beheerbaar"
                ref.set({"blockedManagementActions":blocked_management,"phase":"PROTECTION" if portfolio.drawdown>=settings.caution_drawdown or portfolio.margin_ratio>=settings.caution_margin_ratio else "RUNNING",
                         "lastReason":reason,"lastTickAt":now,"updatedAt":now},merge=True)
                return {"status":"waiting","action":"CLOSE_BLOCKED_NET_NON_POSITIVE","symbol":leg.symbol,
                    "side":leg.side,"ordersSent":0,"reason":reason}
            except Strategy2RiskBlocked as exc:
                reason=str(exc)
                action_key=f"{leg.symbol}|{leg.side}|{decision.kind}"
                blocked_management[action_key]=int(now.timestamp()*1000)+5*60*1000
                ref.set({"blockedManagementActions":blocked_management,"phase":"WAITING","lastReason":reason,
                         "lastTickAt":now,"updatedAt":now},merge=True)
                ref.collection("audit").add({"event":"MANAGEMENT_RISK_BLOCKED","symbol":leg.symbol,
                    "side":leg.side,"action":decision.kind,"reason":reason,"retryAfterSeconds":300,"timestamp":now})
                return {"status":"waiting","action":"RISK_BLOCKED","symbol":leg.symbol,
                    "side":leg.side,"ordersSent":0,"reason":reason}
            except Exception as exc:
                if not is_definite_contract_rejection(exc):raise
                action_key=f"{leg.symbol}|{leg.side}|{decision.kind}"
                blocked_management[action_key]=int(now.timestamp()*1000)+(30*60*1000 if decision.kind=="ADD_DCA" else 5*60*1000)
                reason=f"{leg.symbol} {leg.side} {decision.kind} tijdelijk overgeslagen na definitieve afwijzing: {exc}"
                ref.set({"blockedManagementActions":blocked_management,"phase":"RUNNING","lastReason":reason,"lastTickAt":now},merge=True)
                ref.collection("audit").add({"event":"MANAGEMENT_CONTRACT_REJECTION_SKIPPED","symbol":leg.symbol,
                    "side":leg.side,"action":decision.kind,"reason":str(exc),"timestamp":now})
                return {"status":"waiting","action":"MANAGEMENT_SKIPPED","symbol":leg.symbol,"side":leg.side,
                    "ordersSent":0,"reason":reason}
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
                if decision.kind=="FULL_TP" and enabled and settings.auto_restart and (order_budget is None or order_budget>=2):
                    info={str(x.get("symbol","")).upper():x for x in client.public_exchange_info().get("symbols",[])}
                    reopen=plan_aster_pair(info[leg.symbol],_aster_brackets(client.leverage_brackets(leg.symbol),leg.symbol),price,settings.base_notional)
                    reopen=replace(reopen,leverage=settings.leverage)
                    reopen_margin=float(reopen.notional_per_leg)/max(1,reopen.leverage)
                    if portfolio.strategy_margin+reopen_margin>portfolio.equity*settings.strategy_budget:
                        pending_reopens.append({"symbol":leg.symbol,"side":leg.side,"closedCycleId":leg.cycle_id,
                            "packageId":hashlib.sha256(f"{uid}|{leg.cycle_id}|{leg.symbol}|{leg.side}".encode()).hexdigest()[:24],
                            "notional":settings.base_notional,"createdAt":now,"reason":"ACTUAL_MARGIN_OR_STRATEGY_BUDGET",
                            "attempts":0,"cooldownUntilMs":0})
                        ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"pendingReopens":pending_reopens,
                            "phase":"WAITING","lastReason":"TP gesloten; herstart geblokkeerd door actueel Strategy Margin Budget","updatedAt":now},merge=True)
                        return {"status":"waiting","action":"FULL_TP","symbol":leg.symbol,"side":leg.side,"ordersSent":len(result),"reason":"Herstart geblokkeerd door actueel Strategy Margin Budget"}
                    reopen_cycle=f"c{int(time.time())}"
                    package_id=hashlib.sha256(f"{uid}|{leg.cycle_id}|{leg.symbol}|{leg.side}".encode()).hexdigest()[:24]
                    try:
                        reopened=execute_aster_leg(client,reopen,side=PositionSide(leg.side),action="OPEN",
                            id_prefix=f"s2q-r-{package_id[:12]}",confirm=True,
                            new_position_leverage=settings.leverage,
                            before_submit=(lambda intent:before_order(intent,{"kind":"AUTO_RESTART","cycleId":reopen_cycle,"packageId":package_id,
                            "leverage":reopen.leverage,"marginUsd":float(reopen.notional_per_leg)/max(1,reopen.leverage),"dcaNumber":None})) if before_order else None)
                    except Exception as exc:
                        if not isinstance(exc,NewPositionLeverageBlocked) and not is_definite_contract_rejection(exc):raise
                        pending_reopens.append({"symbol":leg.symbol,"side":leg.side,"closedCycleId":leg.cycle_id,
                            "packageId":package_id,"notional":settings.base_notional,"createdAt":now,
                            "reason":str(exc),"attempts":1,"cooldownUntilMs":int(now.timestamp()*1000)+30*60*1000})
                        ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"pendingReopens":pending_reopens,
                            "phase":"WAITING","lastReason":f"{leg.symbol} {leg.side}: sluiting bevestigd; heropening definitief afgewezen","updatedAt":now},merge=True)
                        ref.collection("audit").add({"event":"AUTO_RESTART_REJECTED_AFTER_CONFIRMED_CLOSE","symbol":leg.symbol,
                            "side":leg.side,"cycleId":leg.cycle_id,"packageId":package_id,"reason":str(exc),"timestamp":now})
                        sent_count=len(result) if isinstance(exc,NewPositionLeverageBlocked) else len(result)+1
                        return {"status":"waiting","action":"FULL_TP","symbol":leg.symbol,"side":leg.side,
                            "ordersSent":sent_count,"reason":"Sluiting behouden; heropening staat met cooldown in de wachtrij"}
                    result.append(reopened);rr=reopened.get("result",{});rq=safe_float(rr.get("executedQty")) or float(reopen.quantity);rp=safe_float(rr.get("avgPrice")) or price
                    _record_aster_order_attribution(ref,rr,strategy_id=settings.strategy_id,strategy_name="Dual Profit Harvest DCA",
                        cycle_id=reopen_cycle,config_version=settings.version,symbol=leg.symbol,side=leg.side,action="AUTO_RESTART")
                    owned.append(OwnedLeg(settings.strategy_id,"strategy2",leg.symbol,leg.side,reopen_cycle,settings.version,rq,rp,0,"HARVEST",(str(rr.get("clientOrderId","")),),(),(),int(time.time()*1000)))
                elif decision.kind=="FULL_TP" and enabled and settings.auto_restart:
                    pending_reopens.append({"symbol":leg.symbol,"side":leg.side,"closedCycleId":leg.cycle_id,
                        "packageId":hashlib.sha256(f"{uid}|{leg.cycle_id}|{leg.symbol}|{leg.side}".encode()).hexdigest()[:24],
                        "notional":settings.base_notional,"createdAt":now,"createdScanId":str(raw.get("orderQueueState",{}).get("scanId","")),
                        "reason":"ORDER_BUDGET_EXHAUSTED","attempts":0,"cooldownUntilMs":0})
            ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"pendingReopens":pending_reopens,
                "phase":"RUNNING","lastReason":decision.reason,"updatedAt":now},merge=True)
            ref.collection("audit").add({"event":decision.kind,"symbol":leg.symbol,"side":leg.side,"cycleId":leg.cycle_id,"timestamp":now})
            return {"status":"ok","action":decision.kind,"symbol":leg.symbol,"side":leg.side,"ordersSent":len(result)}
    if management_only:
        return {"status":"waiting","action":"REALTIME_HOLD","symbol":event_symbol,"ordersSent":0,"reason":"Realtime management afgerond; discovery blijft periodiek"}
    if cost_holds:
        reason="; ".join(cost_holds[:3])
        seat_shortage=len(owned)<settings.maximum_pairs
        if not enabled or not seat_shortage:
            ref.set({"phase":"DATA_HOLD","lastReason":reason,"lastTickAt":now},merge=True)
            return {"status":"data-hold","action":"HOLD","reason":reason,"ordersSent":0}
        # Cost/funding evidence is leg-local. Stale managed legs stay blocked,
        # but unrelated free seats may still fill toward the user's target.
        ref.set({"lastReason":f"{reason}; vrije stoelen blijven doorstromen","lastTickAt":now},merge=True)
    # Open orders are symbol-local: unrelated free seats may continue refilling.
    open_order_symbols={str(order.get("symbol","")).upper() for order in orders
        if str(order.get("symbol","")).strip()}
    if ownership_isolated:
        # Unknown/manual exchange legs stay quarantined forever unless explicit
        # ownership evidence appears.  They must not deadlock the whole account:
        # proven S2 risk reduction remains available above and the scanner may
        # continue with unrelated fresh pairs.  DCA/reopen stay fail-closed.
        reason="Onbewezen ownership per leg geïsoleerd; onbekende positie overgeslagen, normale nieuwe instappers mogen door"
        ref.set({"phase":"RUNNING" if enabled else "PROTECTIVE_ONLY","lastReason":reason,"lastTickAt":now},merge=True)
    if not enabled or not scanner_allowed(settings,portfolio,owned):
        reason="Strategy 2 staat veilig gestopt" if not enabled else "Geen beheeractie; pair- of risicolimiet bereikt"
        ref.set({"phase":"PROTECTIVE_ONLY" if not enabled else "WAITING","lastReason":reason},merge=True);return {"status":"waiting","action":"HOLD","reason":reason,"ordersSent":0}
    active_keys={(str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) for x in positions if abs(safe_float(x.get("positionAmt")))>0}
    long_target,short_target=settings.entry_targets
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
        universe=build_aster_universe_snapshot(exchange_info,market24,settings.universe_top_n,
            base_notional=settings.base_notional,minimum_quote_volume_24h_usdt=settings.minimum_quote_volume_24h_usdt)
        all_brackets=client.leverage_brackets()
        bulk_max_leverage={}
        for bracket_row in all_brackets if isinstance(all_brackets,list) else []:
            if not isinstance(bracket_row,dict): continue
            bracket_symbol=str(bracket_row.get("symbol","")).upper()
            bracket_items=(bracket_row.get("brackets") if isinstance(bracket_row.get("brackets"),list)
                else ([bracket_row] if bracket_row.get("initialLeverage") is not None else []))
            if bracket_symbol:
                bulk_max_leverage[bracket_symbol]=max(
                    [int(safe_float(item.get("initialLeverage"))) for item in bracket_items if isinstance(item,dict)] or [0])
    except (AsterApiError,ValueError) as exc:
        blocked=aster_usdt_universe_snapshot(settings.universe_top_n,client=client).public_dict()
        ref.set({"phase":"DATA_HOLD","lastReason":str(exc),"lastTickAt":now,"universe":blocked},merge=True)
        return {"status":"data-hold","reason":str(exc),"ordersSent":0,"universe":blocked}
    universe_contract=universe.public_dict();ref.set({"universe":universe_contract},merge=True)
    codes=entry_fill_symbols(universe_contract["selectedSymbols"],rows,prices)
    preferred_codes=set(universe_contract["selectedSymbols"])
    if not codes:
        reason=universe_contract["entryBlockReason"] or "Geen technisch uitvoerbare actuele Aster USDT-perpetuals"
        ref.set({"phase":"DATA_HOLD","lastReason":reason,"lastTickAt":now},merge=True)
        return {"status":"data-hold","reason":reason,"ordersSent":0,"universe":universe_contract}
    orders_used=(MAX_ORDERS_PER_ACCOUNT_SCAN-max(0,int(order_budget))) if order_budget is not None else 0
    order_limit=queued_entry_order_limit(initial_build_complete,owned,settings.maximum_pairs,
        orders_used=orders_used,maximum_orders=MAX_ORDERS_PER_ACCOUNT_SCAN,long_target=long_target,short_target=short_target)
    if dry_run or not live:
        return {"status":"simulated","action":"INITIAL_BUILD" if not initial_build_complete else "OPEN_LEG","plannedOrders":order_limit,
            "targetLong":long_target,"targetShort":short_target,"ordersSent":0}
    opened_legs=[];remaining_available=portfolio.available_balance;candidate_failures=[];budget_blocked=False
    scan_checked=0;scan_skipped=0;advanced_after_rejection=False
    openable_zero_symbols:set[str]=set();capacity_check_failures=0
    capacity_cache:dict[str,float]={}
    compatible_codes=[symbol for symbol in codes
        if symbol not in bulk_max_leverage or bulk_max_leverage.get(symbol,0)>=settings.leverage]
    cooldown_version=3
    cooldowns=(raw.get("entryCandidateCooldowns") if
        int(safe_float(raw.get("entryCandidateCooldownVersion")))==cooldown_version and
        isinstance(raw.get("entryCandidateCooldowns"),dict) else {})
    cooldowns={str(key):value for key,value in cooldowns.items() if isinstance(value,dict)}
    contract_exposure={}
    for position in positions:
        position_symbol=str(position.get("symbol","")).upper()
        contract_exposure[position_symbol]=contract_exposure.get(position_symbol,Decimal("0"))+abs(
            Decimal(str(position.get("positionAmt",0)))*Decimal(str(position.get("markPrice",0))))
    for index in range(order_limit):
        preferred_side=next_balanced_entry_side(owned,settings.maximum_pairs,long_target,short_target)
        if not preferred_side:break
        long_target_now,short_target_now=settings.entry_targets
        long_count_now,short_count_now=harvest_counts(owned)
        alternate_side="SHORT" if preferred_side=="LONG" else "LONG"
        entry_sides=[preferred_side]
        if ((alternate_side=="LONG" and long_count_now<long_target_now) or
            (alternate_side=="SHORT" and short_count_now<short_target_now)):
            entry_sides.append(alternate_side)
        plan=None;symbol="";opened=None;entry_side=preferred_side
        for entry_side in entry_sides:
            candidates=[candidate for candidate in side_entry_candidates(compatible_codes,active_keys,entry_side)
                if candidate not in open_order_symbols]
            candidates.sort(key=lambda symbol:(
                0 if bulk_max_leverage.get(symbol,0)>=settings.leverage else (1 if symbol not in bulk_max_leverage else 2),
                symbol not in preferred_codes,
                -changes.get(symbol,0) if entry_side=="LONG" else changes.get(symbol,0),symbol))
            for candidate in candidates:
                scan_checked+=1
                try:
                    cooldown_key=f"{candidate}|{entry_side}|OPEN"
                    prior=cooldowns.get(cooldown_key,{})
                    if (safe_float(prior.get("until"))>now_ms and
                        int(safe_float(prior.get("requestedLeverage")))==int(settings.leverage)):
                        scan_skipped+=1
                        if str(prior.get("code",""))=="ASTER_OPENABLE_NOTIONAL_ZERO":
                            openable_zero_symbols.add(candidate)
                            candidate_failures.append(f"{candidate}: Aster heeft bij {settings.leverage}x tijdelijk 0 USDT nieuwe capaciteit")
                        else:
                            candidate_failures.append(f"{candidate}: tijdelijke contractcooldown")
                        continue
                    candidate_brackets=planning_brackets(client,all_brackets,candidate,settings.leverage)
                    rules=ContractRules.from_exchange_info(rows[candidate])
                    fingerprint=hashlib.sha256(json.dumps({"price":prices[candidate],"tick":str(rules.tick_size),
                        "step":str(rules.market_quantity_step),"minQty":str(rules.market_min_quantity),
                        "minNotional":str(rules.min_notional),"requestedLeverage":settings.leverage,
                        "brackets":candidate_brackets},sort_keys=True,separators=(",",":" )).encode()).hexdigest()[:20]
                    if safe_float(prior.get("until"))>now_ms and prior.get("fingerprint")==fingerprint:
                        scan_skipped+=1
                        candidate_failures.append(f"{candidate}: tijdelijke contractcooldown")
                        continue
                    cooldowns.pop(cooldown_key,None)
                    if settings.trend_bollinger_entry_enabled:
                        try:
                            candle_rows=client.klines(candidate,"15m",61)
                            closes=[safe_float(row[4]) for row in candle_rows[:-1] if isinstance(row,list) and len(row)>=5 and safe_float(row[4])>0]
                            entry_check=trend_bollinger_entry_check(closes,prices[candidate],entry_side)
                        except (AsterApiError,ValueError) as exc:
                            scan_skipped+=1;advanced_after_rejection=True
                            candidate_failures.append(f"{candidate}: Trend + Bollinger 15m-data niet betrouwbaar ({exc})")
                            continue
                        if entry_check is None:
                            scan_skipped+=1;advanced_after_rejection=True
                            candidate_failures.append(f"{candidate}: onvoldoende 15m-data voor Trend + Bollinger")
                            continue
                        if not bool(entry_check["eligible"]):
                            scan_skipped+=1;advanced_after_rejection=True
                            relevant=(entry_check["middle"] if entry_check["trend"] in {"UP","DOWN"} and
                                ((entry_check["trend"]=="UP" and entry_side=="LONG") or (entry_check["trend"]=="DOWN" and entry_side=="SHORT"))
                                else entry_check["lower"] if entry_side=="LONG" else entry_check["upper"])
                            candidate_failures.append(
                                f"{candidate}: Trend + Bollinger skip {entry_side} · trend {entry_check['trend']} · "
                                f"prijs {entry_check['price']:.8g} · band {relevant:.8g}")
                            continue
                    value=plan_aster_pair(rows[candidate],candidate_brackets,prices[candidate],settings.base_notional,
                        accepted_leverage=settings.leverage,
                        existing_contract_notional=contract_exposure.get(candidate,0))
                    try:
                        if candidate not in capacity_cache:
                            capacity_cache[candidate]=client.remaining_openable_notional_value(candidate,settings.leverage)
                        remaining_openable=capacity_cache[candidate]
                    except (AsterApiError,AsterValidationError,ValueError) as exc:
                        capacity_check_failures+=1;scan_skipped+=1;advanced_after_rejection=True
                        candidate_failures.append(f"{candidate}: Aster-capaciteit tijdelijk niet betrouwbaar leesbaar")
                        cooldowns[cooldown_key]={"until":now_ms+60*1000,"fingerprint":fingerprint,
                            "attempts":int(safe_float(prior.get("attempts")))+1,"code":"ASTER_OPENABLE_CAPACITY_UNAVAILABLE",
                            "reason":str(exc),"side":entry_side,"action":"OPEN","requestedLeverage":settings.leverage}
                        continue
                    if remaining_openable+1e-9<float(value.notional_per_leg):
                        openable_zero_symbols.add(candidate);scan_skipped+=1;advanced_after_rejection=True
                        capacity_reason=(f"Aster meldt bij {settings.leverage}x slechts {remaining_openable:.8g} USDT "
                            f"resterende openbare notional; {float(value.notional_per_leg):.8g} USDT nodig")
                        candidate_failures.append(f"{candidate}: {capacity_reason}")
                        cooldowns[cooldown_key]={"until":now_ms+5*60*1000,"fingerprint":fingerprint,
                            "attempts":int(safe_float(prior.get("attempts")))+1,"code":"ASTER_OPENABLE_NOTIONAL_ZERO",
                            "reason":capacity_reason,"side":entry_side,"action":"OPEN","requestedLeverage":settings.leverage}
                        ref.collection("audit").add({"event":"ENTRY_CANDIDATE_CAPACITY_WAIT","symbol":candidate,
                            "side":entry_side,"action":"OPEN","configuredLeverage":settings.leverage,
                            "remainingOpenableNotional":remaining_openable,"requiredNotional":float(value.notional_per_leg),
                            "timestamp":datetime.now(timezone.utc)})
                        continue
                    required=float(value.notional_per_leg)/max(1,value.leverage)
                    if required*1.05>remaining_available:
                        budget_blocked=True;scan_skipped+=1;advanced_after_rejection=True
                        candidate_failures.append(f"{candidate}: onvoldoende vrije Aster-margin inclusief 5% uitvoeringsbuffer")
                        continue
                    try:
                        scan_key=str(raw.get("orderQueueState",{}).get("scanId",""))
                        entry_prefix=(f"s2q-i-{hashlib.sha256((uid+scan_key+candidate+entry_side+str(index)).encode()).hexdigest()[:12]}"
                            if before_order else f"s2i-{uid[-4:]}-{int(time.time()*1000)}-{index}-{candidate[:5].lower()}")
                        opened=execute_aster_leg(client,value,side=PositionSide(entry_side),action="OPEN",
                            id_prefix=entry_prefix,confirm=True,
                            new_position_leverage=settings.leverage,
                            before_submit=(lambda intent:before_order(intent,{"kind":"INITIAL_OPEN_LEG" if not initial_build_complete else "OPEN_LEG",
                            "leverage":value.leverage,"marginUsd":float(value.notional_per_leg)/max(1,value.leverage),"dcaNumber":None})) if before_order else None)
                    except Exception as exc:
                        if not isinstance(exc,NewPositionLeverageBlocked) and not is_definite_contract_rejection(exc):
                            raise
                        candidate_failures.append(f"{candidate}: {exc}")
                        scan_skipped+=1;advanced_after_rejection=True
                        attempts=int(safe_float(prior.get("attempts")))+1
                        cooldown_seconds=min(30*60,60*(2**min(attempts,5)))
                        code=(exc.reason_code if isinstance(exc,NewPositionLeverageBlocked)
                            else (re.search(r"-\d{4}",str(exc)) or [""])[0])
                        cooldowns[cooldown_key]={"until":now_ms+cooldown_seconds*1000,"fingerprint":fingerprint,
                            "attempts":attempts,"code":code,"reason":str(exc),"side":entry_side,"action":"OPEN","requestedLeverage":settings.leverage}
                        ref.collection("audit").add({"event":"ENTRY_CANDIDATE_REJECTED","symbol":candidate,"side":entry_side,
                            "action":"OPEN","errorCode":code,"reason":str(exc),"cooldownSeconds":cooldown_seconds,
                            "configVersion":settings.version,"timestamp":datetime.now(timezone.utc)})
                        continue
                    plan=value;symbol=candidate;break
                except ValueError as exc:
                    candidate_failures.append(f"{candidate}: {exc}")
                    scan_skipped+=1;advanced_after_rejection=True
                    attempts=int(safe_float(prior.get("attempts")))+1
                    cooldown_seconds=min(30*60,60*(2**min(attempts,5)))
                    cooldowns[cooldown_key]={"until":now_ms+cooldown_seconds*1000,"fingerprint":fingerprint,
                        "attempts":attempts,"code":"VALIDATION","reason":str(exc),"side":entry_side,"action":"OPEN","requestedLeverage":settings.leverage}
                    ref.collection("audit").add({"event":"ENTRY_CANDIDATE_VALIDATION_SKIPPED","symbol":candidate,
                        "side":entry_side,"action":"OPEN","errorCode":"VALIDATION","reason":str(exc),
                        "cooldownSeconds":cooldown_seconds,"configVersion":settings.version,"timestamp":datetime.now(timezone.utc)})
                    continue
                except Exception as exc:
                    if not is_definite_contract_rejection(exc):
                        raise
                    candidate_failures.append(f"{candidate}: {exc}")
                    scan_skipped+=1;advanced_after_rejection=True
                    attempts=int(safe_float(prior.get("attempts")))+1
                    cooldown_seconds=min(30*60,60*(2**min(attempts,5)))
                    code=(re.search(r"-\d{4}",str(exc)) or [""])[0]
                    cooldowns[cooldown_key]={"until":now_ms+cooldown_seconds*1000,"fingerprint":fingerprint,
                        "attempts":attempts,"code":code,"reason":str(exc),"side":entry_side,"action":"OPEN","requestedLeverage":settings.leverage}
                    ref.collection("audit").add({"event":"ENTRY_CANDIDATE_REJECTED","symbol":candidate,"side":entry_side,
                        "action":"OPEN","errorCode":code,"reason":str(exc),"cooldownSeconds":cooldown_seconds,
                        "configVersion":settings.version,"timestamp":datetime.now(timezone.utc)})
                    continue
            if plan is not None and opened is not None:
                break
        if not plan or opened is None:break
        required=float(plan.notional_per_leg)/max(1,plan.leverage)
        cycle=f"c{int(time.time()*1000)}-{index}"
        rr=opened.get("result",{});q=safe_float(rr.get("executedQty")) or float(plan.quantity);p=safe_float(rr.get("avgPrice")) or prices[symbol]
        _record_aster_order_attribution(ref,rr,strategy_id=settings.strategy_id,strategy_name="Dual Profit Harvest DCA",
            cycle_id=cycle,config_version=settings.version,symbol=symbol,side=entry_side,
            action="INITIAL_OPEN_LEG" if not initial_build_complete else "OPEN_LEG")
        owned.append(OwnedLeg(settings.strategy_id,"strategy2",symbol,entry_side,cycle,settings.version,q,p,0,"HARVEST",(str(rr.get("clientOrderId","")),),(),(),int(time.time()*1000)))
        active_keys.add((symbol,entry_side));remaining_available=max(0.0,remaining_available-required)
        if symbol in capacity_cache:
            capacity_cache[symbol]=max(0.0,capacity_cache[symbol]-(q*p))
        opened_legs.append({"symbol":symbol,"side":entry_side})
        # Persist after every confirmed fill: a later timeout must never erase
        # ownership of the positions already opened in this initial batch.
        audit_ref=ref.collection("audit").document();batch=db.batch();confirmed_at=datetime.now(timezone.utc)
        batch.set(ref,{"ownedLegs":[owned_to_mapping(x) for x in owned],"entryCandidateCooldowns":cooldowns,
            "entryCandidateCooldownVersion":cooldown_version,"phase":"INITIAL_BUILD","lastReason":f"Initiële opbouw: {len(opened_legs)} positie(s) bevestigd","updatedAt":confirmed_at},merge=True)
        batch.set(audit_ref,{"event":"INITIAL_OPEN_LEG" if not initial_build_complete else "OPEN_LEG","symbol":symbol,"side":entry_side,"cycleId":cycle,
            "configuredBaseNotional":settings.base_notional,"filledNotional":q*p,"acceptedLeverage":opened.get("leverage",plan.leverage),"configVersion":settings.version,"timestamp":datetime.now(timezone.utc)})
        batch.commit()
    long_count,short_count=harvest_counts(owned);complete=long_count>=long_target and short_count>=short_target
    openable_zero_candidates=len(openable_zero_symbols)
    capacity_waiting=bool(openable_zero_candidates>0 and not opened_legs and len(owned)<settings.maximum_pairs)
    detail=((f"Aster heeft bij {settings.leverage}x momenteel geen voldoende nieuwe notionalcapaciteit "
        f"voor {openable_zero_candidates} technisch geschikte markt(en); automatische hercheck blijft actief")
        if capacity_waiting else ("; ".join(candidate_failures[:3]) if candidate_failures else
        ("Strategy Margin Budget bereikt" if budget_blocked else f"{len(codes)} kandidaten gecontroleerd")))
    reason=(f"Gebalanceerde start compleet: {long_count} LONG / {short_count} SHORT" if complete else
        f"Initiële opbouw gepauzeerd op {long_count} LONG / {short_count} SHORT. {detail}")
    scan_status={"checked":scan_checked,"skipped":scan_skipped,"advancedWithinTick":advanced_after_rejection,
        "reasons":candidate_failures[:5],"accountPositionCount":len(active_keys),"provenStrategy2LegCount":len(owned),
        "openableZeroCandidates":openable_zero_candidates,"capacityCheckFailures":capacity_check_failures,
        "openableCapacityBlocked":capacity_waiting,"configuredLeverage":settings.leverage,"checkedAt":now}
    ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned],"entryCandidateCooldowns":cooldowns,
        "entryCandidateCooldownVersion":cooldown_version,"candidateScan":scan_status,"initialBuildComplete":complete,"phase":"RUNNING" if complete else "INITIAL_BUILD",
        "lastReason":reason,"updatedAt":datetime.now(timezone.utc)},merge=True)
    return {"status":"ok" if opened_legs else "waiting","action":"INITIAL_BUILD" if not initial_build_complete else "OPEN_LEG",
        "opened":opened_legs,"longCount":long_count,"shortCount":short_count,"targetLong":long_target,"targetShort":short_target,
        "candidateScan":scan_status,"ordersSent":len(opened_legs),"reason":reason}


def _aster_brackets(rows: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    for row in rows:
        if str(row.get("symbol", "")).upper() == symbol.upper():
            return list(row.get("brackets") or [])
    return []


def mexc_automation_public(uid: str) -> dict[str, Any]:
    value = mexc_automation_reference(uid).get().to_dict() or {}
    state = value.get("state") if isinstance(value.get("state"), dict) else {}
    v3_state = value.get("v3State") if isinstance(value.get("v3State"), dict) else {}
    settings_value = value.get("settings") if isinstance(value.get("settings"), dict) else {}
    is_v3 = str(settings_value.get("strategy_version", settings_value.get("strategyVersion", ""))) == "hedge_dca_v3"
    signal = value.get("lastSignal") if isinstance(value.get("lastSignal"), dict) else {}
    snapshot = value.get("lastSnapshot") if isinstance(value.get("lastSnapshot"), dict) else {}
    return {
        "automationEnabled": bool(value.get("enabled", False)),
        "automationMonitoring": bool(value.get("monitor", False)),
        "automationProtectiveOnly": bool(value.get("protectiveOnly", False)),
        "automationPhase": str(v3_state.get("state", "NORMAL") if is_v3 else state.get("phase", "WAIT")),
        "automationReason": str(value.get("lastReason", "Niet gestart")),
        "automationLastTickAt": value.get("lastTickAt"),
        "automationLastAction": str(value.get("lastAction", "HOLD")),
        "automationPaused": bool(value.get("paused", False)),
        "automationPauseReason": str(value.get("pauseReason", "")),
        "automationSettings": settings_value or V3Settings().public_dict(),
        "automationSessionStartEquity": safe_float(state.get("sessionStartEquity")),
        "automationDcaCount": int(safe_float(state.get("dcaCount"))),
        "automationRiskScore": int(safe_float(signal.get("riskScore"))),
        "automationRecoveryScore": int(safe_float(signal.get("recoveryScore"))),
        "automationNetSessionPnl": safe_float(snapshot.get("netSessionPnl")),
        "automationMarginRatioPercent": safe_float(snapshot.get("marginRatio")) * 100.0,
        "automationLiquidationDistancePercent": safe_float(snapshot.get("liquidationDistance")) * 100.0,
        "automationFees": safe_float(value.get("sessionFees")),
        "automationRealizedPnl": safe_float(value.get("sessionRealizedPnl")),
        "automationStrategyVersion": "hedge_dca_v3" if is_v3 else "adaptive_v2",
        "automationLongDcaCount": int(safe_float((v3_state.get("long") or {}).get("dca_level"))) if is_v3 else int(safe_float(state.get("dcaCount"))),
        "automationShortDcaCount": int(safe_float((v3_state.get("short") or {}).get("dca_level"))) if is_v3 else 0,
        "automationFrozen": bool(v3_state.get("frozen")) if is_v3 else False,
        "automationRescueState": str(v3_state.get("state", "")) if is_v3 and str(v3_state.get("state", "")).startswith("RESCUE") else "",
    }


def verify_internal_cloud_request(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Cloudtaak mist authenticatie")
    base_url = os.getenv(
        "MEXC_AUTOMATION_BASE_URL",
        os.getenv("MEXC_INTERNAL_AUDIENCE", "https://tradementor-api-604335232956.europe-west4.run.app"),
    )
    try:
        google_id_token.verify_oauth2_token(
            authorization.removeprefix("Bearer ").strip(),
            google_auth_requests.Request(),
            audience=base_url,
        )
    except Exception as exc:
        raise HTTPException(401, "Ongeldige Cloudtaak-authenticatie") from exc


def linked_wallet(user: dict[str, Any]) -> str:
    snapshot = user_reference(user).get()
    address = str((snapshot.to_dict() or {}).get("walletAddress", "")).strip().lower()
    if not (address.startswith("0x") and len(address) == 42):
        raise HTTPException(409, "Cloudaccount is nog niet aan een Hyperliquid-wallet gekoppeld")
    return address


def require_admin(user: dict[str, Any]) -> None:
    expected = os.getenv("TRADEMENTOR_ADMIN_EMAIL", "amar_rakhan@hotmail.com").strip().lower()
    is_admin = str(user.get("email", "")).strip().lower() == expected
    if not is_admin:
        raise HTTPException(403, "Alleen geautoriseerd TradeMentor-beheer heeft toegang")


def _admin_device_reference(user:dict[str,Any]):
    return user_reference(user).collection("security").document("adminDevice")


def _admin_device_hash(value:str)->str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def _admin_mfa_secret_name(user:dict[str,Any])->str:
    project=os.getenv("GOOGLE_CLOUD_PROJECT","tradementor-production")
    return f"projects/{project}/secrets/tradementor-admin-totp-{user['uid']}"


def _load_admin_mfa_secret(user:dict[str,Any])->str|None:
    try:
        response=secrets_client.access_secret_version(request={"name":f"{_admin_mfa_secret_name(user)}/versions/latest"})
        return response.payload.data.decode("utf-8").strip() or None
    except google_exceptions.NotFound:
        return None


def _store_admin_mfa_secret(user:dict[str,Any],secret:str)->None:
    project=os.getenv("GOOGLE_CLOUD_PROJECT","tradementor-production");parent=f"projects/{project}"
    secret_id=f"tradementor-admin-totp-{user['uid']}";name=f"{parent}/secrets/{secret_id}"
    try:
        secrets_client.create_secret(request={"parent":parent,"secret_id":secret_id,"secret":{"replication":{"automatic":{}}}})
    except google_exceptions.AlreadyExists:
        pass
    secrets_client.add_secret_version(request={"parent":name,"payload":{"data":secret.encode("utf-8")}})


def _totp_code(secret:str,counter:int)->str:
    padded=secret.upper()+"="*((8-len(secret)%8)%8)
    key=base64.b32decode(padded);digest=hmac.new(key,struct.pack(">Q",counter),hashlib.sha1).digest()
    offset=digest[-1]&15;number=(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1_000_000
    return f"{number:06d}"


def _verify_totp(secret:str,code:str,now:float|None=None)->bool:
    normalized=re.sub(r"\D","",code);counter=int((now if now is not None else time.time())//30)
    return len(normalized)==6 and any(python_secrets.compare_digest(_totp_code(secret,counter+delta),normalized) for delta in (-1,0,1))


def _admin_security_reference(user:dict[str,Any]):
    return user_reference(user).collection("security").document("adminMfa")


def _admin_device_session_reference(user:dict[str,Any],device_id:str):
    return user_reference(user).collection("adminDevices").document(_admin_device_hash(device_id))


def _split_admin_credential(value:str|None)->tuple[str,str]:
    if not value or "." not in value:return "",""
    return tuple(value.split(".",1))  # type: ignore[return-value]


def require_admin_device(user:dict[str,Any],credential:str|None)->None:
    require_admin(user);device_id,session_token=_split_admin_credential(credential)
    if not device_id or not session_token:raise HTTPException(403,"Bevestig dit toestel eerst met Google Authenticator")
    stored=_admin_device_session_reference(user,device_id).get().to_dict() or {};expires=stored.get("sessionExpiresAt")
    if hasattr(expires,"timestamp"):expires_at=expires.timestamp()
    else:expires_at=0.0
    valid=stored.get("sessionHash") and python_secrets.compare_digest(str(stored["sessionHash"]),_admin_device_hash(session_token))
    if not valid or expires_at<=time.time():raise HTTPException(403,"De beheersessie is verlopen; bevestig opnieuw met Google Authenticator")


def safe_feedback_text(value: str) -> str:
    """Keep secrets out of support reports even when pasted accidentally."""
    import re
    cleaned = value.strip()
    cleaned = re.sub(r"(?i)(secret|private\s*key|password|wachtwoord)\s*[:=]\s*\S+", r"\1: [VERWIJDERD]", cleaned)
    cleaned = re.sub(r"(?<![0-9a-fA-F])(?:0x)?[0-9a-fA-F]{64}(?![0-9a-fA-F])", "[MOGELIJKE SLEUTEL VERWIJDERD]", cleaned)
    return cleaned


def _admin_environment() -> str:
    return os.getenv("TRADEMENTOR_ENVIRONMENT", "production").strip().lower() or "production"


def _admin_user_rows() -> list[dict[str, Any]]:
    rows=[];now=datetime.now(timezone.utc)
    for record in auth.list_users().iterate_all():
        uid=str(record.uid);profile=user_reference({"uid":uid}).get().to_dict() or {}
        strategy=aster_strategy2_reference(uid).get().to_dict() or {}
        health=classify_bot_health(strategy,now=now)
        metadata=record.user_metadata
        last_login=datetime.fromtimestamp(metadata.last_sign_in_timestamp/1000,tz=timezone.utc) if metadata and metadata.last_sign_in_timestamp else None
        rows.append({"uid":uid,"email":record.email or "","accountStatus":"blocked" if record.disabled else "active",
            "emailVerified":bool(record.email_verified),"lastLogin":last_login,"appVersion":str(profile.get("appVersion",profile.get("webVersion","onbekend"))),
            "environment":_admin_environment(),"exchangeConnected":bool(profile.get("asterConnected") or profile.get("walletAddress")),
            "botEnabled":bool(strategy.get("enabled")),"monitorEnabled":bool(strategy.get("monitor")),"strategy":"Aster Strategy 2",
            "phase":str(strategy.get("phase","DRAFT")),"lastTickAt":strategy.get("lastTickAt"),"lastSyncAt":(strategy.get("accountSnapshot") or {}).get("capturedAt"),
            "technicalError":safe_feedback_text(str(strategy.get("lastReason","")))[:500],"health":health.mapping(),
            "lastRecoveryAt":strategy.get("lastRecoveryAt")})
    return rows


def _reliability_ref(uid:str,event_id:str):
    return db.collection("botReliability").document(uid).collection("events").document(event_id)

def _record_reliability(uid:str,*,component:str,error_code:str,category:str,cause:str,original_status:str,recovery_action:str,status:str):
    event_id=reliability_event_key(uid,component,category,error_code); ref=_reliability_ref(uid,event_id); existing=ref.get().to_dict() or {}
    ref.set(reliability_event_payload(uid=uid,component=component,error_code=error_code,category=category,cause=cause,original_status=original_status,recovery_action=recovery_action,status=status,existing=existing,software_version=os.getenv("TRADEMENTOR_SOURCE_COMMIT", "")),merge=True)
    return event_id

def _today_reliability(uid:str):
    start=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0); rows=[]
    for doc in db.collection("botReliability").document(uid).collection("events").stream():
        row=doc.to_dict() or {}; seen=row.get("lastDetectedAt")
        if isinstance(seen,datetime) and seen>=start: rows.append({"eventId":doc.id,**row})
    return rows

def _record_admin_event(*,actor:str,uid:str,action:str,result:str,reason:str="",incident_id:str="") -> None:
    db.collection("adminAudit").add({"timestamp":datetime.now(timezone.utc),"actor":actor,"uid":uid,"environment":_admin_environment(),
        "action":action,"reason":safe_feedback_text(reason)[:1000],"result":result,"incidentId":incident_id,
        "correlationId":python_secrets.token_hex(8)})


def _run_admin_health_monitor(*,actor:str="system") -> dict[str,Any]:
    now=datetime.now(timezone.utc);results=[];healed=0
    for row in _admin_user_rows():
        uid=row["uid"];state=aster_strategy2_reference(uid).get().to_dict() or {};health=classify_bot_health(state,now=now);actions=safe_recovery_plan(state,health,now=now)
        incident_id=""
        if health.status not in {"healthy"}:
            incident_id=incident_key(uid,"aster-strategy2",health.category);ref=db.collection("adminIncidents").document(incident_id);existing=ref.get().to_dict() or {}
            ref.set({"incidentId":incident_id,"uid":uid,"environment":_admin_environment(),"component":"aster-strategy2","strategy":"Strategy 2",
                "firstDetectedAt":existing.get("firstDetectedAt",now),"lastDetectedAt":now,"severity":health.severity,"category":health.category,
                "summary":health.summary,"technicalDetails":safe_feedback_text(str(state.get("lastReason","")))[:1000],"attempts":int(safe_float(existing.get("attempts")))+bool(actions),
                "status":"auto_recovery" if actions else ("safety_blocked" if health.status=="safety_blocked" else "new"),"updatedAt":now},merge=True)
        if actions:
            update={"phase":"RECONCILING","lastReason":"Technische healthcheck vraagt veilige reconciliatie","lastRecoveryAt":now,"updatedAt":now}
            if "release_stale_lease" in actions:update["leaseUntil"]=firestore.DELETE_FIELD
            aster_strategy2_reference(uid).set(update,merge=True);healed+=1
            _record_admin_event(actor=actor,uid=uid,action=";".join(actions),result="requested",reason=health.summary,incident_id=incident_id)
        results.append({"uid":uid,"status":health.status,"category":health.category,"actions":actions,"incidentId":incident_id})
    return {"checked":len(results),"recoveryRequested":healed,"environment":_admin_environment(),"results":results,"checkedAt":now}


def _send_admin_account_email(*,to:str,subject:str,html:str) -> None:
    key=os.getenv("RESEND_API_KEY","").strip();sender=os.getenv("TRADEMENTOR_EMAIL_FROM","").strip()
    if not key or not sender:raise HTTPException(503,"E-maildienst is nog niet volledig geconfigureerd")
    response=httpx.post("https://api.resend.com/emails",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
        json={"from":sender,"to":[to],"subject":subject,"html":html},timeout=20)
    if response.status_code>=300:raise HTTPException(502,"De e-maildienst heeft het bericht niet geaccepteerd")


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
    if normalized == "BTC":
        raise HTTPException(409, "Bitcoin is uitsluitend beschikbaar in Bitcoin Trade Casino")
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
    environment = os.getenv("TRADEMENTOR_ENVIRONMENT", "production")
    try:
        claims = auth.verify_id_token(
            token,
            app=auth_app,
            check_revoked=check_revoked_tokens(environment),
        )
        if environment.strip().lower() == "strategy3-live" and not recent_id_token(
            claims,
            now_epoch_seconds=time.time(),
            maximum_age_seconds=600,
        ):
            raise ValueError("Strategy-3-live vereist een recent Firebase ID-token")
        return claims
    except Exception as exc:
        raise HTTPException(401, "Ongeldige of verlopen gebruikerssessie") from exc


def require_verified_email(user: dict[str, Any]) -> None:
    if user.get("email_verified") is True:
        return
    try:
        record = auth.get_user(str(user["uid"]))
        if record.email_verified:
            return
    except Exception:
        pass
    raise HTTPException(403, "Bevestig eerst je e-mailadres voordat echt-geldhandel kan worden geactiveerd")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ready",
        "environment": os.getenv("TRADEMENTOR_ENV", "development"),
        "dataProject": data_project_id or None,
        "identityProject": auth_project_id or data_project_id or None,
        "sourceCommit": os.getenv("TRADEMENTOR_SOURCE_COMMIT") or None,
        "imageSourceCommit": os.getenv("TRADEMENTOR_IMAGE_SOURCE_COMMIT") or None,
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


@app.get("/v1/me/preferences/interface")
def get_interface_preference(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    value = user_reference(user).collection("preferences").document("interface").get().to_dict() or {}
    mode = str(value.get("mode", "legacy"))
    return {"mode": mode if mode in {"legacy", "premium"} else "legacy"}


@app.put("/v1/me/preferences/interface")
def save_interface_preference(request: InterfacePreferenceRequest,
                              user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    user_reference(user).collection("preferences").document("interface").set({
        "mode": request.mode,
        "updatedAt": now,
    }, merge=True)
    return {"mode": request.mode, "saved": True}


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


def _admin_serialized(snapshot) -> dict[str, Any]:
    value=snapshot.to_dict() or {};value.setdefault("id",snapshot.id)
    for key,item in list(value.items()):
        if hasattr(item,"isoformat"):value[key]=item.isoformat()
    return value



def _bot_health_platform_summary()->dict[str,int]:
    global _bot_health_platform_cache
    now=time.monotonic()
    # Keep this dashboard read cheap: the previous implementation ran one reliability
    # subcollection query per account on every browser poll. That becomes N+1 reads.
    with _cache_lock:
        cached_at,cached=_bot_health_platform_cache
        if cached and now-cached_at<60:return dict(cached)
    active=tracked=platform_auto=platform_open=0
    start=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    for doc in db.collection("asterStrategy2").stream():
        tracked+=1;value=doc.to_dict() or {};active+=int(bool(value.get("enabled") or value.get("monitor")))
    try:
        for doc in db.collection_group("events").where("lastDetectedAt", ">=", start).stream():
            row=doc.to_dict() or {};seen=row.get("lastDetectedAt")
            if not isinstance(seen,datetime):continue
            status=str(row.get("status") or "")
            platform_auto+=int(status=="AUTO_RECOVERED")
            platform_open+=int(status in {"DETECTED","RECOVERING","OPEN","SAFETY_HOLD"})
    except Exception:
        # Platform-wide counters are informative only; never make the user's own
        # health status unavailable because an aggregate read is temporarily blocked.
        pass
    result={"activeBots":active,"trackedBots":tracked,"autoRecovered":platform_auto,"openIncidents":platform_open}
    with _cache_lock:_bot_health_platform_cache=(now,result)
    return dict(result)

@app.get("/v1/me/bot-health")
def bot_health(user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    uid=str(user["uid"]); state=aster_strategy2_reference(uid).get().to_dict() or {}; rows=_today_reliability(uid); mine=reliability_counts(rows)
    ordered=sorted(rows,key=lambda x:x.get("lastDetectedAt") or datetime.min.replace(tzinfo=timezone.utc),reverse=True)
    return {"status":reliability_overall(rows),"lastSuccessfulScan":state.get("lastTickAt"),"yourBot":mine,
        "platform":_bot_health_platform_summary(),"incidents":ordered[:100]}

@app.get("/v1/admin/health/accounts")
def admin_health_accounts(x_admin_device:str|None=Header(default=None,alias="X-TradeMentor-Admin-Device"),user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    require_admin_device(user,x_admin_device);rows=_admin_user_rows();summary={}
    for row in rows:
        status=str((row.get("health") or {}).get("status","insufficient_data"));summary[status]=summary.get(status,0)+1
    return {"accounts":rows,"summary":summary,"environment":_admin_environment(),"generatedAt":datetime.now(timezone.utc)}


@app.post("/v1/admin/health/run")
def admin_run_health(x_admin_device:str|None=Header(default=None,alias="X-TradeMentor-Admin-Device"),user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    require_admin_device(user,x_admin_device);return _run_admin_health_monitor(actor=str(user.get("email") or user["uid"]))


@app.get("/v1/admin/incidents")
def admin_incidents(x_admin_device:str|None=Header(default=None,alias="X-TradeMentor-Admin-Device"),user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    require_admin_device(user,x_admin_device);items=(_admin_serialized(row) for row in db.collection("adminIncidents").limit(500).stream())
    return {"incidents":sorted(items,key=lambda row:str(row.get("lastDetectedAt","")),reverse=True)}


@app.put("/v1/admin/incidents/{incident_id}")
def admin_update_incident(incident_id:str,request:AdminIncidentUpdateRequest,x_admin_device:str|None=Header(default=None,alias="X-TradeMentor-Admin-Device"),user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    require_admin_device(user,x_admin_device)
    if not incident_id or len(incident_id)>240 or "/" in incident_id:raise HTTPException(422,"Ongeldig incidentnummer")
    ref=db.collection("adminIncidents").document(incident_id)
    if not ref.get().exists:raise HTTPException(404,"Incident bestaat niet")
    ref.set({"status":request.status,"adminNote":safe_feedback_text(request.note),"assignedAdmin":str(user.get("email") or user["uid"]),"updatedAt":datetime.now(timezone.utc)},merge=True)
    _record_admin_event(actor=str(user.get("email") or user["uid"]),uid="",action="incident_update",result=request.status,reason=request.note,incident_id=incident_id)
    return {"updated":True,"incidentId":incident_id,"status":request.status}


@app.get("/v1/admin/audit")
def admin_audit(x_admin_device:str|None=Header(default=None,alias="X-TradeMentor-Admin-Device"),user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    require_admin_device(user,x_admin_device);items=(_admin_serialized(row) for row in db.collection("adminAudit").limit(500).stream())
    return {"events":sorted(items,key=lambda row:str(row.get("timestamp","")),reverse=True)}


@app.post("/v1/admin/users/{uid}/actions/{action}")
def admin_user_action(uid:str,action:str,request:AdminUserActionRequest,x_admin_device:str|None=Header(default=None,alias="X-TradeMentor-Admin-Device"),user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    require_admin_device(user,x_admin_device)
    if not uid or len(uid)>180 or "/" in uid:raise HTTPException(422,"Ongeldige gebruiker")
    allowed={"block","unblock","revoke_sessions","restart_monitor","reconcile","check","password_reset","verify_email"}
    if action not in allowed:raise HTTPException(422,"Onbekende beheeractie")
    if action in {"block","unblock","revoke_sessions"} and not request.confirm:raise HTTPException(422,"Bevestiging is verplicht")
    record=auth.get_user(uid);email=str(record.email or "");actor=str(user.get("email") or user["uid"]);result="completed"
    if action=="block":auth.update_user(uid,disabled=True)
    elif action=="unblock":auth.update_user(uid,disabled=False)
    elif action=="revoke_sessions":auth.revoke_refresh_tokens(uid)
    elif action=="restart_monitor":
        aster_strategy2_reference(uid).set({"monitor":True,"phase":"RECONCILING","lastReason":"Beheer heeft veilige monitoring opnieuw gestart","leaseUntil":firestore.DELETE_FIELD,"updatedAt":datetime.now(timezone.utc)},merge=True)
    elif action=="reconcile":
        aster_strategy2_reference(uid).set({"phase":"RECONCILING","lastReason":"Beheer heeft veilige reconciliatie aangevraagd","updatedAt":datetime.now(timezone.utc)},merge=True)
    elif action=="check":result=classify_bot_health(aster_strategy2_reference(uid).get().to_dict() or {}).mapping()
    elif action=="password_reset":
        if not email:raise HTTPException(409,"Dit account heeft geen e-mailadres")
        link=auth.generate_password_reset_link(email);_send_admin_account_email(to=email,subject="TradeMentor wachtwoord opnieuw instellen",html=f'<p>Gebruik deze beveiligde link om je wachtwoord opnieuw in te stellen:</p><p><a href="{link}">Wachtwoord instellen</a></p>')
    elif action=="verify_email":
        if not email:raise HTTPException(409,"Dit account heeft geen e-mailadres")
        link=auth.generate_email_verification_link(email);_send_admin_account_email(to=email,subject="Bevestig je TradeMentor e-mailadres",html=f'<p>Bevestig je e-mailadres via deze beveiligde link:</p><p><a href="{link}">E-mailadres bevestigen</a></p>')
    _record_admin_event(actor=actor,uid=uid,action=action,result=str(result),reason=request.reason)
    return {"completed":True,"action":action,"result":result}


@app.get("/v1/admin/device")
def admin_device_status(x_admin_device:str|None=Header(default=None,alias="X-TradeMentor-Admin-Device"),user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    require_admin(user);configured=bool((_admin_security_reference(user).get().to_dict() or {}).get("configuredAt"));allowed=False;label=""
    device_id,session_token=_split_admin_credential(x_admin_device)
    if device_id and session_token:
        stored=_admin_device_session_reference(user,device_id).get().to_dict() or {};expires=stored.get("sessionExpiresAt")
        expires_at=expires.timestamp() if hasattr(expires,"timestamp") else 0.0
        allowed=bool(stored.get("sessionHash")) and python_secrets.compare_digest(str(stored.get("sessionHash")),_admin_device_hash(session_token)) and expires_at>time.time()
        if allowed:label=str(stored.get("deviceLabel") or "")
    return {"mfaConfigured":configured,"enrolled":configured,"allowed":allowed,"deviceLabel":label}


@app.post("/v1/admin/mfa/setup")
def setup_admin_mfa(user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    require_admin(user);security=_admin_security_reference(user).get().to_dict() or {}
    if security.get("configuredAt"):return {"configured":True,"setupRequired":False}
    secret=_load_admin_mfa_secret(user)
    if not secret:
        secret=base64.b32encode(python_secrets.token_bytes(20)).decode("ascii").rstrip("=");_store_admin_mfa_secret(user,secret)
    email=str(user.get("email") or "admin");issuer="TradeMentor"
    uri=f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    return {"configured":False,"setupRequired":True,"manualKey":secret,"otpauthUri":uri}


@app.post("/v1/admin/device/verify")
def verify_admin_device(request:AdminMfaVerifyRequest,user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    require_admin(user)
    if not request.confirm:raise HTTPException(422,"Bevestiging is verplicht")
    secret=_load_admin_mfa_secret(user)
    if not secret:raise HTTPException(409,"Start eerst de Google Authenticator-koppeling")
    security_ref=_admin_security_reference(user);security=security_ref.get().to_dict() or {};code=request.code.strip().upper()
    recovery_value=re.sub(r"[^A-Z0-9]","",code);recovery_hashes=list(security.get("recoveryCodeHashes") or []);recovery_hash=_admin_device_hash(recovery_value);used_recovery=recovery_hash in recovery_hashes
    if not _verify_totp(secret,code) and not used_recovery:raise HTTPException(403,"De Google Authenticator-code is ongeldig of verlopen")
    if used_recovery:recovery_hashes.remove(recovery_hash)
    now=datetime.now(timezone.utc);recovery_codes:list[str]=[]
    if not security.get("configuredAt"):
        recovery_codes=[f"{python_secrets.token_hex(2).upper()}-{python_secrets.token_hex(2).upper()}-{python_secrets.token_hex(2).upper()}" for _ in range(8)]
        recovery_hashes=[_admin_device_hash(value.replace("-","").upper()) for value in recovery_codes]
    security_ref.set({"configuredAt":security.get("configuredAt",now),"recoveryCodeHashes":recovery_hashes,"lastVerifiedAt":now},merge=True)
    session_token=python_secrets.token_urlsafe(32);expires=now+timedelta(hours=12)
    _admin_device_session_reference(user,request.device_id).set({"deviceHash":_admin_device_hash(request.device_id),"deviceLabel":safe_feedback_text(request.device_label),"sessionHash":_admin_device_hash(session_token),"sessionExpiresAt":expires,"lastVerifiedAt":now,"createdAt":now},merge=True)
    _record_admin_event(actor=str(user.get("email") or user["uid"]),uid=str(user["uid"]),action="admin_mfa_verified",result="completed",reason=request.device_label)
    return {"allowed":True,"credential":f"{request.device_id}.{session_token}","sessionExpiresAt":expires,"recoveryCodes":recovery_codes}


@app.post("/internal/admin-health/tick")
def internal_admin_health_tick(authorization:str|None=Header(default=None))->dict[str,Any]:
    verify_internal_cloud_request(authorization);return _run_admin_health_monitor(actor="system:30-minute-monitor")


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
        "ordersEnabled": bool(live.get("enabled", False)) and os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() == "true",
    }


@app.post("/v1/me/settings")
def cloud_settings(request: CloudSettingsRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    user_reference(user).collection("settings").document("trading").set({
        "maxActivePositions": request.max_active_positions,
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {"maxActivePositions": request.max_active_positions}


def _public_aster_client() -> AsterV3Client:
    """Create a public-data-only client; its signer can never authorize orders."""
    return AsterV3Client(signer_address="", sign_message=lambda _: "", live_authorized=False)


def aster_usdt_universe_snapshot(limit: int, *, client: AsterV3Client | None = None,
                                  force_refresh: bool = False) -> AsterUniverseSnapshot:
    """Return one shared, TTL-bound Aster universe for every strategy."""
    global _aster_universe_cache
    requested = normalize_top_n(limit)
    now = datetime.now(timezone.utc)
    with _cache_lock:
        cached = _aster_universe_cache
        if cached and not force_refresh and now < cached.expires_at:
            return replace(cached, requested_top_n=requested)
    try:
        source = client or _public_aster_client()
        snapshot = build_aster_universe_snapshot(
            source.public_exchange_info(), source.ticker_24h(), requested, fetched_at=now,
        )
    except (AsterApiError, ValueError) as exc:
        reason = f"Actuele Aster USDT-marktdata ontbreekt: {exc}; nieuwe instappen zijn geblokkeerd"
        if cached:
            return stale_aster_universe_snapshot(replace(cached,requested_top_n=requested), now=now, reason=reason)
        empty = build_aster_universe_snapshot({"symbols": []}, [], requested, fetched_at=now)
        return replace(empty, stale=True, entry_block_reason=reason)
    with _cache_lock:
        _aster_universe_cache = snapshot
    return snapshot


@app.get("/v1/me/market/aster-usdt")
def aster_usdt_universe(
    limit: int = Query(default=50, ge=1),
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    del user
    return aster_usdt_universe_snapshot(limit).public_dict()


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
    ttl = 900.0 if request.type in {"perpDexs", "spotMetaAndAssetCtxs"} else (5.0 if request.type == "userFills" else 2.0)
    return _hyperliquid_info_value(payload, ttl=ttl)


@app.get("/v1/me/hyperliquid/account-state")
def hyperliquid_account_state(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Exchange-truth snapshot shared by the website and all strategy risk gates."""
    return _hyperliquid_account_truth(linked_wallet(user), asset="BTC")


@app.get("/v1/me/hyperliquid/closed-trades")
def hyperliquid_closed_trades(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    address = linked_wallet(user)
    fills = _hyperliquid_info_value({"type": "userFills", "user": address}, ttl=15.0)
    trades = []
    for fill in fills if isinstance(fills, list) else []:
        direction = str(fill.get("dir", ""))
        if "close" not in direction.lower(): continue
        size, price = safe_float(fill.get("sz")), safe_float(fill.get("px"))
        trades.append({
            "symbol": str(fill.get("coin", "")),
            "side": "SHORT" if "short" in direction.lower() else "LONG",
            "notionalUsd": abs(size * price), "exitPrice": price,
            "realizedPnlUsd": safe_float(fill.get("closedPnl")),
            "closedAt": datetime.fromtimestamp(safe_float(fill.get("time")) / 1000, tz=timezone.utc).isoformat(),
            "source": "hyperliquid-fill",
        })
    trades.sort(key=lambda row: row["closedAt"], reverse=True)
    return {"closedTrades": trades[:100]}


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


@app.put("/v1/me/mexc/credentials")
def provision_mexc_credentials(
    request: MexcCredentialRequest,
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Verify MEXC read access before moving credentials into Secret Manager."""
    credentials = MexcCredentials(request.api_key.strip(), request.secret_key.strip())
    status = inspect_mexc(credentials)
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "tradementor-production")
    parent = f"projects/{project}"
    secret_id = f"tradementor-mexc-{user['uid']}"
    secret_name = f"{parent}/secrets/{secret_id}"
    try:
        secrets_client.create_secret(
            request={"parent": parent, "secret_id": secret_id, "secret": {"replication": {"automatic": {}}}}
        )
    except google_exceptions.AlreadyExists:
        pass
    payload = json.dumps({"apiKey": credentials.api_key, "secretKey": credentials.secret_key}).encode("utf-8")
    secrets_client.add_secret_version(request={"parent": secret_name, "payload": {"data": payload}})
    user_reference(user).collection("executionControls").document("mexc").set({
        "configured": True,
        "liveEnabled": False,
        "keySuffix": credentials.api_key[-6:],
        "lastVerifiedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {**status, "keySuffix": credentials.api_key[-6:], "liveEnabled": False, "ordersEnabled": False}


@app.get("/v1/me/mexc/status")
def mexc_status(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    control = user_reference(user).collection("executionControls").document("mexc").get().to_dict() or {}
    try:
        credentials = load_mexc_credentials(user)
    except HTTPException:
        return {"configured": False, "liveReady": False, "liveEnabled": False, "ordersEnabled": False}
    status = inspect_mexc(credentials)
    return {
        **status,
        **mexc_automation_public(str(user["uid"])),
        "keySuffix": str(control.get("keySuffix", "")),
        "liveEnabled": bool(control.get("liveEnabled", False)),
        # Live order execution stays server-gated until an explicit canary is approved.
        "ordersEnabled": os.getenv("MEXC_LIVE_EXECUTION_ENABLED", "false").lower() == "true",
    }


@app.put("/v1/me/aster/credentials")
def provision_aster_credentials(
    request: AsterCredentialRequest,
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Verify read-only Aster V3 access before storing the API wallet secret."""
    try:
        secret = AsterSecret.create(request.signer_address, request.private_key)
        derived_signer = Account.from_key(secret.private_key).address.lower()
    except Exception as exc:
        raise HTTPException(422, "Ongeldige Aster API-walletgegevens") from exc
    if derived_signer != secret.signer_address:
        raise HTTPException(409, "Aster signer-adres en sleutel horen niet bij elkaar")

    # All calls in this inspection are read-only. The client has no live
    # authorization and no Aster order endpoint is exposed by this API.
    status = inspect_aster(secret)
    store_aster_secret(user, secret)
    user_reference(user).collection("executionControls").document("aster").set({
        "configured": True,
        "liveEnabled": False,
        "signerAddressSuffix": secret.signer_address[-6:],
        "lastVerifiedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {
        **status,
        **secret.public_metadata(),
        "liveEnabled": False,
        "ordersEnabled": False,
    }


@app.get("/v1/me/aster/wallet-challenge")
def aster_wallet_challenge(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, str]:
    nonce = python_secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    message = (
        "TradeMentor Aster-koppeling\n"
        f"Account: {user['uid']}\n"
        f"Nonce: {nonce}\n"
        "Deze handtekening plaatst geen order en verplaatst geen geld."
    )
    user_reference(user).collection("executionControls").document("asterChallenge").set({
        "messageHash": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "expiresAt": expires,
        "used": False,
    })
    return {"message": message}


@app.post("/v1/me/aster/wallet-connect")
def aster_wallet_connect(
    request: AsterWalletConnectRequest,
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    challenge_ref = user_reference(user).collection("executionControls").document("asterChallenge")
    challenge = challenge_ref.get().to_dict() or {}
    expected_hash = hashlib.sha256(request.message.encode("utf-8")).hexdigest()
    expires = challenge.get("expiresAt")
    if challenge.get("used") or expected_hash != challenge.get("messageHash") or not isinstance(expires, datetime) or expires <= datetime.now(timezone.utc):
        raise HTTPException(409, "Aster-walletverzoek is verlopen; probeer opnieuw")
    try:
        recovered = Account.recover_message(encode_defunct(text=request.message), signature=request.signature).lower()
    except Exception as exc:
        raise HTTPException(422, "MetaMask-handtekening kon niet worden gecontroleerd") from exc
    master = request.address.strip().lower()
    if recovered != master:
        raise HTTPException(409, "De handtekening hoort niet bij de gekozen wallet")

    generated = Account.create()
    secret = AsterSecret.create(generated.address, generated.key.hex())
    store_aster_secret(user, secret)
    now = datetime.now(timezone.utc)
    user_reference(user).collection("executionControls").document("aster").set({
        "configured": False,
        "authorizationPending": True,
        "masterAddress": master,
        "liveEnabled": False,
        "signerAddressSuffix": secret.signer_address[-6:],
        "updatedAt": now,
    }, merge=True)
    challenge_ref.set({"used": True, "usedAt": now}, merge=True)
    return {
        "authorizationPending": True,
        "apiWalletAddress": secret.signer_address,
        "authorizationUrl": "https://www.asterdex.com/en/api-wallet",
        "message": "Keur dit persoonlijke API-walletadres nu eenmalig goed bij Aster.",
    }


@app.post("/v1/me/aster/wallet-verify")
def aster_wallet_verify(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    secret = load_aster_secret(user)
    status = inspect_aster(secret)
    now = datetime.now(timezone.utc)
    user_reference(user).collection("executionControls").document("aster").set({
        "configured": True,
        "authorizationPending": False,
        "liveEnabled": False,
        "signerAddressSuffix": secret.signer_address[-6:],
        "lastVerifiedAt": now,
    }, merge=True)
    return {**status, **secret.public_metadata(), "liveEnabled": False, "ordersEnabled": False}


def _stored_aster_closed_trades(user: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in user_reference(user).collection("asterClosedTrades").order_by(
        "closedAt", direction=firestore.Query.DESCENDING
    ).limit(100).stream():
        row = item.to_dict() or {}
        if isinstance(row.get("closedAt"), datetime):
            row["closedAt"] = row["closedAt"].isoformat()
        rows.append(row)
    return rows


def _persist_confirmed_aster_closed_trades(user: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    """Persist new exchange-confirmed closes once, using the exchange trade id as identity."""
    control_ref = user_reference(user).collection("executionControls").document("aster")
    control = control_ref.get().to_dict() or {}
    synced = control.get("closedTradesSyncedThrough")
    if isinstance(synced, datetime):
        synced_at = synced.astimezone(timezone.utc)
    else:
        synced_at = datetime.fromtimestamp(0, tz=timezone.utc)
    pending: list[tuple[Any, dict[str, Any], datetime]] = []
    for row in rows:
        try:
            closed_at = datetime.fromisoformat(str(row.get("closedAt", "")).replace("Z", "+00:00")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if closed_at <= synced_at:
            continue
        exchange_id = str(row.get("exchangeTradeId", "")).strip()
        identity = exchange_id or "|".join(str(row.get(field, "")) for field in ("symbol", "side", "closedAt", "notionalUsd", "realizedPnlUsd"))
        document_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        payload = {**row, "closedAt": closed_at, "storedAt": datetime.now(timezone.utc), "source": "aster-fill"}
        pending.append((user_reference(user).collection("asterClosedTrades").document(document_id), payload, closed_at))
    for start in range(0, len(pending), 450):
        batch = db.batch()
        for reference, payload, _closed_at in pending[start:start + 450]:
            batch.set(reference, payload, merge=True)
        batch.commit()
    if pending:
        control_ref.set({"closedTradesSyncedThrough": max(item[2] for item in pending)}, merge=True)
    return len(pending)


def _merge_aster_closed_trades(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for rows in groups:
        for row in rows:
            trade_id = str(row.get("exchangeTradeId", ""))
            key = f"trade:{trade_id}" if trade_id else "|".join(str(row.get(field, "")) for field in (
                "symbol", "side", "closedAt", "notionalUsd", "realizedPnlUsd",
            ))
            merged[key] = row
    return sorted(merged.values(), key=lambda row: str(row.get("closedAt", "")), reverse=True)[:100]


def _stored_aster_realized_events(user: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in user_reference(user).collection("asterRealizedEvents").order_by(
        "closedAt", direction=firestore.Query.DESCENDING
    ).limit(5000).stream():
        row = item.to_dict() or {}
        if isinstance(row.get("closedAt"), datetime):
            row["closedAt"] = row["closedAt"].isoformat()
        rows.append(row)
    return rows


def _persist_aster_realized_events(user: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    """Persist Aster's authoritative PnL ledger so a rolling API limit cannot lower a day total."""
    pending = []
    newest: datetime | None = None
    for row in rows:
        try:
            closed_at = datetime.fromisoformat(str(row.get("closedAt", "")).replace("Z", "+00:00")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        identity = str(row.get("exchangeTransactionId", "")).strip() or "|".join(
            str(row.get(field, "")) for field in ("symbol", "closedAt", "realizedPnlUsd")
        )
        document_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        payload = {**row, "closedAt": closed_at, "storedAt": datetime.now(timezone.utc), "source": "aster-realized-ledger"}
        pending.append((user_reference(user).collection("asterRealizedEvents").document(document_id), payload))
        newest = closed_at if newest is None or closed_at > newest else newest
    for start in range(0, len(pending), 450):
        batch = db.batch()
        for reference, payload in pending[start:start + 450]:
            batch.set(reference, payload, merge=True)
        batch.commit()
    if newest:
        user_reference(user).collection("executionControls").document("aster").set(
            {"realizedEventsSyncedThrough": newest}, merge=True
        )
    return len(pending)


@app.get("/v1/me/aster/closed-trades")
def aster_closed_trades(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Return exchange-confirmed closes, including trades closed outside strategy 1."""
    uid = str(user["uid"])
    stored = _stored_aster_closed_trades(user)
    stored_events = _stored_aster_realized_events(user)
    now = time.monotonic()
    with _cache_lock:
        cached = _aster_closed_trades_cache.get(uid)
    # Fill history is expensive (one signed request per symbol) and is not a
    # live-price feed. Keep a short activity cache so page refreshes/PWA tabs do
    # not compete with the trading scheduler for Aster's shared-IP quota.
    if cached and now - cached[0] < 120.0:
        return {"closedTrades": _merge_aster_closed_trades(stored, cached[1]), "realizedEvents": merge_realized_events(stored_events, cached[2]), "recentTradeActivity": cached[3], "historyAvailable": True}
    try:
        secret = load_aster_secret(user)
        client = AsterV3Client(
            signer_address=secret.signer_address,
            sign_message=local_eip712_signer(secret),
            live_authorized=False,
        )
        control = user_reference(user).collection("executionControls").document("aster").get().to_dict() or {}
        synced = control.get("realizedEventsSyncedThrough")
        start_time = int((synced.astimezone(timezone.utc) - timedelta(minutes=5)).timestamp() * 1000) if isinstance(synced, datetime) else None
        income = client.income_history(income_type="REALIZED_PNL", start_time=start_time, limit=1000)
        recent_income = sorted(
            (row for row in income if isinstance(row, dict)),
            key=lambda row: safe_float(row.get("time")), reverse=True,
        )
        realized_events = realized_events_from_income(recent_income)
        _persist_aster_realized_events(user, realized_events)
        stored_events = _stored_aster_realized_events(user)
        automation = aster_automation_reference(uid).get().to_dict() or {}
        # Always use Aster's current position-risk response for symbol discovery.
        # The stored automation snapshot can legitimately lag behind or be empty
        # when another strategy (or a manual Aster order) owns the position.
        active_positions = [
            row for row in client.position_risk()
            if isinstance(row, dict) and abs(safe_float(row.get("positionAmt", row.get("quantity")))) > 0
        ]
        strategy2_state = aster_strategy2_reference(uid).get().to_dict() or {}
        strategy2_legs = strategy2_state.get("ownedLegs") if isinstance(strategy2_state.get("ownedLegs"), list) else []
        strategy_states = [("Strategy 2", strategy2_state)]
        strategy_by_intent = {}
        strategy_by_order_id = {}
        for fallback_name, state in strategy_states:
            settings = state.get("settings") if isinstance(state.get("settings"), dict) else {}
            strategy_name = str(settings.get("name", fallback_name)).strip() or fallback_name
            for attribution in state.get("orderAttributions") if isinstance(state.get("orderAttributions"), list) else []:
                if not isinstance(attribution, dict):
                    continue
                attributed_name = str(attribution.get("strategyName", strategy_name)).strip() or strategy_name
                order_id = str(attribution.get("orderId", "")).strip()
                client_order_id = str(attribution.get("clientOrderId", "")).strip()
                if order_id:
                    strategy_by_order_id[order_id] = attributed_name
                if client_order_id:
                    strategy_by_intent[client_order_id] = attributed_name
            for leg in state.get("ownedLegs") if isinstance(state.get("ownedLegs"), list) else []:
                if not isinstance(leg, dict):
                    continue
                for intent in leg.get("intent_ids") if isinstance(leg.get("intent_ids"), list) else []:
                    if str(intent):
                        strategy_by_intent[str(intent)] = strategy_name
        background_symbols = []
        for row in [*active_positions, *strategy2_legs, *stored]:
            symbol = str(row.get("symbol", "")).upper() if isinstance(row, dict) else ""
            if symbol and symbol not in background_symbols:
                background_symbols.append(symbol)
        priority_symbols=[]
        prioritized_income = [row for row in recent_income if str(row.get("incomeType", "")).upper() == "REALIZED_PNL"]
        prioritized_income.extend(row for row in recent_income if str(row.get("incomeType", "")).upper() != "REALIZED_PNL")
        for row in prioritized_income:
            symbol = str(row.get("symbol", "")).upper()
            if symbol and symbol not in priority_symbols and str(row.get("incomeType", "")).upper() in {"REALIZED_PNL", "COMMISSION"}:
                priority_symbols.append(symbol)
        symbols=bounded_history_symbols(priority_symbols,background_symbols,maximum_symbols=8,
            rotation_slot=int(time.time()//60))
        fills: list[dict[str, Any]] = []
        for symbol in symbols:
            # A single stale/delisted symbol must not erase the complete trade
            # overview. Aster fill history is authoritative per symbol, so skip
            # only the symbol that cannot currently be read.
            try:
                rows = client.user_trades(symbol, limit=500)
            except (AsterApiError, AsterSubmissionUncertain, AsterValidationError, ValueError):
                continue
            fills.extend(row for row in rows if isinstance(row, dict))
        confirmed = closed_trades_from_fills(fills)
        fresh_activity = recent_trade_activity_from_fills(
            fills, active_positions=active_positions, strategy_by_intent=strategy_by_intent,
            strategy_by_order_id=strategy_by_order_id,
        )
        previous_activity = cached[3] if cached else {"entries": [], "exits": []}
        activity = merge_recent_trade_activity(previous_activity, fresh_activity)
        _persist_confirmed_aster_closed_trades(user, confirmed)
        with _cache_lock:
            _aster_closed_trades_cache[uid] = (time.monotonic(), confirmed, realized_events, activity)
        return {"closedTrades": _merge_aster_closed_trades(stored, confirmed), "realizedEvents": merge_realized_events(stored_events, realized_events), "recentTradeActivity": activity, "historyAvailable": True}
    except (AsterApiError, AsterSubmissionUncertain, AsterValidationError, HTTPException, ValueError):
        fallback = cached[1] if cached else []
        events = cached[2] if cached else []
        durable_events = merge_realized_events(stored_events, events)
        activity = cached[3] if cached else {"entries": [], "exits": []}
        return {"closedTrades": _merge_aster_closed_trades(stored, fallback), "realizedEvents": durable_events, "recentTradeActivity": activity, "historyAvailable": bool(durable_events)}


@app.get("/v1/me/aster/status")
def aster_status(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    control = user_reference(user).collection("executionControls").document("aster").get().to_dict() or {}
    if bool(control.get("authorizationPending", False)):
        try:
            pending_secret = load_aster_secret(user)
            pending_address = pending_secret.signer_address
        except HTTPException:
            pending_address = ""
        return {
            "configured": False, "authorizationPending": True,
            "credentialsVerified": False, "hedgeMode": False,
            "liveReady": False, "liveEnabled": False, "ordersEnabled": False,
            "signerAddressSuffix": str(control.get("signerAddressSuffix", "")),
            "apiWalletAddress": pending_address,
            "authorizationUrl": "https://www.asterdex.com/en/api-wallet",
        }
    try:
        secret = load_aster_secret(user)
    except HTTPException:
        return {
            "configured": False,
            "credentialsVerified": False,
            "hedgeMode": False,
            "liveReady": False,
            "liveEnabled": False,
            "ordersEnabled": False,
        }
    # Reuse the central snapshot, but refresh stale account values read-only.
    # This keeps stopped/not-yet-started bots from showing an old balance while
    # avoiding a signed Aster request for every open browser tab.
    uid = str(user["uid"])
    ensure_aster_strategy2_control(uid)
    automation_ref = aster_automation_reference(uid)
    automation = automation_ref.get().to_dict() or {}
    snapshot = automation.get("accountSnapshot") if isinstance(automation.get("accountSnapshot"), dict) else {}
    captured_at = snapshot.get("capturedAt")
    snapshot_stale = not isinstance(captured_at, datetime) or datetime.now(timezone.utc) - captured_at > timedelta(seconds=30)
    if snapshot_stale:
        try:
            read_client = AsterV3Client(
                signer_address=secret.signer_address,
                sign_message=local_eip712_signer(secret),
                live_authorized=False,
            )
            current = aster_dashboard_snapshot(read_client.account_information(), read_client.position_risk())
            # Open-order evidence is part of the same read-only exchange snapshot.
            # A failed order read keeps the previous snapshot, so the dashboard
            # cannot claim that entries are safe from partial Aster evidence.
            current["openOrders"] = len(read_client.open_orders())
            snapshot = {**snapshot, **current, "capturedAt": datetime.now(timezone.utc)}
            automation_ref.set({"accountSnapshot": snapshot}, merge=True)
        except (AsterApiError, AsterSubmissionUncertain, AsterValidationError, ValueError):
            # Preserve the last exchange-confirmed snapshot rather than showing
            # invented zeroes when Aster is temporarily unavailable.
            pass
    hedge_mode = bool(snapshot.get("hedgeMode", True))
    leg_meta: dict[str, Any] = {}
    leg_last_order_at: dict[str, Any] = {}
    strategy_settings = AsterStrategySettings.from_mapping({})
    strategy2_state = aster_strategy2_reference(uid).get().to_dict() or {}
    for state, reference in ((strategy2_state, aster_strategy2_reference(uid)),):
        try:
            latest = next(iter(reference.collection("audit").order_by(
                "timestamp", direction=firestore.Query.DESCENDING).limit(1).stream()), None)
            audit = latest.to_dict() if latest is not None else {}
            if isinstance(audit, dict) and audit:
                state["lastAction"] = str(audit.get("event", state.get("lastAction", "NIET_BEWEZEN")))
                state["lastActionAt"] = audit.get("timestamp")
        except google_exceptions.GoogleAPICallError:
            # Audit lookup is optional evidence: absence remains explicit and
            # can never be upgraded to a positive browser-derived action.
            pass
    owned_legs_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    strategy2_owned_by_key:dict[tuple[str,str],OwnedLeg]={}
    for strategy_state in (strategy2_state,):
        for item in strategy_state.get("ownedLegs", []) if isinstance(strategy_state.get("ownedLegs"), list) else []:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("symbol", "")).upper(), str(item.get("side", "")).upper())
            if not key[0] or key[1] not in {"LONG", "SHORT"}:
                continue
            previous = owned_legs_by_key.get(key) or {}
            item_activity = max(int(safe_float(item.get("last_order_at_ms"))), int(safe_float(item.get("created_at_ms"))))
            previous_activity = max(int(safe_float(previous.get("last_order_at_ms"))), int(safe_float(previous.get("created_at_ms"))))
            if not previous or item_activity >= previous_activity:
                owned_legs_by_key[key] = item
            if strategy_state is strategy2_state:
                try:
                    parsed=owned_from_mapping(item)
                    if parsed.strategy_id=="aster-strategy-2" and parsed.engine_type=="strategy2":strategy2_owned_by_key[key]=parsed
                except (TypeError,ValueError):pass
    evidence_now=datetime.now(timezone.utc)
    def recent_portfolio_snapshot(value:Any)->bool:
        if not isinstance(value,datetime):return False
        stamp=value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        age=evidence_now-stamp
        return timedelta(0)<=age<=timedelta(minutes=5)
    strategy2_settings_raw=strategy2_state.get("settings") if isinstance(strategy2_state.get("settings"),dict) else {}
    if str(strategy2_settings_raw.get("engine",strategy2_settings_raw.get("strategyKind","")))==MULTI_BB_ENGINE:
        multi_status_settings=MultiBbConfig.from_mapping(strategy2_settings_raw)
        # Dashboard compatibility only: Multi BB is the live engine. The old
        # Strategy2Config shape is still consumed by legacy presentation helpers,
        # so project the current settings without re-validating Multi BB TP limits.
        dashboard_max_pairs=min(100,max(1,multi_status_settings.maximum_positions))
        strategy2_settings=Strategy2Config.from_mapping({
            "mode":multi_status_settings.mode,
            "baseNotional":multi_status_settings.entry_notional_usd,
            "takeProfit":min(.20,max(.001,multi_status_settings.take_profit)),
            "autoRestart":True,"dcaEnabled":True,
            "longDcaDistance":multi_status_settings.dca_distance,
            "shortDcaDistance":multi_status_settings.dca_distance,
            "longMaxDca":min(50,max(0,multi_status_settings.max_dca)),
            "shortMaxDca":min(50,max(0,multi_status_settings.max_dca)),
            "maximumPairs":dashboard_max_pairs,
            "universeTopN":max(1,multi_status_settings.universe_top_n),
            "leverage":min(200,max(1,multi_status_settings.minimum_leverage)),
        })
    else:
        strategy2_settings=Strategy2Config.from_mapping(strategy2_settings_raw)
    strategy2_focus_slots=[dict(x) for x in strategy2_state.get("focusLiveSlots",[]) if isinstance(x,dict)] if isinstance(strategy2_state.get("focusLiveSlots"),list) else []
    strategy2_airbag_by_key={(str(x.get("pair","")).upper(),str(x.get("side","")).upper()):dict(x.get("airbag")) for x in strategy2_focus_slots if isinstance(x.get("airbag"),dict)}
    strategy2_focus_slot_by_key={(str(x.get("pair","")).upper(),str(x.get("side","")).upper()):x for x in strategy2_focus_slots if str(x.get("pair","")).strip()}
    strategy2_snapshot=strategy2_state.get("accountSnapshot") if isinstance(strategy2_state.get("accountSnapshot"),dict) else {}
    strategy2_portfolio=None
    strategy2_captured=strategy2_snapshot.get("capturedAt")
    strategy2_snapshot_recent=recent_portfolio_snapshot(strategy2_captured)
    if safe_float(strategy2_snapshot.get("equity"))>0 and strategy2_snapshot_recent:
        strategy2_portfolio=Strategy2PortfolioState(
            safe_float(strategy2_snapshot.get("equity")),safe_float(strategy2_snapshot.get("highWaterMark")),
            safe_float(strategy2_snapshot.get("marginRatio")),safe_float(strategy2_snapshot.get("longExposure")),
            safe_float(strategy2_snapshot.get("shortExposure")),safe_float(strategy2_snapshot.get("strategyExposure")),
            True,True,False,safe_float(strategy2_snapshot.get("strategyMargin")))
    # Dashboard reads never fan out into per-symbol Aster fill/funding calls.
    # The strategy runtimes already persist this evidence under ownedLegs; the
    # browser consumes it fail-closed until a scheduler refreshes it.
    strategy2_costs_by_key=dict(strategy2_owned_by_key);strategy2_cost_failures:dict[str,str]={}
    positions = []
    for raw in snapshot.get("positions") if isinstance(snapshot.get("positions"), list) else []:
        row = dict(raw) if isinstance(raw, dict) else {}
        symbol, side = str(row.get("symbol", "")).upper(), str(row.get("side", "")).upper()
        stored_dca = int(safe_float((leg_meta.get(symbol) or {}).get(side)))
        inferred_dca = infer_aster_dca_level(
            abs(safe_float(row.get("quantity"))) * safe_float(row.get("entryPrice")), strategy_settings.base_notional,
            strategy_settings.dca_multiplier,
            strategy_settings.maximum_long_dca if side == "LONG" else strategy_settings.maximum_short_dca,
        )
        owned_leg = owned_legs_by_key.get((symbol, side)) or {}
        row["dcaCount"] = int(safe_float(owned_leg.get("dca_count"))) if owned_leg else max(stored_dca, inferred_dca or 0)
        row["lastOrderAt"] = max(
            int(safe_float(owned_leg.get("last_order_at_ms"))), int(safe_float(owned_leg.get("created_at_ms"))),
            int(safe_float((leg_last_order_at.get(symbol) or {}).get(side))),
        )
        row["openedAt"] = int(safe_float(owned_leg.get("created_at_ms"))) or row.get("openedAt")
        strategy_id = str(owned_leg.get("strategy_id", owned_leg.get("strategyId", ""))).strip()
        row["strategyId"] = strategy_id
        row["strategyName"] = "Strategy 2 · Dual Profit Harvest DCA" if strategy_id == "aster-strategy-2" else ""
        row["strategy2Role"] = str(owned_leg.get("role", "")) if owned_leg else ""
        if strategy_id=="aster-strategy-2":
            if (symbol,side) in strategy2_airbag_by_key:
                row["focusAirbag"]={**strategy2_airbag_by_key[(symbol,side)],"enabled":bool(strategy2_settings.focus_airbag_enabled)}
            elif str(row.get("strategy2Role","")).upper().startswith("FOCUS_SLOT_AIRBAG:"):
                row["focusAirbagHedge"]=True
            strategy2_owned=strategy2_costs_by_key.get((symbol,side))
            row["strategy2Tp"]=strategy2_position_tp_contract(row=row,
                owned=strategy2_owned,config=strategy2_settings,
                state={**strategy2_state,"runtimeEnabled":os.getenv("ASTER_STRATEGY2_LIVE_ENABLED","false").lower()=="true"},
                portfolio=strategy2_portfolio)
            row["strategy2DcaLadder"]=strategy2_fixed_dca_ladder(row=row,owned=strategy2_owned,config=strategy2_settings)
            focus_slot=strategy2_focus_slot_by_key.get((symbol,side))
            if isinstance(focus_slot,dict) and str(row.get("strategy2Role","")).upper().startswith("FOCUS_SLOT:"):
                next_focus_dca=safe_float(focus_slot.get("nextDcaTrigger"));filled=int(safe_float(focus_slot.get("dcaCount")))
                row["strategy2DcaLadder"]={"available":next_focus_dca>0,"mode":str(focus_slot.get("cycleDcaMode",strategy2_settings.focus_dca_mode)),
                    "filledDcaCount":filled,"maxDca":strategy2_settings.focus_max_dca,
                    "levels":[{"number":filled+1,"price":next_focus_dca}] if next_focus_dca>0 else [],"source":"focus-runtime-state"}
            elif str(row.get("strategy2Role","")).upper()=="FOCUS_V2_LONG":
                v2=strategy2_state.get("focusV2State") if isinstance(strategy2_state.get("focusV2State"),dict) else {}
                filled=max(0,int(safe_float(v2.get("dcaCount"))))
                anchor=safe_float(v2.get("dcaAnchorPrice")) or safe_float(v2.get("weightedEntry")) or safe_float(v2.get("originalEntry")) or safe_float(row.get("entryPrice"))
                fallback_next=(anchor*(1-strategy2_settings.focus_dca_distance) if strategy2_settings.focus_dca_enabled and anchor>0 and (strategy2_settings.focus_dca_unlimited or filled<strategy2_settings.focus_max_dca) else 0.0)
                next_focus_dca=safe_float(v2.get("nextDcaPrice")) or fallback_next
                row["dcaCount"]=filled
                row["strategy2DcaLadder"]={"available":next_focus_dca>0,"mode":strategy2_settings.focus_dca_mode,
                    "filledDcaCount":filled,"maxDca":strategy2_settings.focus_max_dca,
                    "levels":[{"number":filled+1,"price":next_focus_dca}] if next_focus_dca>0 else [],"source":"focus-v2-runtime-state"}
            if symbol in strategy2_cost_failures and row["strategy2Tp"]["status"]=="Niet betrouwbaar te bepalen":
                row["strategy2Tp"]["blockReason"]=f"Fees/funding niet volledig bewezen: {strategy2_cost_failures[symbol]}"
        positions.append(row)
    # Focus 2.0 cockpit is read-only presentation state derived from the same persisted runtime truth.
    focus_v2_cockpit:dict[str,Any]={}
    v2_state=strategy2_state.get("focusV2State") if isinstance(strategy2_state.get("focusV2State"),dict) else {}
    v2_history=strategy2_state.get("focusV2History") if isinstance(strategy2_state.get("focusV2History"),dict) else {}
    v2_symbol=str(v2_state.get("symbol","")).upper()
    if v2_symbol and str(v2_state.get("cycleId", "")):
        v2_long=next((x for x in positions if str(x.get("symbol","")).upper()==v2_symbol and str(x.get("side","")).upper()=="LONG"),{})
        v2_short=next((x for x in positions if str(x.get("symbol","")).upper()==v2_symbol and str(x.get("side","")).upper()=="SHORT"),{})
        current=safe_float(v2_history.get("currentPrice")) or safe_float(v2_long.get("markPrice")) or safe_float(v2_short.get("markPrice"))
        long_qty=abs(safe_float(v2_long.get("quantity",v2_long.get("positionAmt"))))
        short_qty=abs(safe_float(v2_short.get("quantity",v2_short.get("positionAmt"))))
        long_entry=safe_float(v2_long.get("entryPrice",v2_state.get("weightedEntry")))
        short_entry=safe_float(v2_short.get("entryPrice"))
        long_notional=long_qty*current if current>0 else safe_float(v2_history.get("longNotional"))
        short_notional=short_qty*current if current>0 else safe_float(v2_history.get("shortNotional"))
        dca_anchor=safe_float(v2_state.get("dcaAnchorPrice")) or safe_float(v2_history.get("dcaAnchorPrice")) or long_entry
        next_dca=(dca_anchor*(1-strategy2_settings.focus_dca_distance) if strategy2_settings.focus_dca_enabled and dca_anchor>0 and (strategy2_settings.focus_dca_unlimited or int(safe_float(v2_state.get("dcaCount")))<strategy2_settings.focus_max_dca) else 0.0)
        state_machine_version=max(1,int(safe_float(v2_state.get("stateMachineVersion",v2_history.get("stateMachineVersion",1)))))
        recovery_model_version=(5 if state_machine_version>=5 else max(1,int(safe_float(v2_state.get("recoveryModelVersion",1)))))
        last_dca_fill=safe_float(v2_state.get("lastDcaFillPrice",v2_history.get("lastDcaFillPrice")))
        if state_machine_version>=5:
            next_dca=safe_float(v2_state.get("nextDcaPrice",v2_history.get("nextDcaPrice"))) or next_dca
            next_release_price=safe_float(v2_state.get("hedgeReleasePrice",v2_history.get("hedgeReleasePrice")))
            rebound=next_release_price
            primary_side=str(v2_state.get("primarySide","LONG")).upper()
            price_met=bool(next_release_price>0 and ((current>=next_release_price) if primary_side=="LONG" else (current<=next_release_price)))
            middle_met=True
            portfolio_met=True
            release_ready=bool(short_qty>0 and price_met)
        else:
            rebound=safe_float(v2_history.get("recoveryTrigger",v2_history.get("recoveryReboundPrice"))) or ((safe_float(v2_state.get("recentLow"))*(1+strategy2_settings.focus_v2_recovery_rebound_pct)) if safe_float(v2_state.get("recentLow"))>0 else 0.0)
            next_release_price=(safe_float(v2_history.get("nextReleasePrice",v2_state.get("nextReleasePrice"))) if recovery_model_version==2 else (rebound if recovery_model_version>=3 else rebound))
            price_met=bool(v2_history.get("recoveryPriceMet", current>=rebound if rebound>0 else False))
            middle_met=bool(v2_history.get("bollinger5mConfirmed", not strategy2_settings.focus_v2_require_bollinger_middle))
            portfolio_met=bool(v2_history.get("portfolioRecoveryMet", False))
            release_ready=(bool(next_release_price>0 and current>=next_release_price and middle_met) if recovery_model_version==2 else (bool(v2_history.get("shortReleaseReady", price_met and middle_met and int(safe_float(v2_history.get("recoveryStage",v2_state.get("releaseStage"))))==0)) if recovery_model_version>=3 else bool(v2_history.get("shortReleaseReady", price_met and middle_met and portfolio_met))))
        rehedge_price=0.0 if state_machine_version>=5 else safe_float(v2_state.get("rehedgeStopPrice",v2_history.get("rehedgeTrigger")))
        armed_rehedge_qty=0.0 if state_machine_version>=5 else safe_float(v2_history.get("armedRehedgeQty",v2_state.get("armedRehedgeQty")))
        rehedge_armed=False if state_machine_version>=5 else bool((armed_rehedge_qty>0 or v2_state.get("rehedgeClientId")) and rehedge_price>0)
        runtime_phase=str(strategy2_state.get("phase",""))
        runtime_hold_reason=str(strategy2_state.get("lastReason","")) if runtime_phase=="DATA_HOLD" else ""
        harvest_baseline=safe_float(v2_state.get("harvestBaselineEquity")) or safe_float(v2_history.get("harvestBaselineEquity")) or safe_float(v2_state.get("cycleStartEquity"))
        profit_since_harvest=(safe_float(v2_history.get("profitSinceHarvest")) if "profitSinceHarvest" in v2_history else 0.0)
        if not profit_since_harvest and harvest_baseline>0: profit_since_harvest=(safe_float(v2_history.get("equity")) or safe_float(strategy2_snapshot.get("equity")))-harvest_baseline
        if state_machine_version>=6:
            tp_mode=str(getattr(strategy2_settings,"focus_v2_take_profit_mode","usdt"));tp_value=safe_float(getattr(strategy2_settings,"focus_v2_take_profit_value",0))
            long_open_pnl=safe_float(v2_long.get("unrealizedPnl",v2_long.get("unRealizedProfit")))
            profit_trigger=tp_value if tp_mode=="usdt" else 0.0;profit_harvest=0.0
            profit_since_harvest=long_open_pnl
            profit_remaining=(max(0.0,tp_value-long_open_pnl) if tp_mode=="usdt" else max(0.0,tp_value-(long_open_pnl/long_notional if long_notional>0 else 0.0)))
        else:
            tp_mode="usdt";tp_value=0.0
            profit_trigger=strategy2_settings.focus_v2_profit_trigger_usdt;profit_harvest=strategy2_settings.focus_v2_profit_harvest_usdt
            profit_remaining=max(0.0,profit_trigger-profit_since_harvest) if profit_trigger>0 else 0.0
        recovery_stage=int(safe_float(v2_history.get("recoveryStage",v2_state.get("releaseStage"))))
        recovery_progress=safe_float(v2_history.get("recoveryProgressRatio",v2_state.get("recoveryProgressRatio")))
        recovery_low=safe_float(v2_history.get("recoveryLow",v2_state.get("recentLow")))
        recovery_high=safe_float(v2_history.get("recoveryHigh",v2_state.get("recoveryHigh")))
        next_release_qty=safe_float(v2_history.get("nextReleaseQty"))
        released_short_qty=safe_float(v2_history.get("releasedShortQty",v2_state.get("releasedShortQty")))
        target_short_notional=(long_notional*strategy2_settings.focus_v2_hedge_ratio if state_machine_version>=5 else safe_float(v2_history.get("targetShortNotional")))
        realtime_worker_connected=False
        realtime_worker_healthy=False
        try:
            realtime_health=db.collection("systemStatus").document("asterRealtime").get().to_dict() or {}
            realtime_worker_connected=bool(realtime_health.get("connected",False))
            realtime_updated=realtime_health.get("updatedAt")
            realtime_fresh=bool(realtime_updated and (datetime.now(timezone.utc)-realtime_updated).total_seconds()<=30)
            realtime_worker_healthy=bool(realtime_worker_connected and realtime_fresh and not str(realtime_health.get("lastError","")).strip())
        except Exception:
            realtime_worker_connected=False
            realtime_worker_healthy=False
        protection_ui_ready=bool(realtime_worker_healthy and (v2_state.get("releaseRehedgeMarginReady",False) if state_machine_version>=8 else v2_state.get("protectionReserveReady",False)) and str(v2_state.get("cycleStatus",""))!="DCA_HEDGE_SYNC_PENDING")
        protected_extreme=safe_float(v2_state.get("protectedFloorPrice")) if str(v2_state.get("primarySide","LONG")).upper()=="LONG" else safe_float(v2_state.get("protectedCeilingPrice"))
        if runtime_phase=="DATA_HOLD": next_action=f"DATA HOLD · {runtime_hold_reason or 'wacht op betrouwbare serverdata'}"
        elif state_machine_version>=8 and short_qty>0 and bool(v2_state.get("shortReleasePriceReady")) and not bool(v2_state.get("shortReleaseNetGreenReady")): next_action=f"REBOUND BEREIKT · SHORT NOG NIET NETTO GROEN · BODEM {protected_extreme:.8g}"
        elif state_machine_version>=8 and short_qty>0 and bool(v2_state.get("shortReleasePriceReady")) and bool(v2_state.get("shortReleaseNetGreenReady")) and not bool(v2_state.get("releaseRehedgeMarginReady",False)): next_action="RELEASE GEBLOKKEERD · RE-HEDGE MARGIN NIET BEWEZEN"
        elif state_machine_version>=8 and short_qty>0 and bool(v2_state.get("shortReleasePriceReady")) and bool(v2_state.get("shortReleaseNetGreenReady")): next_action=f"RELEASE READY · BODEM {protected_extreme:.8g} · RE-HEDGE OP DEZELFDE PRIJS"
        elif state_machine_version>=8 and short_qty>0: next_action=f"BODEM VOLGEN · {protected_extreme:.8g} · RELEASE {next_release_price:.8g}"
        elif state_machine_version>=8 and short_qty<=0 and rehedge_armed: next_action=f"LONG VRIJ · RE-HEDGE GEWAPEND OP BODEM {rehedge_price:.8g}"
        elif state_machine_version>=8: next_action="LONG VRIJ · WACHT OP PORTFOLIODOEL OF RE-HEDGE"
        elif state_machine_version>=6 and short_qty>0 and int(safe_float(v2_state.get("dcaCount")))==0: next_action=f"START HEDGE ACTIEF · EERSTE DCA TRAILT MEE OP {next_dca:.8g}"
        elif state_machine_version>=6 and str(v2_state.get("cycleStatus",""))=="DCA_PROTECTION_MARGIN_BLOCKED": next_action="PROTECTION MARGIN LOW · DCA BLIJFT PENDING"
        elif state_machine_version>=6 and short_qty>0 and bool(v2_state.get("shortReleasePriceReady")) and bool(v2_state.get("shortReleaseNetGreenReady")) and not bool(v2_state.get("protectionReserveReady",False)): next_action="RELEASE GEBLOKKEERD · PROTECTION MARGIN LOW"
        elif state_machine_version>=6 and short_qty>0 and bool(v2_state.get("shortReleasePriceReady")) and bool(v2_state.get("shortReleaseNetGreenReady")): next_action=(f"RELEASE READY · +{strategy2_settings.focus_v2_hedge_release_recovery_pct*100:.2f}% · PROTECTION READY" if protection_ui_ready else f"RELEASE READY · +{strategy2_settings.focus_v2_hedge_release_recovery_pct*100:.2f}% · REALTIME PROTECTION NIET READY")
        elif state_machine_version>=6 and short_qty>0 and bool(v2_state.get("shortReleasePriceReady")): next_action=f"RELEASEPRIJS BEREIKT · WACHT OP SHORT NETTO GROEN"
        elif state_machine_version>=6 and short_qty>0: next_action=f"DCA-HEDGE ACTIEF · DCA {next_dca:.8g} · RELEASE {next_release_price:.8g}"
        elif state_machine_version>=6 and short_qty<=0 and tp_mode=="usdt" and long_open_pnl>=tp_value>0: next_action=f"FULL TP BEREIKT · LONG VOLLEDIG SLUITEN ${tp_value:.2f}"
        elif state_machine_version>=6 and short_qty<=0 and tp_mode=="percent" and long_notional>0 and long_open_pnl/long_notional>=tp_value>0: next_action=f"FULL TP BEREIKT · LONG VOLLEDIG SLUITEN {tp_value*100:.2f}%"
        elif state_machine_version>=6: next_action=f"PRIMARY-ONLY · TRAILING DCA {next_dca:.8g} · TP {('$'+format(tp_value,'.2f')) if tp_mode=='usdt' else format(tp_value*100,'.2f')+'%'}"
        elif state_machine_version>=5 and short_qty>0 and release_ready: next_action=f"HERSTEL +{strategy2_settings.focus_v2_hedge_release_recovery_pct*100:.2f}% · SHORT VOLLEDIG LOSLATEN"
        elif state_machine_version>=5 and short_qty>0: next_action=f"HEDGE ACTIEF · DCA {next_dca:.8g} · RELEASE {next_release_price:.8g}"
        elif state_machine_version>=5 and profit_trigger>0 and profit_since_harvest>=profit_trigger: next_action=f"WINSTTRIGGER BEREIKT · AFROMEN ${profit_harvest:.2f}"
        elif state_machine_version>=5: next_action=f"LONG-ONLY · TRAILING DCA {next_dca:.8g}" if next_dca>0 else "LONG-ONLY · TRAILING ACTIEF"
        elif recovery_model_version>=3 and str(v2_state.get("lastAction",""))=="REHEDGE_RESTORED": next_action="TERUGVAL · HEDGE HERSTELD"
        elif recovery_model_version>=3 and short_qty<=max(1e-10,max(1.0,long_notional*.002)/max(current,1e-12)) and rehedge_armed: next_action="SHORT VRIJ · LONG KRIJGT RUIMTE"
        elif recovery_model_version>=3 and release_ready: next_action="BODEM / HERSTEL · SHORT STOP EERST GEWAPEND"
        elif recovery_model_version>=3 and profit_trigger>0 and profit_since_harvest>=profit_trigger: next_action=f"WINSTTRIGGER BEREIKT · AFROMEN ${profit_harvest:.2f}"
        elif recovery_model_version>=3 and str(v2_state.get("lastAction",""))=="PROFIT_HARVEST": next_action="WINST AFGEROOMD · CYCLE BLIJFT ACTIEF"
        elif recovery_model_version>=3 and not price_met: next_action="DALING · BESCHERMD"
        elif profit_trigger>0 and profit_since_harvest>=profit_trigger: next_action=f"PROFIT HARVEST GEREED · ${profit_harvest:.2f}"
        elif next_dca>0 and current>0 and current<=next_dca: next_action=f"DCA {int(safe_float(v2_state.get('dcaCount')))+1} gereed"
        elif recovery_model_version==2 and str(v2_state.get("lastAction",""))=="REHEDGE_RESTORED": next_action="TERUGVAL · HEDGE HERSTELD"
        elif recovery_model_version==2 and rehedge_armed: next_action=f"RE-HEDGE GEWAPEND · {armed_rehedge_qty:.6g} SHORT"
        elif recovery_model_version==2 and release_ready: next_action=f"HERSTEL {min(4,recovery_stage+1)} · RELEASE {strategy2_settings.focus_v2_release_ratio*100:.0f}%"
        elif recovery_model_version==2 and recovery_stage>=3: next_action="BIJNA BREAK-EVEN · LONG KRIJGT RUIMTE"
        elif recovery_model_version==2 and recovery_progress>0: next_action="BODEM GEVORMD · HERSTEL WORDT GEVOLGD"
        elif rehedge_armed: next_action=f"RE-HEDGE SHORT gewapend op {rehedge_price:.8g}"
        elif release_ready: next_action=f"SHORT RELEASE {strategy2_settings.focus_v2_release_ratio*100:.0f}% gereed"
        elif not price_met: next_action="Wacht op prijsherstel"
        elif not middle_met: next_action="Herstel bezig · wacht op 5m Bollinger-middle"
        elif recovery_model_version<2 and not portfolio_met: next_action=f"Wacht op portfolioherstel tot {strategy2_settings.focus_v2_portfolio_recovery_ratio*100:.1f}%"
        elif profit_trigger>0 and profit_remaining>0: next_action=(f"NOG ${profit_remaining:.2f} TOT WINST AFROMEN" if recovery_model_version>=3 else f"NOG ${profit_remaining:.2f} TOT PROFIT HARVEST")
        else: next_action="DALING · BESCHERMD" if recovery_model_version>=3 else ("DALING · VOLLEDIG BESCHERMD" if recovery_model_version>=2 else "Hedge actief · bescherming in balans")
        recent_actions=[]
        try:
            for doc in aster_strategy2_reference(uid).collection("audit").order_by("timestampMs",direction=firestore.Query.DESCENDING).limit(40).stream():
                a=doc.to_dict() or {}; details=a.get("details") if isinstance(a.get("details"),dict) else {}
                if str(a.get("mode","")).lower()!="focus_v2" or str(details.get("symbol",v2_symbol)).upper()!=v2_symbol: continue
                recent_actions.append({"event":str(a.get("event","")),"timestampMs":int(safe_float(a.get("timestampMs"))),"price":safe_float(details.get("price",details.get("fillPrice",0))),"quantity":safe_float(details.get("quantity",details.get("fillQuantity",0))),"details":details})
                if len(recent_actions)>=20: break
        except Exception: pass
        long_break_even=safe_float((v2_long.get("strategy2Tp") or {}).get("breakEvenPrice")) if isinstance(v2_long.get("strategy2Tp"),dict) else long_entry
        cycle_start=safe_float(v2_state.get("cycleStartEquity")); cycle_equity=safe_float(v2_history.get("equity")) or safe_float(strategy2_snapshot.get("equity"))
        focus_v2_cockpit={"symbol":v2_symbol,"cycleId":str(v2_state.get("cycleId","")),"currentPrice":current,"longQuantity":long_qty,"longEntry":long_entry,"longBreakEvenPrice":long_break_even or long_entry,"longNotional":long_notional,"longPnl":safe_float(v2_long.get("unrealizedPnl",v2_long.get("unRealizedProfit"))),"longLeverage":safe_float(v2_long.get("leverage")),"shortQuantity":short_qty,"shortEntry":short_entry,"shortNotional":short_notional,"shortPnl":safe_float(v2_short.get("unrealizedPnl",v2_short.get("unRealizedProfit"))),"shortLeverage":safe_float(v2_short.get("leverage")),"netExposure":long_notional-short_notional,"grossExposure":long_notional+short_notional,"hedgeRatio":(short_notional/long_notional if long_notional>0 else 0.0),"dcaCount":int(safe_float(v2_state.get("dcaCount"))),"dcaAnchorPrice":dca_anchor,"nextLongDcaPrice":next_dca,"nextLongDcaDistancePct":((next_dca/current-1)*100 if next_dca>0 and current>0 else None),"recoveryReboundPrice":rebound,"recoveryTrigger":rebound,"longTakeProfitPrice":(0.0 if recovery_model_version>=3 else (safe_float(v2_history.get("longTakeProfitPrice")) or (long_entry*(1+strategy2_settings.focus_minimum_profit_pct) if long_entry>0 else 0.0))),"recoveryPriceMet":price_met,"bollinger5mMiddle":safe_float(v2_history.get("bollinger5mMiddle")),"bollinger5mConfirmed":middle_met,"portfolioRecoveryTarget":safe_float(v2_history.get("portfolioRecoveryTarget")) or cycle_start*strategy2_settings.focus_v2_portfolio_recovery_ratio,"portfolioRecoveryMet":portfolio_met,"shortReleaseRatio":strategy2_settings.focus_v2_release_ratio,"shortReleaseReady":release_ready,"nextShortReleasePrice":next_release_price,"nextShortReleaseQty":next_release_qty,"recoveryModelVersion":recovery_model_version,"recoveryStage":recovery_stage,"recoveryProgress":recovery_progress,"recoveryLow":recovery_low,"recoveryHigh":recovery_high,"releasedShortQty":released_short_qty,"targetShortNotional":target_short_notional,"rehedgePrice":rehedge_price,"rehedgeArmed":rehedge_armed,"armedRehedgeQty":armed_rehedge_qty,"cycleStartEquity":cycle_start,"cycleEquity":cycle_equity,"cyclePnl":cycle_equity-cycle_start if cycle_start>0 else 0.0,"cycleTargetActive":False,"cycleTargetEquity":None,"stateMachineVersion":state_machine_version,"cycleStatus":str(v2_state.get("cycleStatus",v2_state.get("lastAction","HOLD"))),"startHedgePercent":safe_float(v2_state.get("startHedgePercent",getattr(strategy2_settings,"focus_v2_start_hedge_ratio",0))),"hedgeTargetPercent":safe_float(v2_state.get("hedgeTargetPercent",strategy2_settings.focus_v2_hedge_ratio)),"tpMode":tp_mode,"tpValue":tp_value,"distanceToTp":profit_remaining,"autoRestart":bool(v2_state.get("autoRestart",getattr(strategy2_settings,"focus_v2_auto_restart",False))),"dcaMode":str(v2_state.get("dcaMode","")),"dcaTriggerPending":bool(v2_state.get("dcaTriggerPending",False)),"dcaTriggerPrice":safe_float(v2_state.get("dcaTriggerPrice")),"protectedFloorPrice":safe_float(v2_state.get("protectedFloorPrice")),"protectedCeilingPrice":safe_float(v2_state.get("protectedCeilingPrice")),"reHedgeAnchorPrice":safe_float(v2_state.get("reHedgeAnchorPrice")),"releaseRehedgeMarginReady":bool(v2_state.get("releaseRehedgeMarginReady",False)),"releaseRehedgeRequiredMargin":safe_float(v2_state.get("releaseRehedgeRequiredMargin")),"releaseRehedgeAvailableAfterCloseEstimate":safe_float(v2_state.get("releaseRehedgeAvailableAfterCloseEstimate")),"hedgeReleaseTriggerToSubmitMs":safe_float(v2_state.get("hedgeReleaseTriggerToSubmitMs")),"reHedgeTriggerToSubmitMs":safe_float(v2_state.get("reHedgeTriggerToSubmitMs")),"protectionReserveRequired":safe_float(v2_state.get("protectionReserveRequired")),"protectionReserveAvailable":safe_float(v2_state.get("protectionReserveAvailable")),"protectionReserveSpendableMargin":safe_float(v2_state.get("protectionReserveSpendableMargin")),"protectionReserveReady":bool(v2_state.get("protectionReserveReady",False)),"protectionReserveShortfall":safe_float(v2_state.get("protectionReserveShortfall")),"realtimeWorkerConnected":realtime_worker_connected,"realtimeWorkerHealthy":realtime_worker_healthy,"protectionStatus":("PROTECTION READY" if protection_ui_ready else ("PROTECTION MARGIN LOW" if not bool(v2_state.get("protectionReserveReady",False)) else "PROTECTION REALTIME NOT READY")),"triggerToLongSubmitMs":safe_float(v2_state.get("triggerToLongSubmitMs")),"longFillToShortSubmitMs":safe_float(v2_state.get("longFillToShortSubmitMs")),"triggerToFullHedgeMs":safe_float(v2_state.get("triggerToFullHedgeMs")),"hedgeState":str(v2_state.get("hedgeState","")),"lastDcaFillPrice":last_dca_fill,"hedgeReleasePrice":next_release_price if state_machine_version>=5 else 0.0,"shortNetGreenReleasePrice":safe_float(v2_state.get("shortNetGreenReleasePrice",v2_history.get("shortNetGreenReleasePrice"))),"shortReleasePriceReady":bool(v2_state.get("shortReleasePriceReady",False)),"shortReleaseNetGreenReady":bool(v2_state.get("shortReleaseNetGreenReady",False)),"expectedNetShortClosePnl":safe_float(v2_state.get("expectedNetShortClosePnl")),"hedgeReleaseRecoveryPct":strategy2_settings.focus_v2_hedge_release_recovery_pct if state_machine_version>=5 else 0.0,"recoverySinceLastDcaPct":safe_float(v2_history.get("recoverySinceLastDcaPct")),"hedgeTargetQty":safe_float(v2_state.get("hedgeTargetQty",v2_history.get("hedgeTargetQty"))),"harvestBaselineEquity":harvest_baseline,"profitSinceHarvest":profit_since_harvest,"profitTriggerUsdt":profit_trigger,"profitHarvestUsdt":profit_harvest,"profitRemainingUsdt":profit_remaining,"lastHarvestProfit":safe_float(v2_state.get("lastHarvestProfit",v2_history.get("lastHarvestProfit"))),"totalHarvestedProfit":safe_float(v2_state.get("totalHarvestedProfit",v2_history.get("totalHarvestedProfit"))),"nextAction":next_action,"status":str(v2_state.get("lastAction","HOLD")),"runtimePhase":runtime_phase,"runtimeHoldReason":runtime_hold_reason,"recentActions":recent_actions}
    closed_trades = _stored_aster_closed_trades(user)
    def confirmed_snapshot_number(key: str) -> float | None:
        value=snapshot.get(key)
        return safe_float(value) if value is not None else None
    status = {
        "configured": True, "credentialsVerified": True, "hedgeMode": hedge_mode,
        "equity": confirmed_snapshot_number("equity"),
        "walletBalance": confirmed_snapshot_number("walletBalance"),
        "availableBalance": confirmed_snapshot_number("availableBalance"),
        "unrealizedPnl": confirmed_snapshot_number("unrealizedPnl"),
        "activePositions": len(positions),
        "activeTradeCapital": confirmed_snapshot_number("activeTradeCapital"),
        "financialDataContract": snapshot.get("financialDataContract") if isinstance(snapshot.get("financialDataContract"), dict) else {},
        "maintenanceMargin": confirmed_snapshot_number("maintenanceMargin"),
        "maintenanceMarginPct": confirmed_snapshot_number("maintenanceMarginPct"),
        "liquidationRiskPct": confirmed_snapshot_number("liquidationRiskPct"),
        "liquidationRiskSource": str(snapshot.get("liquidationRiskSource", "")),
        "marginBalance": confirmed_snapshot_number("marginBalance"),
        "totalUnrealizedPnl": confirmed_snapshot_number("totalUnrealizedPnl"),
        "totalCrossNotional": confirmed_snapshot_number("totalCrossNotional"),
        "longNotional": confirmed_snapshot_number("longNotional"),
        "shortNotional": confirmed_snapshot_number("shortNotional"),
        "netExposure": confirmed_snapshot_number("netExposure"),
        "grossExposure": confirmed_snapshot_number("grossExposure"),
        "positionCountIncluded": int(safe_float(snapshot.get("positionCountIncluded"))),
        "marginRatio": confirmed_snapshot_number("marginRatio"),
        "openOrders": int(safe_float(snapshot.get("openOrders"))),
        "positions": positions, "closedTrades": closed_trades, "focusV2Cockpit": focus_v2_cockpit,
        "tradableSymbols": int(safe_float(snapshot.get("tradableSymbols"))),
        "maximumLeverage": int(safe_float(snapshot.get("maximumLeverage"))),
        "liveReady": hedge_mode, "snapshotAt": snapshot.get("capturedAt"),
    }
    return {
        **status,
        **aster_strategy2_public(uid),
        "apiWalletAddress": secret.signer_address,
        "signerAddressSuffix": str(control.get("signerAddressSuffix", secret.signer_address[-6:])),
        # Credential replacement never preserves an enabled switch.
        "liveEnabled": bool(control.get("liveEnabled", False)),
        "ordersEnabled": os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "false").lower() == "true",
    }


@app.get("/v1/me/aster/trade-events")
def aster_trade_events(
    symbol: str = Query(..., min_length=3, max_length=30, pattern=r"^[A-Za-z0-9]+$"),
    side: str = Query(..., pattern=r"^(?i:long|short)$"),
    closed_at_ms: int | None = Query(default=None, ge=1),
    anchor_at_ms: int | None = Query(default=None, ge=1),
    all_cycles: bool = Query(default=False),
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Return confirmed fills for exactly one selected Aster position cycle."""
    normalized_symbol, normalized_side = symbol.upper(), side.upper()
    secret = load_aster_secret(user)
    client = AsterV3Client(
        signer_address=secret.signer_address,
        sign_message=local_eip712_signer(secret),
        live_authorized=False,
    )
    try:
        fills = client.user_trades(normalized_symbol, limit=500)
    except (AsterApiError, AsterSubmissionUncertain, AsterValidationError, ValueError) as exc:
        raise HTTPException(503, "Aster-fillhistorie is tijdelijk niet beschikbaar.") from exc
    events = trade_events_from_fills(
        fills if isinstance(fills, list) else [], symbol=normalized_symbol,
        position_side=normalized_side, closed_at_ms=closed_at_ms, anchor_at_ms=anchor_at_ms,
        include_all_cycles=all_cycles,
    )
    # Partial Focus 2.0 harvest is an intentional reduction, not a full close.
    # Overlay confirmed audit evidence so the chart can label it HARVEST instead of CLOSE.
    if normalized_side == "LONG":
        try:
            strategy_ref=aster_strategy2_reference(str(user["uid"]))
            for doc in strategy_ref.collection("audit").order_by("timestampMs",direction=firestore.Query.DESCENDING).limit(100).stream():
                row=doc.to_dict() or {}; details=row.get("details") if isinstance(row.get("details"),dict) else {}
                if str(row.get("event","")).upper()!="FOCUS_V2_PROFIT_HARVEST" or str(details.get("symbol","")).upper()!=normalized_symbol: continue
                ts=int(safe_float(row.get("timestampMs"))); price=safe_float(details.get("closePrice")); qty=safe_float(details.get("longReducedQty"))
                if ts<=0 or price<=0 or qty<=0: continue
                events.append({"id":f"focus-v2-harvest:{doc.id}","symbol":normalized_symbol,"side":"LONG","kind":"harvest","action":"close","price":price,"quantity":qty,"notionalUsd":price*qty,"notional":price*qty,"exchange":"Aster","at":datetime.fromtimestamp(ts/1000,tz=timezone.utc).isoformat(),"timestampMs":ts,"realizedPnl":safe_float(details.get("realizedNetProfitUsd"))})
            events.sort(key=lambda item:(int(safe_float(item.get("timestampMs"))),str(item.get("id",""))))
        except Exception:
            pass
    return {"symbol": normalized_symbol, "side": normalized_side, "events": events, "source": "aster-confirmed-fills+focus-audit"}


def _epoch_ms(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if hasattr(value, "timestamp"):
        try: return int(value.timestamp() * 1000)
        except (TypeError, ValueError): return 0
    numeric = int(safe_float(value))
    return numeric * 1000 if 0 < numeric < 10_000_000_000 else numeric


def _aster_replay_candles(symbol: str, start_ms: int, end_ms: int, interval: str = "15m") -> list[ReplayCandle]:
    """Read-only public candles, paged without crossing the comparison moment."""
    rows: list[ReplayCandle] = []
    cursor = start_ms
    interval_ms = 15 * 60 * 1000
    with httpx.Client(base_url="https://fapi.asterdex.com", timeout=20.0) as client:
        for _ in range(40):
            response = client.get("/fapi/v1/klines", params={"symbol": symbol, "interval": interval, "startTime": cursor, "endTime": end_ms, "limit": 1000})
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload: break
            batch = [ReplayCandle(int(item[0]), safe_float(item[1]), safe_float(item[2]), safe_float(item[3]), safe_float(item[4])) for item in payload if isinstance(item, list) and len(item) >= 5]
            batch = [item for item in batch if item.timestamp_ms <= end_ms and item.open > 0 and item.high > 0 and item.low > 0 and item.close > 0]
            rows.extend(batch)
            next_cursor = max((item.timestamp_ms for item in batch), default=cursor) + interval_ms
            if next_cursor <= cursor or len(payload) < 1000: break
            cursor = next_cursor
    unique = {item.timestamp_ms: item for item in rows}
    return [unique[key] for key in sorted(unique)]


def _aster_strategy2_replay(uid: str, request: AsterPortfolioReplayRequest, job_id: str) -> dict[str, Any]:
    strategy_ref = aster_strategy2_reference(uid)
    job_ref = strategy_ref.collection("portfolioReplays").document(job_id)
    raw = strategy_ref.get().to_dict() or {}
    started_at = _epoch_ms(raw.get("startedAt"))
    comparison_at = int(time.time() * 1000)
    if not started_at or started_at >= comparison_at:
        raise ValueError("Het bewezen startmoment van de huidige Strategy 2-run ontbreekt")
    base = Strategy2Config.from_mapping(raw.get("settings"))
    config_a = config_with_overrides(base, request.test_a)
    config_b = config_with_overrides(base, request.test_b)
    job_ref.set({"status":"MARKET_DATA_LOADING","progress":15,"updatedAt":datetime.now(timezone.utc)}, merge=True)

    audit_rows = [item.to_dict() or {} for item in strategy_ref.collection("audit").where("timestamp", ">=", datetime.fromtimestamp(started_at/1000, timezone.utc)).stream()]
    entry_events = []
    for row in audit_rows:
        event = str(row.get("event", "")).upper()
        side = str(row.get("side", "")).upper()
        symbol = str(row.get("symbol", "")).upper()
        timestamp_ms = _epoch_ms(row.get("timestamp"))
        if event in {"INITIAL_OPEN_LEG", "OPEN_LEG"} and side in {"LONG", "SHORT"} and symbol and timestamp_ms:
            entry_events.append(ReplaySeed(symbol, side, timestamp_ms))
    if not entry_events:
        for row in raw.get("ownedLegs") if isinstance(raw.get("ownedLegs"), list) else []:
            if not isinstance(row, dict): continue
            side, symbol = str(row.get("side", "")).upper(), str(row.get("symbol", "")).upper()
            timestamp_ms = int(safe_float(row.get("createdAtMs"))) or started_at
            if side in {"LONG", "SHORT"} and symbol: entry_events.append(ReplaySeed(symbol, side, timestamp_ms))
    symbols = sorted({item.symbol for item in entry_events})
    if not symbols: raise ValueError("Geen bewezen Strategy 2-pairs gevonden")
    if len(symbols) > 100: raise ValueError("Meer dan 100 Strategy 2-pairs; replay is veilig begrensd")

    secret = load_aster_secret({"uid":uid})
    client = AsterV3Client(signer_address=secret.signer_address, sign_message=local_eip712_signer(secret), live_authorized=False)
    account = client.account_information()
    positions = client.position_risk()
    live_equity, _, _, live_unrealized, live_maintenance = aster_account_information_values(account)
    income = client.income_history(start_time=started_at, end_time=comparison_at, limit=1000)
    net_realized = sum(safe_float(row.get("income")) for row in income if str(row.get("incomeType", "")).upper() in {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"})
    observed_funding = sum(safe_float(row.get("income")) for row in income if str(row.get("incomeType", "")).upper() == "FUNDING_FEE")
    external_cashflow = sum(safe_float(row.get("income")) for row in income if str(row.get("incomeType", "")).upper() in {"TRANSFER", "WELCOME_BONUS", "INSURANCE_CLEAR"})
    local_now = datetime.fromtimestamp(comparison_at / 1000, ZoneInfo("Europe/Amsterdam"))
    day_start_ms = int(local_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    live_closed_today = sum(
        safe_float(row.get("income")) for row in income
        if str(row.get("incomeType", "")).upper() == "REALIZED_PNL" and _epoch_ms(row.get("time", row.get("timestamp"))) >= day_start_ms
    )
    live_gross_exposure = sum(
        abs(safe_float(row.get("positionAmt"))) * safe_float(row.get("markPrice"))
        for row in positions if isinstance(row, dict)
    )
    maintenance_rate = live_maintenance / live_gross_exposure if live_maintenance > 0 and live_gross_exposure > 0 else 0.0
    live_maintenance_pct = live_maintenance / live_equity * 100 if live_equity > 0 else 0.0
    start_equity = live_equity - live_unrealized - net_realized - external_cashflow
    if start_equity <= 0:
        raise ValueError("De start-equity kan niet betrouwbaar uit exchange-cashflows worden herbouwd")

    candles: dict[str, list[ReplayCandle]] = {}
    for index, symbol in enumerate(symbols):
        candles[symbol] = _aster_replay_candles(symbol, started_at, comparison_at)
        job_ref.set({"progress":min(55, 15 + int((index + 1) / len(symbols) * 40)), "updatedAt":datetime.now(timezone.utc)}, merge=True)
    missing = [symbol for symbol, rows in candles.items() if not rows]
    if missing: raise ValueError(f"Historische candles ontbreken voor {', '.join(missing[:8])}")

    common = {"candles":candles,"seeds":entry_events,"start_equity":start_equity,"comparison_at_ms":comparison_at,"observed_funding":observed_funding,"external_cashflow":external_cashflow,"day_start_ms":day_start_ms,"maintenance_rate":maintenance_rate}
    job_ref.set({"status":"REFERENCE_RUNNING","progress":60,"updatedAt":datetime.now(timezone.utc)}, merge=True)
    reference = run_portfolio_replay(config=base, **common)
    job_ref.set({"status":"TEST_A_RUNNING","progress":72,"updatedAt":datetime.now(timezone.utc)}, merge=True)
    test_a = run_portfolio_replay(config=config_a, **common)
    job_ref.set({"status":"TEST_B_RUNNING","progress":84,"updatedAt":datetime.now(timezone.utc)}, merge=True)
    test_b = run_portfolio_replay(config=config_b, **common)
    conclusion = comparison_conclusion(live_equity=live_equity, reference=reference, test_a=test_a, test_b=test_b, live_closed_today=live_closed_today, live_maintenance_pct=live_maintenance_pct)
    result = {
        "id":job_id,"status":"COMPLETED","progress":100,"strategyId":base.strategy_id,
        "startedAt":datetime.fromtimestamp(started_at/1000, timezone.utc),"comparisonAt":datetime.fromtimestamp(comparison_at/1000, timezone.utc),
        "liveEquity":live_equity,"liveMetrics":{"endingPortfolio":live_equity,"closedResultToday":live_closed_today,"maintenancePct":live_maintenance_pct},"startEquity":start_equity,"reference":reference,"testA":test_a,"testB":test_b,
        "conclusion":conclusion,"symbols":symbols,"dataSource":"Aster Futures + bevestigde Strategy 2-audit",
        "limitations":["Pairselectie volgt bewezen live-auditmomenten", "Historische funding is als geobserveerde cashflow toegepast", "Geen enkele orderadapter is beschikbaar in replay"],
        "updatedAt":datetime.now(timezone.utc),"createdAt":datetime.now(timezone.utc),
    }
    job_ref.set(result)
    return result


def _public_replay(row: dict[str, Any], replay_id: str) -> dict[str, Any]:
    result = {**row, "id":replay_id}
    for field in ("startedAt", "comparisonAt", "updatedAt", "createdAt"):
        value = result.get(field)
        if hasattr(value, "isoformat"): result[field] = value.isoformat()
    return result


@app.post("/v1/me/aster/strategy2/replays")
def start_aster_strategy2_replay(request: AsterPortfolioReplayRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Synchronous server-side replay; read-only exchange client by construction."""
    uid, job_id = str(user["uid"]), python_secrets.token_urlsafe(12)
    ref = aster_strategy2_reference(uid).collection("portfolioReplays").document(job_id)
    ref.set({"id":job_id,"status":"PREPARING","progress":5,"createdAt":datetime.now(timezone.utc),"testAOverrides":request.test_a,"testBOverrides":request.test_b})
    try:
        return _public_replay(_aster_strategy2_replay(uid, request, job_id), job_id)
    except (AsterApiError, AsterValidationError, httpx.HTTPError, ValueError) as exc:
        ref.set({"status":"INSUFFICIENT_DATA" if isinstance(exc, ValueError) else "FAILED","progress":100,"error":str(exc),"updatedAt":datetime.now(timezone.utc)}, merge=True)
        raise HTTPException(409 if isinstance(exc, ValueError) else 503, str(exc)) from exc


@app.get("/v1/me/aster/strategy2/replays")
def list_aster_strategy2_replays(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    rows = aster_strategy2_reference(str(user["uid"])).collection("portfolioReplays").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(20).stream()
    return {"replays":[_public_replay(item.to_dict() or {}, item.id) for item in rows]}


@app.get("/v1/me/aster/strategy2/replays/{replay_id}")
def get_aster_strategy2_replay(replay_id: str, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", replay_id): raise HTTPException(422, "Ongeldige replay-ID")
    row = aster_strategy2_reference(str(user["uid"])).collection("portfolioReplays").document(replay_id).get().to_dict()
    if not row: raise HTTPException(404, "Replay bestaat niet")
    return _public_replay(row, replay_id)


def _money_grabber_activation_preview(uid: str, user: dict[str, Any]) -> dict[str, Any]:
    """Build a fresh, read-only activation contract; this function cannot submit an order."""
    ref=aster_strategy2_reference(uid);raw=ref.get().to_dict() or {}
    settings=Strategy2Config.from_mapping(raw.get("settings"))
    if not settings.money_grabber_enabled:
        raise HTTPException(409,"Zet Money Grabber eerst aan en sla de Strategy-2-configuratie op")
    secret=load_aster_secret(user)
    client=AsterV3Client(signer_address=secret.signer_address,
        sign_message=local_eip712_signer(secret),live_authorized=False)
    try:
        hedge=client.position_mode();account=client.account_information()
        positions=client.position_risk();orders=client.open_orders();info=client.public_exchange_info()
    except (AsterApiError,ValueError) as exc:
        raise HTTPException(409,f"Money Grabber-preview kon Aster niet betrouwbaar lezen: {exc}") from exc
    owned_rows=proven_owned_rows(raw.get("ownedLegs",[]),strategy_id="aster-strategy-2",engine_type="strategy2")
    owned_keys={(str(x.get("symbol","")).upper(),str(x.get("side","")).upper()) for x in owned_rows}
    active=[x for x in positions if abs(safe_float(x.get("positionAmt")))>0]
    active_keys={(str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) for x in active}
    unknown=sorted(active_keys-owned_keys)
    strategy_positions=[x for x in active if (str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) in owned_keys]
    relevant_orders=[x for x in orders if (str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) in owned_keys]
    symbols={str(x.get("symbol","")).upper() for x in strategy_positions}
    contract_symbols={str(x.get("symbol","")).upper() for x in info.get("symbols",[]) if isinstance(x,dict)} if isinstance(info,dict) else set()
    unsafe_contracts=sorted(symbols-contract_symbols)
    equity,_,available,_,maintenance=aster_account_information_values(account)
    gross=sum(abs(safe_float(x.get("positionAmt")))*safe_float(x.get("markPrice")) for x in strategy_positions)
    expected_exit_fees=gross*.0005;spread_slippage=gross*.001
    evidence=NetValueEvidence(visible_equity=equity,expected_exit_fees=expected_exit_fees,
        slippage_buffer=spread_slippage,fresh=True,reliable=equity>0,captured_at_ms=int(time.time()*1000))
    try:net_start=evidence.expected_net_close_value()
    except ValueError:net_start=0.0
    partial=full=0;protection_notional=0.0
    for row in strategy_positions:
        entry=safe_float(row.get("entryPrice"));mark=safe_float(row.get("markPrice"));side=str(row.get("positionSide","")).upper()
        move=max(0,(entry-mark)/entry if side=="LONG" and entry>0 else (mark-entry)/entry if side=="SHORT" and entry>0 else 0)
        notional=abs(safe_float(row.get("positionAmt")))*mark
        if move>=settings.money_grabber_full_threshold:full+=1;protection_notional+=notional*settings.money_grabber_full_ratio
        elif move>=settings.money_grabber_first_threshold:partial+=1;protection_notional+=notional*settings.money_grabber_first_ratio
    estimated_margin=protection_notional/max(1,settings.leverage)
    reserve=max(0,available-estimated_margin)
    blockers=[]
    if not hedge:blockers.append("Aster Hedge Mode staat uit")
    if unknown:blockers.append("Niet alle actieve posities hebben bewezen Strategy-2-ownership")
    if relevant_orders:blockers.append("Er staan relevante Strategy-2-orders open")
    if unsafe_contracts:blockers.append("Contractregels ontbreken voor bescherming")
    if available<estimated_margin:blockers.append("Beschikbare beschermingsmargin is onvoldoende")
    if equity<=0 or net_start<=0:blockers.append("Netto startwaarde is niet betrouwbaar positief")
    captured_at=datetime.now(timezone.utc)
    material=json.dumps({"uid":uid,"keys":sorted(active_keys),
        "orders":sorted(str(x.get("orderId",x.get("clientOrderId",""))) for x in relevant_orders),
        "owned":sorted(owned_keys),"unsafeContracts":unsafe_contracts,
        "hedge":hedge,"target":settings.money_grabber_round_target},sort_keys=True)
    fingerprint=hashlib.sha256(material.encode()).hexdigest()
    preview={"readOnly":True,"ordersSent":0,"capturedAt":captured_at,"expiresAt":captured_at+timedelta(minutes=2),
        "fingerprint":fingerprint,"activationAllowed":not blockers,"blockers":blockers,
        "exchangeEquity":equity,"expectedNetStartValue":net_start,"roundTargetPercent":settings.money_grabber_round_target*100,
        "targetNetValue":net_start*(1+settings.money_grabber_round_target),"strategy2Positions":len(strategy_positions),
        "aboveFirstThreshold":partial+full,"aboveFullThreshold":full,"estimatedProtectionMargin":estimated_margin,
        "availableProtectionReserve":reserve,"unreliableOwnership":[{"symbol":x[0],"side":x[1]} for x in unknown],
        "unsafeContracts":unsafe_contracts,"hedgeModeConfirmed":hedge,"openRelevantOrders":len(relevant_orders),
        "maintenanceMargin":maintenance,"evidence":{"visibleEquity":equity,"expectedExitFees":expected_exit_fees,
            "slippageBuffer":spread_slippage,"capturedAtMs":evidence.captured_at_ms,"fresh":True,"reliable":not blockers}}
    ref.set({"moneyGrabberActivationPreview":preview,"updatedAt":captured_at},merge=True)
    return preview


@app.get("/v1/me/aster/strategy2/money-grabber/activation-preview")
def money_grabber_activation_preview(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    return _money_grabber_activation_preview(str(user["uid"]),user)


@app.post("/v1/me/aster/strategy2/money-grabber/start-round")
def start_money_grabber(request:MoneyGrabberRoundStartRequest,user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    if not request.confirm:raise HTTPException(422,"Bevestig de Money Grabber-ronde expliciet")
    uid=str(user["uid"]);ref=aster_strategy2_reference(uid);existing=ref.get().to_dict() or {}
    if isinstance(existing.get("moneyGrabberRound"),dict) and str(existing["moneyGrabberRound"].get("status","")) not in {"","CLOSED"}:
        raise HTTPException(409,"Er is al een actieve Money Grabber-ronde")
    fresh=_money_grabber_activation_preview(uid,user)
    if fresh["fingerprint"]!=request.preview_fingerprint:
        raise HTTPException(409,"De exchange-state is gewijzigd; controleer de nieuwe activatiepreview")
    if not fresh["activationAllowed"]:raise HTTPException(409,"Money Grabber-activatie is fail-closed geblokkeerd")
    settings=Strategy2Config.from_mapping((ref.get().to_dict() or {}).get("settings"));round_id="mgr-"+python_secrets.token_urlsafe(12)
    ev=fresh["evidence"]
    domain=start_money_grabber_round(account_id=uid,round_id=round_id,target_ratio=settings.money_grabber_round_target,
        evidence=NetValueEvidence(visible_equity=fresh["exchangeEquity"],expected_exit_fees=ev["expectedExitFees"],
            slippage_buffer=ev["slippageBuffer"],fresh=True,reliable=True,captured_at_ms=ev["capturedAtMs"]),
        activation_confirmed=True,ownership_reliable=True,hedge_mode=True,orders_known=True,contracts_known=True,
        protection_margin_sufficient=True,now_ms=int(time.time()*1000))
    stored={"accountId":uid,"roundId":domain.round_id,"status":domain.status,"startNetValue":domain.start_net_value,
        "targetRatio":domain.target_ratio,"targetNetValue":domain.target_net_value,"startedAtMs":domain.started_at_ms,
        "consecutiveTargetProofs":0,"closeIntentId":"","activationFingerprint":fresh["fingerprint"]}
    ref.set({"moneyGrabberRound":stored,"moneyGrabberPairs":[],"moneyGrabberActivated":True,
        "lastReason":"Money Grabber-ronde bevestigd en actief","updatedAt":datetime.now(timezone.utc)},merge=True)
    ref.collection("audit").add({"event":"MONEY_GRABBER_ROUND_STARTED","roundId":round_id,
        "startNetValue":domain.start_net_value,"targetNetValue":domain.target_net_value,"timestamp":datetime.now(timezone.utc)})
    return {"started":True,"ordersSent":0,"round":stored,**aster_strategy2_public(uid)}


@app.get("/v1/me/aster/strategy2/focus/markets")
def strategy2_focus_markets(user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    raw=aster_strategy2_reference(str(user["uid"])).get().to_dict() or {}
    settings=Strategy2Config.from_mapping(raw.get("settings"))
    secret=load_aster_secret(user)
    client=AsterV3Client(signer_address=secret.signer_address,sign_message=local_eip712_signer(secret),live_authorized=False)
    # Manual Multi-Focus must be able to select every currently tradable Aster
    # USDT perpetual. The automatic Focus engine still uses its separate Top-20
    # volume pool via current_focus_markets().
    info=client.public_exchange_info(); tickers=client.ticker_24h(); prices=client.ticker_prices()
    ticker_by={str(x.get("symbol","")).upper():x for x in tickers if isinstance(x,dict)}
    price_by={str(x.get("symbol","")).upper():safe_float(x.get("price")) for x in prices if isinstance(x,dict)}
    rows=[]
    for item in info.get("symbols",[]) if isinstance(info,dict) else []:
        if not isinstance(item,dict): continue
        symbol=str(item.get("symbol","")).upper(); quote=str(item.get("quoteAsset","")).upper()
        status=str(item.get("status","TRADING")).upper(); contract=str(item.get("contractType","PERPETUAL")).upper()
        if not symbol or quote!="USDT" or status!="TRADING" or contract not in {"PERPETUAL",""}: continue
        ticker=ticker_by.get(symbol,{})
        rows.append({"symbol":symbol,"price":price_by.get(symbol,0.0),"change_24h_pct":safe_float(ticker.get("priceChangePercent"))/100.0,
            "quote_volume_24h":max(0.0,safe_float(ticker.get("quoteVolume"))),"tradable":True})
    rows.sort(key=lambda x:(-safe_float(x.get("quote_volume_24h")),str(x.get("symbol",""))))
    return {"readOnly":True,"ordersSent":0,"ranking":rows,"marketCount":len(rows)}


@app.get("/v1/me/aster/strategy2/leverage-tiers")
def strategy2_leverage_tiers(
    symbol: str = Query(min_length=1, max_length=40),
    minimumLeverage: int | None = Query(default=None, ge=1, le=300),
    entryMarginUsd: float | None = Query(default=None, gt=0, le=100000),
    dcaMarginUsd: float | None = Query(default=None, gt=0, le=100000),
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Read-only account-specific Aster leverage tiers for Strategy 2 wizard."""
    uid = str(user["uid"]); raw = aster_strategy2_reference(uid).get().to_dict() or {}
    settings = MultiBbConfig.from_mapping(raw.get("settings"))
    overrides = settings.public_dict()
    if minimumLeverage is not None: overrides["minimumLeverage"] = int(minimumLeverage)
    if entryMarginUsd is not None:
        overrides["entryMarginUsd"] = float(entryMarginUsd); overrides["entrySizingMode"] = "margin"
    if dcaMarginUsd is not None: overrides["dcaMarginUsd"] = float(dcaMarginUsd)
    settings = MultiBbConfig.from_mapping(overrides)
    secret = load_aster_secret(user)
    client = AsterV3Client(signer_address=secret.signer_address, sign_message=local_eip712_signer(secret), live_authorized=False)
    try:
        result = leverage_tier_preview(client=client, symbol=symbol, settings=settings)
    except (AsterApiError, AsterValidationError, ValueError) as exc:
        raise HTTPException(409, f"Aster leverage tiers konden niet betrouwbaar worden gelezen: {exc}") from exc
    return {"readOnly": True, **result}

@app.get("/v1/me/aster/strategy2/focus/shadow")
def strategy2_focus_shadow(user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    """Evaluate one Focus scan against fresh Aster data without an order-capable execution path."""
    uid=str(user["uid"]);raw=aster_strategy2_reference(uid).get().to_dict() or {}
    settings=Strategy2Config.from_mapping(raw.get("settings"))
    if settings.trading_mode!="focus" or not settings.focus_shadow_enabled:
        return {"readOnly":True,"ordersSent":0,"wouldSendCount":0,"reason":"Focus Shadow staat uit"}
    secret=load_aster_secret(user)
    client=AsterV3Client(signer_address=secret.signer_address,sign_message=local_eip712_signer(secret),live_authorized=False)
    try:
        report=build_focus_shadow_report(client=client,raw_state=raw,timestamp_ms=int(time.time()*1000))
    except (AsterApiError,AsterValidationError,KeyError,TypeError,ValueError) as exc:
        return {"readOnly":True,"ordersSent":0,"wouldSendCount":0,"reason":f"Focus Shadow fail-closed: {exc}"}
    report["ordersSent"]=0
    report["readOnly"]=True
    return report


@app.get("/v1/me/aster/strategy2/money-grabber/shadow")
def money_grabber_shadow(user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    """Plan one fresh account scan without database writes or an order-capable client."""
    uid=str(user["uid"]);raw=aster_strategy2_reference(uid).get().to_dict() or {}
    settings=Strategy2Config.from_mapping(raw.get("settings"));round_raw=raw.get("moneyGrabberRound")
    if not settings.money_grabber_enabled or not isinstance(round_raw,dict):
        return {"readOnly":True,"ordersSent":0,"wouldSendCount":0,"reason":"Money Grabber staat uit of heeft geen actieve ronde"}
    secret=load_aster_secret(user);client=AsterV3Client(signer_address=secret.signer_address,
        sign_message=local_eip712_signer(secret),live_authorized=False)
    try:
        hedge=client.position_mode();account=client.account_information();positions=client.position_risk();orders=client.open_orders()
    except (AsterApiError,ValueError) as exc:raise HTTPException(409,f"Money Grabber-shadow kon Aster niet betrouwbaar lezen: {exc}") from exc
    owned=proven_owned_rows(raw.get("ownedLegs",[]),strategy_id="aster-strategy-2",engine_type="strategy2")
    owned_by_key={(str(x.get("symbol","")).upper(),str(x.get("side","")).upper()):x for x in owned}
    active=[]
    for row in positions:
        symbol=str(row.get("symbol","")).upper();side=str(row.get("positionSide","")).upper();qty=abs(safe_float(row.get("positionAmt")))
        owner=owned_by_key.get((symbol,side));mark=safe_float(row.get("markPrice"));entry=safe_float(row.get("entryPrice"))
        if qty<=0 or not owner:continue
        notional=qty*mark;active.append(MoneyGrabberPosition(symbol,side,notional,entry,mark,
            safe_float(row.get("unRealizedProfit",row.get("unrealizedPnl"))),safe_float(owner.get("funding")),
            safe_float(owner.get("fees")),notional*.0005,notional*.001,True))
    equity,_,_,_,_=aster_account_information_values(account);gross=sum(x.notional for x in active)
    pairs=tuple(money_pair_from_mapping(x) for x in raw.get("moneyGrabberPairs",[]) if isinstance(x,dict))
    round_state=money_round_from_mapping(round_raw)
    relevant_orders=[x for x in orders if (str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) in owned_by_key]
    snapshot=MoneyGrabberScanSnapshot(uid,"shadow-"+str(int(time.time()*1000)),round_state,pairs,tuple(active),
        NetValueEvidence(equity,expected_exit_fees=gross*.0005,slippage_buffer=gross*.001,fresh=True,reliable=True,captured_at_ms=int(time.time()*1000)),
        hedge,True,True,not relevant_orders,True,True,max(.01,gross*.00025))
    return money_grabber_shadow_report(plan_money_grabber_scan(settings,snapshot))


def _normalize_focus_slot_target(existing:dict[str,Any],candidate:Strategy2Config)->tuple[Strategy2Config,int]:
    """Preserve every live Multi-Focus slot while allowing the desired count to shrink.

    A reduction is a drain target, not permission to orphan an open position.
    Active slots remain configured until exchange truth confirms one flat; the
    runtime then retires that flat slot instead of reopening it.
    """
    requested=[dict(x) for x in candidate.focus_slots]
    if candidate.trading_mode!="focus" or not requested:
        return candidate,len(requested)
    desired=max(1,min(8,len(requested)))
    old_settings=existing.get("settings") if isinstance(existing.get("settings"),dict) else {}
    old_slots=[dict(x) for x in old_settings.get("focusSlots",[]) if isinstance(x,dict)] if isinstance(old_settings.get("focusSlots"),list) else []
    def sid(row:dict[str,Any],index:int)->str:
        return str(row.get("slotId",f"slot-{index}")).strip() or f"slot-{index}"
    requested_by={sid(row,i):row for i,row in enumerate(requested,1)}
    old_by={sid(row,i):row for i,row in enumerate(old_slots,1)}
    active:set[str]=set()
    for raw in existing.get("ownedLegs",[]) if isinstance(existing.get("ownedLegs"),list) else []:
        role=str(raw.get("role","")).strip() if isinstance(raw,dict) else ""
        upper=role.upper()
        if upper.startswith("FOCUS_SLOT:") and not upper.startswith("FOCUS_SLOT_HEDGE:") and safe_float(raw.get("quantity"))>0:
            active.add(role.split(":",1)[1])
    ordered_active=[sid(row,i) for i,row in enumerate(old_slots,1) if sid(row,i) in active]
    ordered_active.extend(sorted(active-set(ordered_active)))
    normalized:list[dict[str,Any]]=[];seen:set[str]=set()
    for slot_id in ordered_active:
        row=requested_by.get(slot_id) or old_by.get(slot_id)
        if row is None: raise ValueError(f"Actieve Focus-slot {slot_id} mist configuratie; veilig afbouwen is geblokkeerd")
        normalized.append(dict(row));seen.add(slot_id)
    if len(active)<desired:
        for i,row in enumerate(requested,1):
            slot_id=sid(row,i)
            if slot_id in seen: continue
            normalized.append(dict(row));seen.add(slot_id)
            if len(normalized)>=desired: break
    return replace(candidate,focus_slots=tuple(normalized)),desired


@app.put("/v1/me/aster/strategy2/settings")
def save_aster_strategy2_settings(request: AsterStrategySettingsRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    uid=str(user["uid"]); ref=aster_strategy2_reference(uid); existing=ref.get().to_dict() or {}; old=existing.get("settings") if isinstance(existing.get("settings"),dict) else {}
    try: candidate=MultiBbConfig.from_mapping(request.settings)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    version=max(int(safe_float(existing.get("configVersion"))),candidate.version)+1
    saved=MultiBbConfig.from_mapping({**candidate.public_dict(),"version":version}); now=datetime.now(timezone.utc)
    switching=str(old.get("engine",old.get("strategyKind","")))!=MULTI_BB_ENGINE
    update={"settings":saved.public_dict(),"configVersion":version,"updatedAt":now,"phase":"CONFIGURED",
        "lastReason":"Nieuwe Multi DCA-strategie opgeslagen; start de bot handmatig wanneer je klaar bent",
        # A scan report is only valid for the settings version that produced it.
        # Clear it atomically with the settings update so the UI can never show
        # an old order minimum or old position capacity as a current blocker.
        "multiBbReport":{},
        "pendingReopens":[],"focusLiveState":{},"focusLiveSlots":[],"focusV2State":{},"focusV2History":{},
        "moneyGrabberActivated":False,"moneyGrabberRound":None,"moneyGrabberPairs":[]}
    if switching: update.update({"enabled":False,"monitor":False,"multiBbPositions":{}})
    ref.set(update,merge=True)
    ref.collection("configHistory").add({"version":version,"oldValue":old,"newValue":saved.public_dict(),"source":"user-multi-bb-v1","timestamp":now})
    return {"saved":True,**aster_strategy2_public(uid)}


@app.post("/v1/me/aster/strategy2/simulate")
def simulate_aster_strategy2(request: AsterStrategySettingsRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    try: settings=MultiBbConfig.from_mapping({**request.settings,"mode":"paper"})
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    return {"mode":"paper","ordersSent":0,"engine":MULTI_BB_ENGINE,"sameEngineAsLive":True,"configurationValid":True,"errors":[],
        "plannedPositions":settings.maximum_positions,"longSlots":settings.long_slots,"shortSlots":settings.short_slots,
        "rules":{"universeTopN":settings.universe_top_n,"minimumLeverage":settings.minimum_leverage,"entryNotionalUsd":settings.entry_notional_usd,
            "dcaDistance":settings.dca_distance,"dcaMarginUsd":settings.dca_margin_usd,"maxDca":settings.max_dca,"takeProfit":settings.take_profit,
            "entryMode":"immediate_fill"},
        "message":"Nieuwe Multi DCA-configuratie gevalideerd; er zijn 0 orders verzonden."}


@app.get("/v1/me/aster/strategy2/readiness")
def aster_strategy2_readiness(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Read-only exchange validation. This route cannot submit an order."""
    uid=str(user["uid"]);raw=aster_strategy2_reference(uid).get().to_dict() or {}
    secret=load_aster_secret(user)
    client=AsterV3Client(signer_address=secret.signer_address,sign_message=local_eip712_signer(secret),live_authorized=False)
    try:
        hedge=client.position_mode();account=client.account_information();positions=client.position_risk();orders=client.open_orders()
        active_symbols=sorted({str(x.get("symbol","")).upper() for x in positions if abs(safe_float(x.get("positionAmt")))>0})
        order_history=[];fills=[]
        for symbol in active_symbols:
            order_history.extend(client.all_orders(symbol,limit=100))
            fills.extend(client.user_trades(symbol,limit=500))
        income=client.income_history(limit=500)
    except (AsterApiError,ValueError) as exc:
        raise HTTPException(409,f"Live-readiness kon Aster niet volledig lezen: {exc}") from exc
    owned=[]
    for row in raw.get("ownedLegs") if isinstance(raw.get("ownedLegs"),list) else []:
        try: owned.append(OwnedLeg(**row))
        except (TypeError,ValueError): pass
    strategy2_keys={(x.symbol,x.side) for x in owned}
    settings_raw=raw.get("settings") if isinstance(raw.get("settings"),dict) else {}
    if str(settings_raw.get("engine",settings_raw.get("strategyKind","")))==MULTI_BB_ENGINE:
        managed=raw.get("multiBbPositions") if isinstance(raw.get("multiBbPositions"),dict) else {}
        config_version=max(1,int(safe_float(raw.get("configVersion",settings_raw.get("version",1)))))
        for key,row in managed.items():
            symbol,sep,side=str(key).upper().partition("|")
            if not (sep and symbol and side in {"LONG","SHORT"} and isinstance(row,dict) and bool(row.get("botManaged",True))):
                continue
            managed_key=(symbol,side)
            if managed_key in strategy2_keys:
                continue
            owned.append(OwnedLeg(strategy_id="aster-strategy-2",engine_type="strategy2",symbol=symbol,side=side,
                cycle_id=str(row.get("cycleId",f"multi-bb-{symbol}-{side}")),config_version=config_version,
                quantity=abs(safe_float(row.get("lastKnownQty"))),weighted_entry=safe_float(row.get("lastKnownEntry")),
                dca_count=max(0,int(safe_float(row.get("dcaCount")))),role="MULTI_BB",
                created_at_ms=max(0,int(safe_float(row.get("cycleStartedAtMs")))),last_order_at_ms=max(0,int(safe_float(row.get("updatedAtMs"))))))
            strategy2_keys.add(managed_key)
    strategy2_positions=[x for x in positions if (str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) in strategy2_keys]
    strategy2_orders=[x for x in orders if (str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) in strategy2_keys]
    recovery=reconcile_owned_legs(persisted=owned,positions=strategy2_positions,open_orders=strategy2_orders,fills=fills,exchange_reliable=True)
    # Strategy 2 is the only active owner. Unknown/manual legs are isolated by
    # the runtime and never become a cross-strategy collision.
    known_keys=set(strategy2_keys)
    ownership_consistent=True
    report=build_readiness_report(hedge_mode=hedge,account=account,positions=positions,open_orders=orders,
        ownership_keys=known_keys,order_history_readable=isinstance(order_history,list),
        fills_readable=isinstance(fills,list),income_readable=isinstance(income,list),
        reconciliation_passed=recovery.allow_risk_increase and ownership_consistent,
        canary_validated=bool(raw.get("canaryValidated",False)))
    # The report describes this instant. `liveReady` is durable authorization
    # established by a completed canary and must not be cleared by transient
    # conditions such as an open order or an in-progress reconciliation.
    durable_live_ready=bool(raw.get("canaryValidated",False))
    aster_strategy2_reference(uid).set({"readiness":report,"liveReady":durable_live_ready,
        "readinessCheckedAt":datetime.now(timezone.utc)},merge=True)
    return report


@app.post("/v1/me/aster/strategy2/canary")
def run_aster_strategy2_canary(request:AsterStrategy2CanaryRequest,user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    """One idempotent, explicitly confirmed OPEN -> confirmed fill -> CLOSE test."""
    if not request.confirm: raise HTTPException(422,"Bevestig de echte Aster-canary expliciet")
    if os.getenv("ASTER_CANARY_ENABLED","false").lower()!="true":
        raise HTTPException(423,"De afzonderlijke Aster-canarypoort staat centraal uit")
    uid=str(user["uid"]);strategy_ref=aster_strategy2_reference(uid);state=strategy_ref.get().to_dict() or {}
    readiness=state.get("readiness") if isinstance(state.get("readiness"),dict) else {}
    checked_at=state.get("readinessCheckedAt")
    if not readiness.get("softwareReady") or not isinstance(checked_at,datetime) or datetime.now(timezone.utc)-checked_at>timedelta(minutes=5):
        raise HTTPException(409,"Voer eerst opnieuw de live-gereedheidscontrole uit")
    canary_ref=strategy_ref.collection("canaries").document("open-fill-close-v1")
    existing=canary_ref.get().to_dict() or {};action=existing_canary_action(existing.get("status"))
    if str(existing.get("status","")).upper()=="UNKNOWN" and "idempotency-id" in str(existing.get("error","")).lower():
        action="proceed"  # constructor rejected locally before any HTTP order request
    if action=="replay": return {"completed":True,"replayed":True,"orders":existing.get("orders",[]),"symbol":existing.get("symbol")}
    if action=="block": raise HTTPException(409,"Een eerdere canary is nog actief of onzeker; geen tweede order verzonden")
    secret=load_aster_secret(user);client=AsterV3Client(signer_address=secret.signer_address,sign_message=local_eip712_signer(secret),live_authorized=True,before_order_submit=_block_order_during_close_all(str(user["uid"])))
    hedge=client.position_mode();positions=client.position_risk();orders=client.open_orders()
    if not hedge or orders: raise HTTPException(409,"Canary geblokkeerd: Hedge Mode of open-orderstatus is niet veilig")
    account=client.account_information();equity,_,available,_,maint=aster_account_information_values(account)
    if equity<=0 or available<=0 or maint/max(equity,1)>.5: raise HTTPException(409,"Canary geblokkeerd door account- of marginrisico")
    info=client.public_exchange_info();prices={str(x.get("symbol","")).upper():safe_float(x.get("price")) for x in client.ticker_prices()}
    active_symbols={str(x.get("symbol","")).upper() for x in positions if abs(safe_float(x.get("positionAmt")))>0}
    plan=None;symbol_row=None;rejected_minimums=[];tested=set(active_symbols)
    for _ in range(20):
        try: candidate=choose_flat_symbol(info,prices,tested)
        except ValueError: break
        symbol=str(candidate.get("symbol","")).upper();tested.add(symbol)
        try:
            brackets=_aster_brackets(client.leverage_brackets(symbol),symbol)
            candidate_plan=plan_aster_pair(candidate,brackets,prices[symbol],request.notional_usd)
        except (ValueError,AsterApiError) as exc:
            rejected_minimums.append(f"{symbol}: {exc}");continue
        symbol_row=candidate;plan=candidate_plan;break
    if plan is None or symbol_row is None:
        raise HTTPException(409,f"Geen vlak Aster-contract gevonden waarvan het exchange-minimum binnen US$ {request.notional_usd:.2f} past")
    symbol=plan.symbol
    intent_prefix=f"s2c-{uid[-4:]}-{int(time.time())}"
    canary_ref.set({"status":"OPENING","symbol":symbol,"notionalUsd":request.notional_usd,"intentPrefix":intent_prefix,"startedAt":datetime.now(timezone.utc)})
    opened=None
    try:
        client.change_margin_type(symbol,"CROSSED");client.change_leverage(symbol,min(plan.leverage,10))
        opened=execute_aster_leg(client,plan,side=PositionSide.LONG,action="OPEN",id_prefix=intent_prefix,confirm=True)
        open_result=opened.get("result") or {};filled=Decimal(str(open_result.get("executedQty") or plan.quantity))
        close_plan=PairExecutionPlan(symbol,filled,filled*Decimal(str(prices[symbol])),min(plan.leverage,10))
        canary_ref.set({"status":"OPENED","openOrder":open_result},merge=True)
        closed=execute_aster_leg(client,close_plan,side=PositionSide.LONG,action="CLOSE",id_prefix=intent_prefix,confirm=True)
    except Exception as exc:
        preflight_rejected=opened is None and isinstance(exc,AsterValidationError)
        canary_ref.set({"status":"REJECTED" if preflight_rejected else ("OPENED" if opened else "UNKNOWN"),"error":str(exc),"updatedAt":datetime.now(timezone.utc)},merge=True)
        raise HTTPException(409,f"Canary niet volledig afgerond; geen retry verzonden: {exc}") from exc
    orders_out=[opened.get("result",{}),closed.get("result",{})]
    canary_ref.set({"status":"COMPLETED","orders":orders_out,"completedAt":datetime.now(timezone.utc)},merge=True)
    strategy_ref.set({"canaryValidated":True,"liveReady":True,"phase":"LIVE_READY","updatedAt":datetime.now(timezone.utc)},merge=True)
    return {"completed":True,"replayed":False,"symbol":symbol,"notionalUsd":request.notional_usd,"orders":orders_out,
        "message":"Open, werkelijke fill en volledige close zijn door Aster bevestigd."}


@app.post("/v1/me/aster/strategy2/start")
def start_aster_strategy2(request: AsterStrategyStartRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not request.confirm: raise HTTPException(422,"Persoonlijke bevestiging ontbreekt")
    try: settings=MultiBbConfig.from_mapping(request.settings)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    uid=str(user["uid"]); ref=aster_strategy2_reference(uid); existing=ref.get().to_dict() or {}
    if settings.mode=="live":
        if not bool(existing.get("liveReady")) or not bool(existing.get("canaryValidated")):
            raise HTTPException(423,"Multi BB is nog niet LIVE READY; voer eerst readiness en canary uit")
        if os.getenv("ASTER_STRATEGY2_LIVE_ENABLED","false").lower()!="true": raise HTTPException(423,"Productie-uitvoering staat centraal uit")
    now=datetime.now(timezone.utc); version=max(int(safe_float(existing.get("configVersion"))),settings.version)
    settings=MultiBbConfig.from_mapping({**settings.public_dict(),"version":version})
    ref.set({"settings":settings.public_dict(),"phase":"START_PENDING" if settings.mode=="live" else "PAPER_RUNNING",
        "enabled":True,"monitor":True,"pendingReopens":[],"multiBbAdoptionPending":True,"multiBbReport":{},
        "lastReason":"Strategy 2 start: verse exchange-evaluatie","startedAt":now,"updatedAt":now},merge=True)
    first=_run_aster_strategy2_tick(uid,dry_run=settings.mode!="live")
    return {"started":True,"mode":settings.mode,"firstTick":first,**aster_strategy2_public(uid)}


@app.post("/v1/me/aster/strategy2/focus/reset-cycle")
def reset_aster_strategy2_focus_cycle(request: AsterStrategy2FocusResetRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not request.confirm: raise HTTPException(422,"Bevestig volledige Focus-cycle reset expliciet")
    uid=str(user["uid"]);ref=aster_strategy2_reference(uid);raw=ref.get().to_dict() or {}
    settings=Strategy2Config.from_mapping(raw.get("settings"))
    secret=load_aster_secret(user);client=AsterV3Client(signer_address=secret.signer_address,sign_message=local_eip712_signer(secret),live_authorized=True,before_order_submit=_block_order_during_close_all(uid))
    if not client.position_mode(): raise HTTPException(409,"Focus reset vereist bevestigd Aster Hedge Mode")
    owned=[]
    for row in raw.get("ownedLegs") if isinstance(raw.get("ownedLegs"),list) else []:
        try: owned.append(owned_from_mapping(row))
        except (TypeError,ValueError): pass
    focus_owned=[x for x in owned if str(x.role).upper().startswith("FOCUS")]
    focus_keys={(x.symbol,x.side) for x in focus_owned};positions=client.position_risk();orders=client.open_orders()
    relevant_orders=[x for x in orders if (str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) in focus_keys]
    for order in relevant_orders:
        client.cancel_order(str(order.get("symbol","")).upper(),order_id=order.get("orderId"),client_order_id=str(order.get("clientOrderId","") or "") or None)
    plans=[]
    by_key={(str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()):x for x in positions if abs(safe_float(x.get("positionAmt")))>0}
    for leg in focus_owned:
        row=by_key.get((leg.symbol,leg.side))
        if not row: continue
        qty=abs(safe_float(row.get("positionAmt")));mark=safe_float(row.get("markPrice")) or safe_float(row.get("entryPrice"))
        if qty<=0 or mark<=0: raise HTTPException(409,f"{leg.symbol} {leg.side}: onbetrouwbare exchange-truth voor reset")
        rules=ContractRules.from_exchange_info(next(x for x in client.public_exchange_info().get("symbols",[]) if str(x.get("symbol","")).upper()==leg.symbol))
        close_qty=rules.market_quantity(Decimal(str(qty)),Decimal(str(mark)))
        plans.append((PairExecutionPlan(leg.symbol,close_qty,close_qty*Decimal(str(mark)),int(safe_float(row.get("leverage")) or settings.leverage),rules.tick_size,rules.market_quantity_step,rules.market_min_quantity,rules.min_notional),PositionSide(leg.side)))
    if plans:
        execute_aster_close_all(client,plans,id_prefix="s2frst-"+hashlib.sha256(f"{uid}|{int(time.time())}".encode()).hexdigest()[:12],confirm=True,explicit_loss_confirmation=True)
    fresh_positions=client.position_risk();remaining=[x for x in fresh_positions if (str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) in focus_keys and abs(safe_float(x.get("positionAmt")))>0]
    if remaining: raise HTTPException(409,"Focus reset niet voltooid: exchange toont nog Focus-exposure")
    account=client.account_information();equity=safe_float(account.get("totalMarginBalance")) or safe_float(account.get("totalWalletBalance"));now_ms=int(time.time()*1000)
    ref.set({"ownedLegs":[owned_to_mapping(x) for x in owned if not str(x.role).upper().startswith("FOCUS")],"focusLiveState":focus_state_to_mapping(FocusState()),"focusCycleState":cycle_state_to_mapping(reset_cycle(equity=equity,cycle_id="",timestamp_ms=now_ms)),"focusLiveReport":{},"updatedAt":datetime.now(timezone.utc),"lastReason":"FOCUS_CYCLE_RESET"},merge=True)
    ref.collection("audit").add({"event":"FOCUS_CYCLE_RESET","strategyId":"aster-strategy-2","timestampMs":now_ms,"closedLegs":len(plans)})
    return {"reset":True,"closedLegs":len(plans),"ordersSent":len(plans),**aster_strategy2_public(uid)}


@app.post("/v1/me/aster/strategy2/stop")
def stop_aster_strategy2(request: AsterStrategyStopRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not request.confirm: raise HTTPException(422,"Bevestig veilig stoppen")
    uid=str(user["uid"]); ref=aster_strategy2_reference(uid)
    ref.set({"enabled":False,"monitor":False,"phase":"STOPPED","pendingReopens":[],
        "lastReason":"Multi BB handmatig gestopt; er worden geen automatische orders geplaatst",
        "updatedAt":datetime.now(timezone.utc)},merge=True)
    return {"stopped":True,**aster_strategy2_public(uid)}


def _portfolio_growth_client(user:dict[str,Any],*,live:bool)->AsterV3Client:
    secret=load_aster_secret(user)
    return AsterV3Client(signer_address=secret.signer_address,
        sign_message=local_eip712_signer(secret),live_authorized=live)



def _portfolio_daily_growth(user:dict[str,Any])->dict[str,Any]:
    uid=str(user["uid"]);ref=portfolio_growth_reference(uid);now=datetime.now(timezone.utc)
    amsterdam=ZoneInfo("Europe/Amsterdam");local_now=now.astimezone(amsterdam)
    if local_now.date().isoformat()<PORTFOLIO_GROWTH_START_DATE:
        return {"reliable":False,"measurementStartDate":PORTFOLIO_GROWTH_START_DATE,"blockReason":"Meting is nog niet gestart"}
    start_local=datetime(2026,8,23,0,0,0,tzinfo=amsterdam)
    client=_portfolio_growth_client(user,live=False)
    try:
        account=client.account_information();equity,_,_,_,_=aster_account_information_values(account)
        if equity<=0:raise ValueError("Actuele portfolio/equity is niet positief")
        income=[]
        for income_type in ("TRANSFER","WELCOME_BONUS","INSURANCE_CLEAR"):
            income.extend(client.income_history(income_type=income_type,start_time=utc_ms(start_local),limit=1000))
        cumulative_cashflow=external_cashflow_since(income,utc_ms(start_local))
        today=local_now.date().isoformat();transaction=db.transaction()
        @firestore.transactional
        def update(txn:Any)->dict[str,Any]:
            doc=ref.get(transaction=txn);stored=doc.to_dict() or {};state=dict(stored.get("dailyGrowth") or {})
            if state.get("startDate")!=PORTFOLIO_GROWTH_START_DATE or safe_float(state.get("referenceEquity"))<=0:
                state={"startDate":PORTFOLIO_GROWTH_START_DATE,"referenceDate":today,"referenceEquity":equity,
                    "referenceCashflow":cumulative_cashflow,"lastObservedDate":today,"lastObservedEquity":equity,
                    "lastObservedCashflow":cumulative_cashflow,"completedReturnSum":0.0,"completedReturnCount":0}
            elif state.get("lastObservedDate")!=today:
                previous_equity=safe_float(state.get("referenceEquity"));last_equity=safe_float(state.get("lastObservedEquity"))
                reference_cashflow=safe_float(state.get("referenceCashflow"));last_cashflow=safe_float(state.get("lastObservedCashflow"))
                if previous_equity>0 and last_equity>0:
                    finished=daily_return_percentage(previous_equity,last_equity,last_cashflow-reference_cashflow)
                    previous_avg=average_daily_return(safe_float(state.get("completedReturnSum")),int(state.get("completedReturnCount",0)),finished)
                    completed_day={"date":str(state.get("lastObservedDate")),"startEquity":round(previous_equity,8),"endEquity":round(last_equity,8),
                        "usdChange":round((last_equity-(last_cashflow-reference_cashflow))-previous_equity,8),"percentage":round(finished,8),
                        "averageDailyPercentage":round(previous_avg,8),"levels":max(0,int(math.floor(finished/previous_avg+1e-12))) if previous_avg>0 and finished>0 else 0}
                    history=list(state.get("history") or []);history=[row for row in history if isinstance(row,dict) and row.get("date")!=completed_day["date"]]
                    history.append(completed_day);state["history"]=history[-120:]
                    state["completedReturnSum"]=safe_float(state.get("completedReturnSum"))+finished
                    state["completedReturnCount"]=int(state.get("completedReturnCount",0))+1
                    state["referenceEquity"]=last_equity;state["referenceCashflow"]=last_cashflow
                    state["referenceDate"]=str(state.get("lastObservedDate"))
            state["lastObservedDate"]=today;state["lastObservedEquity"]=equity;state["lastObservedCashflow"]=cumulative_cashflow
            today_pct=daily_return_percentage(safe_float(state.get("referenceEquity")),equity,cumulative_cashflow-safe_float(state.get("referenceCashflow")))
            completed_count=int(state.get("completedReturnCount",0));completed_sum=safe_float(state.get("completedReturnSum"))
            average_pct=average_daily_return(completed_sum,completed_count,today_pct)
            state["updatedAt"]=now
            txn.set(ref,{"dailyGrowth":state},merge=True)
            today_usd=(equity-(cumulative_cashflow-safe_float(state.get("referenceCashflow"))))-safe_float(state.get("referenceEquity"))
            today_levels=max(0,int(math.floor(today_pct/average_pct+1e-12))) if average_pct>0 and today_pct>0 else 0
            history=list(state.get("history") or [])
            return {"reliable":True,"todayPercentage":round(today_pct,8),"todayUsd":round(today_usd,8),"todayLevels":today_levels,
                "averageDailyPercentage":round(average_pct,8),"measuredDays":completed_count+1,"measurementStartDate":PORTFOLIO_GROWTH_START_DATE,
                "referenceDate":state.get("referenceDate"),"dayStartEquity":round(safe_float(state.get("referenceEquity")),8),
                "currentEquity":round(equity,8),"history":history[-120:]}
        return update(transaction)
    except Exception as exc:
        return {"reliable":False,"measurementStartDate":PORTFOLIO_GROWTH_START_DATE,
            "blockReason":f"Dagelijkse portfoliogroei niet betrouwbaar beschikbaar: {str(exc)[:180]}"}

def _portfolio_growth_estimate(user:dict[str,Any],*,persist_quote:bool=True)->dict[str,Any]:
    uid=str(user["uid"]);ref=portfolio_growth_reference(uid);stored=ref.get().to_dict() or {}
    baseline=safe_float(stored.get("baseline"));set_at=stored.get("baselineSetAt")
    if baseline<=0 or not isinstance(set_at,datetime):
        return {"setupRequired":True,"currency":"USD","reliable":False,"closeEnabled":False,
            "blockReason":"Stel eerst een persoonlijke startwaarde in"}
    client=_portfolio_growth_client(user,live=False)
    try:
        account=client.account_information();positions=client.position_risk()
        income=client.income_history(start_time=utc_ms(set_at),limit=1000)
        fees=client.fee_details("BTC_USDT")
        taker=abs(safe_float(fees.get("realTakerFee",fees.get("originalTakerFee"))))
        if taker>0.05:taker/=100
        if taker<=0 or taker>0.05:raise ValueError("Aster-takerfee is niet betrouwbaar bevestigd")
        slippage=safe_float(os.getenv("ASTER_CLOSE_ALL_SLIPPAGE_RATE","0.001"))
        if slippage<=0 or slippage>0.05:raise ValueError("Slippagebuffer is niet conservatief geconfigureerd")
        equity,_,_,_,_=aster_account_information_values(account)
        cashflow=external_cashflow_since(income,utc_ms(set_at))
        estimate=estimate_close_value(baseline=baseline,exchange_equity=equity,positions=positions,
            external_cashflow=cashflow,taker_fee_rate=taker,slippage_rate=slippage,
            other_costs=0,equity_includes_unrealized=("totalMarginBalance" in account and "totalUnrealizedProfit" in account),
            funding_in_equity=("totalMarginBalance" in account and "totalWalletBalance" in account),data_fresh=True,
            cashflow_complete=len(income)<1000)
        payload={"setupRequired":False,"currency":"USD",**estimate.public(),"generatedAt":datetime.now(timezone.utc).isoformat(),
            "evidence":{"equitySource":"totalMarginBalance","unrealizedIncluded":True,"fundingTreatment":"settled funding included in wallet/equity; no not-yet-due funding deducted",
                "cashflowRows":len(income),"feeRate":taker,"slippageRate":slippage}}
    except Exception as exc:
        return {"setupRequired":False,"currency":"USD","baseline":baseline,"reliable":False,"closeEnabled":False,
            "blockReason":f"Actuele exchangegegevens niet betrouwbaar: {str(exc)[:180]}"}
    if persist_quote:
        quote_id=python_secrets.token_urlsafe(24);expires=datetime.now(timezone.utc)+timedelta(seconds=45)
        ref.collection("quotes").document(quote_id).set({"uid":uid,"payload":payload,"expiresAt":expires,"createdAt":datetime.now(timezone.utc)})
        payload={**payload,"quoteId":quote_id,"quoteExpiresAt":expires.isoformat()}
    return payload



@app.get("/v1/me/aster/portfolio-growth/daily")
def get_aster_portfolio_daily_growth(user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    return _portfolio_daily_growth(user)

@app.get("/v1/me/aster/portfolio-growth")
def get_aster_portfolio_growth(user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    return _portfolio_growth_estimate(user)


@app.post("/v1/me/aster/portfolio-growth/baseline")
def set_aster_portfolio_growth_baseline(request:PortfolioGrowthBaselineRequest,
    user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    if not request.confirm:raise HTTPException(422,"Bevestig de eerste startwaarde expliciet")
    uid=str(user["uid"]);ref=portfolio_growth_reference(uid);transaction=db.transaction();now=datetime.now(timezone.utc)
    @firestore.transactional
    def save(txn):
        current=ref.get(transaction=txn)
        if current.exists and safe_float((current.to_dict() or {}).get("baseline"))>0:
            raise HTTPException(409,"De startwaarde bestaat al; gebruik de expliciete resetprocedure")
        data={"uid":uid,"baseline":request.amount,"currency":"USD","baselineSetAt":now,"baselineSource":"OWNER_INITIAL",
            "updatedAt":now}
        txn.set(ref,data,merge=True);txn.set(ref.collection("audit").document(),{"event":"BASELINE_INITIALIZED","uid":uid,
            "newBaseline":request.amount,"currency":"USD","actorUid":uid,"timestamp":now})
    save(transaction)
    return {"saved":True,**_portfolio_growth_estimate(user)}


@app.post("/v1/me/aster/portfolio-growth/reset")
def reset_aster_portfolio_growth_baseline(request:PortfolioGrowthResetRequest,
    user:dict[str,Any]=Depends(authenticated_user))->dict[str,Any]:
    if not request.confirm:raise HTTPException(422,"Bevestig de handmatige reset expliciet")
    uid=str(user["uid"]);ref=portfolio_growth_reference(uid);transaction=db.transaction();now=datetime.now(timezone.utc)
    @firestore.transactional
    def reset(txn):
        current=ref.get(transaction=txn).to_dict() or {};old=safe_float(current.get("baseline"))
        txn.set(ref,{"uid":uid,"baseline":request.amount,"currency":"USD","baselineSetAt":now,
            "baselineSource":"OWNER_RESET","updatedAt":now},merge=True)
        txn.set(ref.collection("audit").document(),{"event":"BASELINE_RESET","uid":uid,"oldBaseline":old,
            "newBaseline":request.amount,"reason":request.reason,"actorUid":uid,"timestamp":now})
    reset(transaction)
    return {"reset":True,**_portfolio_growth_estimate(user)}


@app.post("/v1/me/aster/automation/close-all")
def close_all_aster_strategy(
    request: AsterCloseAllRequest,
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(422, "Bevestig Alles sluiten expliciet")
    if os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "false").lower() != "true":
        raise HTTPException(423, "Aster productie-uitvoering staat centraal uit")
    uid=str(user["uid"]);growth=portfolio_growth_reference(uid);quote_ref=growth.collection("quotes").document(request.quote_id)
    action_hash=hashlib.sha256(f"{uid}:{request.idempotency_key}".encode()).hexdigest();action_ref=growth.collection("actions").document(action_hash)
    transaction=db.transaction();now=datetime.now(timezone.utc);lock_token=python_secrets.token_hex(16)
    @firestore.transactional
    def reserve(txn):
        existing=action_ref.get(transaction=txn)
        if existing.exists:return (existing.to_dict() or {}).get("status","UNKNOWN")
        quote=quote_ref.get(transaction=txn);quote_data=quote.to_dict() or {}
        if not quote.exists or quote_data.get("uid")!=uid:raise HTTPException(409,"De persoonlijke sluitpreview bestaat niet")
        expires_at=quote_data.get("expiresAt")
        if isinstance(expires_at,datetime) and expires_at.tzinfo is None:
            expires_at=expires_at.replace(tzinfo=timezone.utc)
        if not isinstance(expires_at,datetime) or expires_at<=now:
            raise HTTPException(409,"De sluitpreview is verlopen; vernieuw eerst de actuele berekening")
        preview=quote_data.get("payload") if isinstance(quote_data.get("payload"),dict) else {}
        if not preview.get("closeEnabled") or not preview.get("reliable"):
            raise HTTPException(409,"De bewaarde sluitpreview is niet aantoonbaar positief en betrouwbaar")
        lock=(growth.get(transaction=txn).to_dict() or {}).get("closeLock")
        if isinstance(lock,dict) and lock.get("active"):raise HTTPException(409,"Voor dit account loopt al een sluitactie")
        txn.set(action_ref,{"uid":uid,"status":"RESERVED","quoteId":request.quote_id,"preview":preview,"createdAt":now})
        txn.set(growth,{"closeLock":{"active":True,"token":lock_token,"actionId":action_hash,"until":now+timedelta(hours=24)}},merge=True)
        pause={"enabled":False,"monitor":True,"closeAllPause":True,"phase":"CLOSING_ALL","lastReason":"Persoonlijk Alles sluiten actief","updatedAt":now}
        txn.set(aster_strategy2_reference(uid),pause,merge=True)
        return "RESERVED"
    status=reserve(transaction)
    if status!="RESERVED":return {"actionId":action_hash,"status":status,"duplicate":True}
    client=_portfolio_growth_client(user,live=True);submitted=[]
    try:
        open_orders=client.open_orders();unknown=[row for row in open_orders if is_exposure_order(row) is None]
        if unknown:raise RuntimeError("Open order(s) kunnen niet veilig als instap of bescherming worden geclassificeerd")
        for order in [row for row in open_orders if is_exposure_order(row) is True]:
            client.cancel_order(str(order.get("symbol","")),order_id=order.get("orderId"),client_order_id=order.get("clientOrderId"))
        preview=_portfolio_growth_estimate(user,persist_quote=False)
        if not preview.get("reliable") or not preview.get("closeEnabled") or safe_float(preview.get("difference"))<=0:
            raise RuntimeError("De opnieuw berekende netto sluitwaarde is niet meer betrouwbaar positief")
        positions=[x for x in client.position_risk() if abs(safe_float(x.get("positionAmt")))>0]
        for index,row in enumerate(positions,1):
            symbol=str(row.get("symbol","")).upper();qty=abs(Decimal(str(row.get("positionAmt"))));mark=safe_float(row.get("markPrice"))
            if not symbol or qty<=0 or mark<=0:raise RuntimeError("Positie bevat geen betrouwbare sluitgegevens")
            plan=PairExecutionPlan(symbol,qty,qty*Decimal(str(mark)),max(1,int(safe_float(row.get("leverage")) or 1)))
            result=execute_aster_leg(client,plan,side=PositionSide(str(row.get("positionSide","")).upper()),action="CLOSE",
                id_prefix=f"tm-ca-{action_hash[:14]}-{index}",confirm=True,manual_loss_confirmation=True)
            submitted.append(result)
        remaining=[x for x in client.position_risk() if abs(safe_float(x.get("positionAmt")))>0]
        if remaining:
            detail=", ".join(f"{str(x.get('symbol','?'))}:{str(x.get('positionSide','?'))}:{abs(safe_float(x.get('positionAmt'))):g}" for x in remaining[:20])
            raise RuntimeError(f"Aster bevestigt nog {len(remaining)} open positie(s) [{detail}]; geen nieuwe basis opgeslagen")
        for order in client.open_orders():
            client.cancel_order(str(order.get("symbol","")),order_id=order.get("orderId"),client_order_id=order.get("clientOrderId"))
        remaining_orders=client.open_orders()
        if remaining_orders:
            detail=", ".join(f"{str(x.get('symbol','?'))}:{str(x.get('orderId',x.get('clientOrderId','?')))}" for x in remaining_orders[:20])
            raise RuntimeError(f"Aster bevestigt nog {len(remaining_orders)} open order(s) [{detail}]; geen nieuwe basis opgeslagen")
        final_account=client.account_information();final_equity=aster_account_information_values(final_account)[0]
        if final_equity<=0:raise RuntimeError("De werkelijk gerealiseerde eindwaarde is niet betrouwbaar bevestigd")
        finish=db.transaction();finished_at=datetime.now(timezone.utc)
        @firestore.transactional
        def complete(txn):
            current=growth.get(transaction=txn).to_dict() or {};old=safe_float(current.get("baseline"));lock=current.get("closeLock") or {}
            if lock.get("token")!=lock_token:raise RuntimeError("Accountlock is tijdens afronding gewijzigd")
            txn.set(growth,{"baseline":final_equity,"baselineSetAt":finished_at,"baselineSource":"CONFIRMED_CLOSE_ALL",
                "updatedAt":finished_at,"closeLock":{"active":False,"token":"","actionId":action_hash,"releasedAt":finished_at}},merge=True)
            actual_fees=sum(abs(safe_float(((item.get("result") or {}) if isinstance(item,dict) else {}).get("commission"))) for item in submitted)
            audit={"event":"CLOSE_ALL_CONFIRMED_FLAT","uid":uid,"actionId":action_hash,"oldBaseline":old,"newBaseline":final_equity,
                "estimatedDifference":safe_float(preview.get("difference")),"expectedFees":safe_float(preview.get("expectedFees")),
                "confirmedReportedFees":actual_fees,"slippageBuffer":safe_float(preview.get("slippageBuffer")),
                "ordersSubmitted":len(submitted),"timestamp":finished_at}
            txn.set(growth.collection("audit").document(),audit);txn.set(action_ref,{"status":"COMPLETED","result":audit,"completedAt":finished_at},merge=True)
        complete(finish)
        return {"actionId":action_hash,"status":"COMPLETED","closedPositions":len(submitted),"newBaseline":final_equity,
            "botPaused":True,"message":"Alle posities en orders zijn exchange-bevestigd weg; het account blijft bewust gepauzeerd."}
    except Exception as exc:
        action_ref.set({"status":"PARTIAL_FAIL_CLOSED" if submitted else "FAILED_BEFORE_CLOSE","submitted":len(submitted),
            "reason":str(exc)[:500],"updatedAt":datetime.now(timezone.utc)},merge=True)
        raise HTTPException(409,f"Alles sluiten is fail-closed gestopt; account blijft gepauzeerd: {str(exc)[:300]}") from exc


@app.get("/v1/me/aster/positions/profitable-close-preview")
def preview_profitable_aster_positions(
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Return a fresh, UID-scoped Aster preview; this endpoint never trades."""
    client = _portfolio_growth_client(user, live=False)
    try:
        preview = profit_preview(client.position_risk())
    except Exception as exc:
        raise HTTPException(502, "Actuele Aster-winstposities konden niet betrouwbaar worden gecontroleerd") from exc
    return {**preview, "generatedAt": datetime.now(timezone.utc).isoformat(), "reliable": True}


@app.post("/v1/me/aster/positions/close-profitable")
def close_profitable_aster_positions(
    request: AsterProfitableCloseRequest,
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Close only still-profitable Aster legs after explicit user confirmation."""
    if not request.confirm:
        raise HTTPException(422, "Bevestiging voor winstposities sluiten ontbreekt")
    if os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "false").lower() != "true":
        raise HTTPException(423, "Aster productie-uitvoering staat centraal uit")

    uid = str(user["uid"])
    action_hash = hashlib.sha256(f"{uid}:{request.idempotency_key}".encode()).hexdigest()
    action_ref = user_reference(user).collection("asterBulkProfitCloseIntents").document(action_hash)
    try:
        action_ref.create({
            "uid": uid, "status": "prepared", "minimumProfitUsd": MINIMUM_PROFIT_USD,
            "createdAt": datetime.now(timezone.utc),
        })
    except google_exceptions.AlreadyExists:
        existing = action_ref.get().to_dict() or {}
        if existing.get("status") == "completed":
            return {**(existing.get("result") or {}), "duplicate": True}
        raise HTTPException(409, "Deze winstsluiting wordt al verwerkt; er worden geen dubbele orders geplaatst")

    strategy_ref = aster_strategy2_reference(uid)
    queue_token = _acquire_strategy2_queue_lease(strategy_ref)
    if not queue_token:
        action_ref.set({"status": "blocked", "reason": "strategy2_order_busy", "updatedAt": datetime.now(timezone.utc)}, merge=True)
        raise HTTPException(409, "Strategy 2 verwerkt nog een order; probeer het zo opnieuw")

    closed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    try:
        client = _portfolio_growth_client(user, live=True)
        initial = profitable_positions(client.position_risk())
        for index, candidate in enumerate(initial, 1):
            symbol = candidate["symbol"]
            side = candidate["side"]
            # Re-read exchange truth immediately before every order. A position
            # that crossed below the positive threshold is skipped, never closed.
            live_rows = client.position_risk()
            current = next((row for row in live_rows
                if str(row.get("symbol", "")).upper() == symbol
                and str(row.get("positionSide", "")).upper() == side
                and abs(safe_float(row.get("positionAmt"))) > 0), None)
            if current is None:
                skipped.append({**candidate, "reason": "positie bestaat niet meer"})
                continue
            current_profit = position_profit(current)
            live_quantity = abs(safe_float(current.get("positionAmt")))
            mark = safe_float(current.get("markPrice"))
            if current_profit is None or current_profit < MINIMUM_PROFIT_USD or live_quantity <= 0 or mark <= 0:
                skipped.append({**candidate, "currentProfitUsd": current_profit, "reason": "niet langer minimaal $0,50 groen"})
                continue
            try:
                plan = PairExecutionPlan(
                    symbol, Decimal(str(live_quantity)), Decimal(str(live_quantity * mark)),
                    max(1, int(safe_float(current.get("leverage")) or 1)),
                )
                result = execute_aster_leg(
                    client, plan, side=PositionSide(side), action="CLOSE",
                    id_prefix=f"tm-profit-{action_hash[:12]}-{index}", confirm=True,
                    manual_loss_confirmation=True,
                )
                tolerance = max(1e-12, live_quantity * 1e-9)
                remaining = next((row for row in client.position_risk()
                    if str(row.get("symbol", "")).upper() == symbol
                    and str(row.get("positionSide", "")).upper() == side
                    and abs(safe_float(row.get("positionAmt"))) > tolerance), None)
                if remaining is not None:
                    raise RuntimeError("Aster heeft de volledige sluiting nog niet bevestigd")
                closed.append({
                    "symbol": symbol, "side": side, "closedSize": live_quantity,
                    "profitAtSubmitUsd": current_profit, "order": result,
                })
            except Exception as exc:
                failed.append({"symbol": symbol, "side": side, "reason": str(exc)[:240]})

        result = {
            "closedCount": len(closed), "skippedCount": len(skipped), "failedCount": len(failed),
            "profitAtSubmitUsd": round(sum(item["profitAtSubmitUsd"] for item in closed), 8),
            "closed": closed, "skipped": skipped, "failed": failed,
            "minimumProfitUsd": MINIMUM_PROFIT_USD,
            "message": f"{len(closed)} winstpositie(s) gesloten · {len(skipped)} overgeslagen · {len(failed)} mislukt",
        }
        action_ref.set({"status": "completed", "result": result, "completedAt": datetime.now(timezone.utc)}, merge=True)
        strategy_ref.collection("audit").document().set({
            "event": "BULK_PROFIT_CLOSE_COMPLETED", "uid": uid, "actionId": action_hash,
            "closedCount": len(closed), "skippedCount": len(skipped), "failedCount": len(failed),
            "profitAtSubmitUsd": result["profitAtSubmitUsd"], "timestamp": datetime.now(timezone.utc),
        })
        return {**result, "duplicate": False}
    except HTTPException:
        raise
    except Exception as exc:
        action_ref.set({
            "status": "PARTIAL_FAIL_CLOSED" if closed else "FAILED_BEFORE_CLOSE",
            "reason": str(exc)[:500], "updatedAt": datetime.now(timezone.utc),
        }, merge=True)
        raise HTTPException(502, "Winstsluiting is veilig gestopt; onbekende posities worden niet opnieuw besteld") from exc
    finally:
        _release_strategy2_queue_lease(strategy_ref, queue_token)


@app.post("/v1/me/aster/positions/{symbol}/close")
def close_one_aster_position(
    symbol: str, request: AsterManualCloseRequest,
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Close exactly one still-matching Aster hedge leg, never increasing risk."""
    if not request.confirm:
        raise HTTPException(422, "Bevestiging voor volledig market sluiten ontbreekt")
    if os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "false").lower() != "true":
        raise HTTPException(423, "Aster productie-uitvoering staat centraal uit")
    normalized_symbol = symbol.upper()
    uid = str(user["uid"])
    intent_hash = hashlib.sha256(f"{uid}:{request.idempotency_key}".encode()).hexdigest()
    intent_ref = user_reference(user).collection("asterManualCloseIntents").document(intent_hash)
    try:
        intent_ref.create({
            "status": "prepared", "symbol": normalized_symbol, "side": request.side,
            "expectedQuantity": request.expected_quantity, "createdAt": datetime.now(timezone.utc),
        })
    except google_exceptions.AlreadyExists as exc:
        raise HTTPException(409, "Deze sluitopdracht is al ontvangen; er wordt geen tweede order geplaatst") from exc

    secret = load_aster_secret(user)
    client = AsterV3Client(
        signer_address=secret.signer_address, sign_message=local_eip712_signer(secret), live_authorized=True,
        before_order_submit=_block_order_during_close_all(uid),
    )
    try:
        live_rows = client.position_risk()
        position = next((row for row in live_rows
            if str(row.get("symbol", "")).upper() == normalized_symbol
            and str(row.get("positionSide", "")).upper() == request.side
            and abs(safe_float(row.get("positionAmt"))) > 0), None)
        if position is None:
            raise HTTPException(409, "De geselecteerde positie bestaat niet meer; actuele posities worden opnieuw opgehaald")
        live_quantity = abs(safe_float(position.get("positionAmt")))
        tolerance = max(1e-12, request.expected_quantity * 1e-9)
        if abs(live_quantity - request.expected_quantity) > tolerance:
            raise HTTPException(409, "De positiegrootte is gewijzigd; controleer de actuele positie en bevestig opnieuw")
        mark = safe_float(position.get("markPrice"))
        if mark <= 0:
            raise HTTPException(409, "Aster gaf geen betrouwbare actuele marktprijs; sluiten is gestopt")
        plan = PairExecutionPlan(
            normalized_symbol, Decimal(str(live_quantity)), Decimal(str(live_quantity * mark)),
            max(1, int(safe_float(position.get("leverage")) or 1)),
        )
        id_prefix = f"tm-manual-{intent_hash[:18]}"
        result = execute_aster_leg(
            client, plan, side=PositionSide(request.side), action="CLOSE", id_prefix=id_prefix,
            confirm=True, manual_loss_confirmation=True,
        )
        remaining = next((row for row in client.position_risk()
            if str(row.get("symbol", "")).upper() == normalized_symbol
            and str(row.get("positionSide", "")).upper() == request.side
            and abs(safe_float(row.get("positionAmt"))) > tolerance), None)
        if remaining is not None:
            raise HTTPException(502, "Aster heeft de volledige sluiting nog niet bevestigd; er wordt niet opnieuw besteld")
        intent_ref.set({"status": "confirmed_closed", "result": result, "completedAt": datetime.now(timezone.utc)}, merge=True)
        return {"closed": True, "symbol": normalized_symbol, "side": request.side, "closedSize": live_quantity}
    except HTTPException as exc:
        intent_ref.set({"status": "failed_closed", "detail": str(exc.detail), "updatedAt": datetime.now(timezone.utc)}, merge=True)
        raise
    except Exception as exc:
        intent_ref.set({"status": "unknown_fail_closed", "updatedAt": datetime.now(timezone.utc)}, merge=True)
        raise HTTPException(502, "Sluitstatus is niet betrouwbaar bevestigd; er wordt niet opnieuw besteld") from exc


@app.post("/v1/me/aster/simulate")
def simulate_aster_multi_pair(
    request: AsterDryRunRequest,
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Exercise the personal Aster connection and plan 2 hedge legs per pair.

    This endpoint deliberately has no call to submit_order_once and cannot place
    or close an order. Signed account reads still verify the complete personal
    Secret Manager -> EIP-712 -> Aster connection.
    """
    secret = load_aster_secret(user)
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
        tickers = client.ticker_prices()
    except (AsterApiError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    if not hedge_mode:
        raise HTTPException(409, "Aster Hedge Mode staat niet aan; 5 LONG + 5 SHORT kan daarom niet veilig worden gepland")

    ticker_map = {
        str(item.get("symbol", "")).upper(): safe_float(item.get("price"))
        for item in tickers
        if safe_float(item.get("price")) > 0
    }
    symbol_rows = {
        str(item.get("symbol", "")).upper(): item
        for item in exchange_info.get("symbols", [])
        if isinstance(item, dict) and str(item.get("status", "")).upper() == "TRADING"
    }
    preferred = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    selected = [symbol for symbol in preferred if symbol in symbol_rows and symbol in ticker_map]
    selected.extend(
        symbol for symbol in symbol_rows
        if symbol in ticker_map and symbol not in selected
    )
    selected = selected[:request.pair_count]
    if len(selected) != request.pair_count:
        raise HTTPException(409, f"Aster leverde slechts {len(selected)} bruikbare markten voor deze dry-run")

    plans: list[dict[str, Any]] = []
    for pair_index, symbol in enumerate(selected, start=1):
        rules = ContractRules.from_exchange_info(symbol_rows[symbol])
        price = ticker_map[symbol]
        step = rules.market_quantity_step
        requested_quantity = request.notional_per_leg_usd / price
        minimum_quantity = max(rules.market_min_quantity, rules.min_quantity)
        if rules.min_notional > 0 and step > 0:
            minimum_steps = math.ceil(float(rules.min_notional) / price / float(step))
            minimum_quantity = max(minimum_quantity, step * minimum_steps)
        if step > 0:
            requested_steps = max(1, math.ceil(requested_quantity / float(step)))
            requested_quantity = float(step * requested_steps)
        quantity = rules.market_quantity(max(float(minimum_quantity), requested_quantity), price)
        for side in (PositionSide.LONG, PositionSide.SHORT):
            intent = AsterOrderIntent(
                f"tm-dry-{pair_index}-{side.value.lower()}", symbol, side, quantity, "OPEN",
            )
            payload = build_hedge_order_payload(
                intent, hedge_mode_confirmed=True, risk_approved=True,
            )
            plans.append({
                "symbol": symbol,
                "positionSide": side.value,
                "side": payload["side"],
                "quantity": payload["quantity"],
                "referencePrice": price,
                "plannedNotionalUsd": round(float(quantity) * price, 4),
                "clientOrderId": payload["newClientOrderId"],
                "submitted": False,
            })

    usdt = next((item for item in balances if str(item.get("asset", "")).upper() == "USDT"), {})
    return {
        "status": "passed",
        "dryRun": True,
        "ordersSubmitted": 0,
        "pairCount": len(selected),
        "plannedPositions": len(plans),
        "plannedLong": sum(item["positionSide"] == "LONG" for item in plans),
        "plannedShort": sum(item["positionSide"] == "SHORT" for item in plans),
        "hedgeMode": hedge_mode,
        "signedAccountReads": 5,
        "marketDataReads": 2,
        "availableBalance": safe_float(usdt.get("availableBalance")),
        "existingPositions": sum(abs(safe_float(item.get("positionAmt"))) > 0 for item in positions),
        "existingOpenOrders": len(open_orders),
        "leverageBracketRows": len(brackets),
        "pairs": selected,
        "plans": plans,
        "message": "Alle verbindingen en 10 orderplannen zijn gecontroleerd; er is niets naar Aster verzonden.",
    }


@app.put("/v1/me/mexc/live")
def set_mexc_live(
    request: MexcLiveToggleRequest,
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    if request.enabled:
        require_verified_email(user)
    if request.enabled and not request.confirm:
        raise HTTPException(422, "Bevestig expliciet dat REAL MONEY wordt ingeschakeld")
    status = inspect_mexc(load_mexc_credentials(user))
    if request.enabled and not status["liveReady"]:
        raise HTTPException(409, "MEXC preflight is niet volledig geslaagd")
    enabled = bool(request.enabled)
    user_reference(user).collection("executionControls").document("mexc").set({
        "liveEnabled": enabled,
        "updatedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {
        **status,
        "liveEnabled": enabled,
        "ordersEnabled": enabled and os.getenv("MEXC_LIVE_EXECUTION_ENABLED", "false").lower() == "true",
    }


@app.post("/v1/me/mexc/canary")
def place_mexc_canary(
    request: MexcCanaryRequest,
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Place at most one Cross 200x BTC long canary under a hard USD cap."""
    if request.leverage != 200:
        raise HTTPException(422, "Deze strategie gebruikt uitsluitend het vaste Cross 200× profiel")
    if not request.confirm:
        raise HTTPException(422, "Bevestig de echte MEXC-canary expliciet")
    if os.getenv("MEXC_LIVE_EXECUTION_ENABLED", "false").lower() != "true":
        raise HTTPException(409, "MEXC-orderuitvoering staat centraal vergrendeld")
    control_ref = user_reference(user).collection("executionControls").document("mexc")
    if not bool((control_ref.get().to_dict() or {}).get("liveEnabled", False)):
        raise HTTPException(409, "Activeer REAL MONEY eerst via de accountpreflight")

    credentials = load_mexc_credentials(user)
    status = inspect_mexc(credentials)
    if not status["liveReady"]:
        raise HTTPException(409, "MEXC-accountpreflight is niet meer geldig")
    if status["openBtcPositions"] != 0:
        raise HTTPException(409, "Canary geweigerd: er bestaat al een BTC-positie")

    key_hash = hashlib.sha256(f"{user['uid']}:{request.idempotency_key}".encode("utf-8")).hexdigest()
    canary_ref = user_reference(user).collection("mexcCanaries").document(key_hash)
    existing = canary_ref.get().to_dict() or {}
    existing_action = canary_existing_action(existing.get("status"))
    if existing_action == "replay":
        return {**existing, "replayed": True}
    if existing_action == "block":
        raise HTTPException(409, "Eerdere canary heeft een onzekere status; handmatige controle vereist")

    client = MexcClient(credentials)
    try:
        contract = client.contract_detail("BTC_USDT")
        ticker = client.ticker("BTC_USDT")
        price = safe_float(ticker.get("lastPrice", ticker.get("last", ticker.get("fairPrice"))))
        volume, actual_notional = volume_for_notional(request.maximum_notional_usd, price, contract)
    except MexcApiError as exc:
        raise HTTPException(409, str(exc)) from exc
    # MEXC Adaptive DCA uses one fixed execution profile for every leg.
    if status["maximumLeverage"] < 200:
        raise HTTPException(409, "MEXC staat het vaste Cross 200× profiel voor BTC_USDT niet toe")
    leverage = 200
    open_type = 2  # Cross margin
    external_oid = f"tmc_{key_hash[:24]}"
    canary_ref.set({
        "status": "prepared",
        "symbol": "BTC_USDT",
        "side": "long",
        "maximumNotionalUsd": request.maximum_notional_usd,
        "actualNotionalUsd": actual_notional,
        "volume": volume,
        "leverage": leverage,
        "marginMode": "cross",
        "externalOid": external_oid,
        "createdAt": datetime.now(timezone.utc),
    })
    try:
        result, recovered = place_canary_once(
            client, symbol="BTC_USDT", volume=volume, external_oid=external_oid,
            leverage=leverage, open_type=open_type,
        )
    except MexcCanaryUncertain as exc:
        canary_ref.set({
            "status": "uncertain",
            "failure": str(exc),
            "updatedAt": datetime.now(timezone.utc),
        }, merge=True)
        raise HTTPException(409, str(exc)) from exc
    order_id = str(result.get("orderId", ""))
    canary_ref.set({
        "status": "accepted",
        "orderId": order_id,
        "acceptedAt": datetime.now(timezone.utc),
    }, merge=True)
    return {
        "status": "accepted",
        "orderId": order_id,
        "externalOid": external_oid,
        "symbol": "BTC_USDT",
        "side": "long",
        "volume": volume,
        "actualNotionalUsd": actual_notional,
        "maximumNotionalUsd": request.maximum_notional_usd,
        "leverage": leverage,
        "marginMode": "cross",
        "recovered": recovered,
        "replayed": False,
    }


def _mexc_auto_state(value: dict[str, Any], equity: float) -> MexcAutoState:
    raw = value.get("state") if isinstance(value.get("state"), dict) else {}
    return MexcAutoState(
        session_start_equity=safe_float(raw.get("sessionStartEquity")) or equity,
        dca_count=max(0, int(safe_float(raw.get("dcaCount")))),
        last_dca_price=safe_float(raw.get("lastDcaPrice")),
        last_order_time=max(0, int(safe_float(raw.get("lastOrderTime")))),
        phase=str(raw.get("phase", "WAIT")),
        cycle=max(1, int(safe_float(raw.get("cycle"))) or 1),
    )


def _mexc_state_dict(state: MexcAutoState) -> dict[str, Any]:
    return {
        "sessionStartEquity": state.session_start_equity,
        "dcaCount": state.dca_count,
        "lastDcaPrice": state.last_dca_price,
        "lastOrderTime": state.last_order_time,
        "phase": state.phase,
        "cycle": state.cycle,
    }


def _mexc_position(rows: list[dict[str, Any]], side: str) -> dict[str, Any] | None:
    return next((item for item in rows if str(item.get("side")) == side), None)


def _mexc_order_volume(notional: float, price: float, contract: dict[str, Any]) -> float:
    volume, _ = volume_for_notional(notional, price, contract)
    return volume


def _execute_mexc_automation_action(
    uid: str,
    client: MexcClient,
    control_ref,
    state: MexcAutoState,
    action,
    positions: list[dict[str, Any]],
    contract: dict[str, Any],
    price: float,
    timestamp: int,
) -> MexcAutoState:
    legs = plan_mexc_order_legs(action, positions, contract, price)

    for index, leg in enumerate(legs):
        side, volume, position_id, label = leg.side_code, leg.volume, leg.position_id, leg.label
        if volume <= 0:
            continue
        if side in {1, 3}:
            existing_position = _mexc_position(positions, "long" if side == 1 else "short")
            client.change_leverage(
                leverage=200,
                position_id=int(safe_float((existing_position or {}).get("positionId"))) or None,
                symbol="BTC_USDT",
                position_type=1 if side == 1 else 2,
                open_type=2,
            )
        fingerprint = hashlib.sha256(f"{uid}:{state.cycle}:{timestamp}:{action.kind}:{index}:{side}:{volume}".encode()).hexdigest()
        journal = control_ref.collection("orders").document(fingerprint)
        existing = journal.get().to_dict() or {}
        if existing.get("status") in {"accepted", "filled"}:
            continue
        if existing.get("status") == "uncertain":
            raise MexcCanaryUncertain("Eerdere automatische orderstatus is onzeker; handmatige controle vereist")
        external_oid = f"tma_{fingerprint[:24]}"
        journal.set({
            "status": "prepared", "cycle": state.cycle, "action": action.kind,
            "leg": label, "sideCode": side, "volume": volume,
            "targetNotional": action.target_notional, "externalOid": external_oid,
            "marketPrice": price, "signalTimestamp": timestamp,
            "dcaIndex": state.dca_count + 1 if action.kind == "ADD_LONG" else 0,
            "createdAt": datetime.now(timezone.utc),
        })
        try:
            result, recovered = place_order_once(
                client, symbol="BTC_USDT", volume=volume, side=side,
                external_oid=external_oid, position_id=position_id,
            )
        except MexcCanaryUncertain as exc:
            journal.set({"status": "uncertain", "failure": str(exc), "updatedAt": datetime.now(timezone.utc)}, merge=True)
            raise
        journal.set({
            "status": "accepted", "orderId": str(result.get("orderId", "")),
            "recovered": recovered, "acceptedAt": datetime.now(timezone.utc),
        }, merge=True)

    if action.kind == "OPEN_LONG":
        return MexcAutoState(state.session_start_equity, 0, price, timestamp, "LONG", state.cycle)
    if action.kind == "ADD_LONG":
        return MexcAutoState(state.session_start_equity, state.dca_count + 1, price, timestamp, "DCA", state.cycle)
    if action.kind == "SET_HEDGE":
        return MexcAutoState(state.session_start_equity, state.dca_count, state.last_dca_price, timestamp, "PROTECT" if action.target_notional > 0 else "UNHEDGE", state.cycle)
    if action.kind in {"CLOSE_ALL", "CLOSE_SHORT"}:
        return MexcAutoState(state.session_start_equity, state.dca_count, state.last_dca_price, timestamp, "CLOSED" if action.kind == "CLOSE_ALL" else "RECOVERY", state.cycle)
    return state


def _mexc_v3_quantity(position: dict[str, Any] | None) -> float:
    row = position or {}
    return safe_float(row.get("volume")) * safe_float(row.get("contractSize"))


def _execute_mexc_v3_action(
    uid: str,
    client: MexcClient,
    control_ref,
    settings: V3Settings,
    state: V3State,
    action,
    positions: list[dict[str, Any]],
    contract: dict[str, Any],
    price: float,
    timestamp: int,
) -> V3State:
    if action.kind == "CANCEL_PENDING":
        client.cancel_all_orders(settings.symbol)
        return V3State(**{**state.__dict__, "state": "EMERGENCY_TRIGGERED", "reason": action.reason})
    if action.kind in {"FREEZE", "SAFE_WAIT", "RESCUE_WAIT", "API_ERROR", "HOLD"}:
        return apply_paper_action(settings, state, V3Account(
            wallet_balance=0, equity=1, available_margin=0, used_margin=0,
            maintenance_margin=0, margin_ratio=0, liquidation_distance=1,
        ), V3Market(timestamp, price), action) if action.kind != "FREEZE" else state

    long = _mexc_position(positions, "long")
    short = _mexc_position(positions, "short")
    if action.kind in {"OPEN_SIDE", "ADD_DCA", "OPEN_RESCUE", "EMERGENCY_HEDGE"}:
        side_code = 1 if action.side == "long" else 3
        if action.target_quantity > 0:
            contract_size = safe_float(contract.get("contractSize"))
            step = safe_float(contract.get("volUnit")) or 1.0
            volume = math.floor((action.target_quantity / contract_size) / step) * step if contract_size > 0 else 0
            if volume <= 0:
                raise ValueError("ORDER BELOW EXCHANGE MINIMUM")
        else:
            volume = _mexc_order_volume(action.target_notional, price, contract)
        existing_position = long if action.side == "long" else short
        client.change_leverage(
            leverage=settings.leverage,
            position_id=int(safe_float((existing_position or {}).get("positionId"))) or None,
            symbol=settings.symbol,
            position_type=1 if action.side == "long" else 2,
            open_type=2,
        )
        position_id = None
    elif action.kind == "CLOSE_SIDE":
        position = long if action.side == "long" else short
        if not position:
            return state
        side_code = 4 if action.side == "long" else 2
        volume = safe_float(position.get("volume"))
        position_id = int(safe_float(position.get("positionId"))) or None
    else:
        return state

    fingerprint = hashlib.sha256(
        f"v3:{uid}:{state.cycle_id}:{timestamp}:{action.kind}:{action.side}:{volume}".encode()
    ).hexdigest()
    journal = control_ref.collection("ordersV3").document(fingerprint)
    existing = journal.get().to_dict() or {}
    if existing.get("status") in {"accepted", "filled"}:
        return state
    if existing.get("status") == "uncertain":
        raise MexcCanaryUncertain("Eerdere V3-orderstatus is onzeker; geen automatische retry")
    external_oid = f"tmv3_{fingerprint[:23]}"
    journal.set({
        "status": "prepared", "cycle": state.cycle_id, "action": action.kind,
        "side": action.side, "sideCode": side_code, "volume": volume,
        "targetNotional": action.target_notional, "externalOid": external_oid,
        "marketPrice": price, "signalTimestamp": timestamp,
        "createdAt": datetime.now(timezone.utc),
    })
    try:
        result, recovered = place_order_once(
            client, symbol=settings.symbol, volume=volume, side=side_code,
            external_oid=external_oid, position_id=position_id,
        )
    except MexcCanaryUncertain as exc:
        journal.set({"status": "uncertain", "failure": str(exc), "updatedAt": datetime.now(timezone.utc)}, merge=True)
        raise
    journal.set({
        "status": "accepted", "orderId": str(result.get("orderId", "")),
        "recovered": recovered, "acceptedAt": datetime.now(timezone.utc),
    }, merge=True)
    if action.kind in {"ADD_DCA", "CLOSE_SIDE", "EMERGENCY_HEDGE"}:
        placeholder = V3Account(
            wallet_balance=0, equity=1, available_margin=0, used_margin=0,
            maintenance_margin=0, margin_ratio=0, liquidation_distance=1,
        )
        return apply_paper_action(settings, state, placeholder, V3Market(timestamp, price), action)
    return V3State(**{**state.__dict__, "last_action_time": timestamp, "reason": action.reason})


def _run_mexc_v3_tick(uid: str, *, dry_run: bool = False, ignore_monitor: bool = False,
                      settings_override: dict[str, Any] | None = None) -> dict[str, Any]:
    control_ref = mexc_automation_reference(uid)
    control = control_ref.get().to_dict() or {}
    if not ignore_monitor and not bool(control.get("monitor", False)):
        return {"uid": uid, "status": "inactive"}
    if not dry_run and bool(control.get("paused", False)):
        return {"uid": uid, "status": "paused", "reason": str(control.get("pauseReason", ""))}
    settings = V3Settings.from_dict(settings_override or control.get("settings"))
    if errors := settings.validate():
        return {"uid": uid, "status": "paused", "reason": "; ".join(errors)}
    client = MexcClient(load_mexc_credentials({"uid": uid}))
    try:
        assets = client.assets()
        raw_positions = client.open_positions(settings.symbol)
        open_orders = client.open_orders(settings.symbol)
        contract = client.contract_detail(settings.symbol)
        ticker = client.ticker(settings.symbol)
        price = safe_float(ticker.get("fairPrice", ticker.get("lastPrice", ticker.get("last"))))
        usdt = usdt_asset(assets)
        if not usdt or price <= 0:
            raise MexcApiError("MEXC account- of prijsdata ontbreekt")
        equity = safe_float(usdt.get("equity"))
        positions = normalized_positions(raw_positions, mark_price=price, contract=contract, account_equity=equity)
        long, short = _mexc_position(positions, "long"), _mexc_position(positions, "short")
        gross = safe_float((long or {}).get("notionalUsd")) + safe_float((short or {}).get("notionalUsd"))
        net = abs(safe_float((long or {}).get("notionalUsd")) - safe_float((short or {}).get("notionalUsd")))
        mmr = max(safe_float((long or short or {}).get("maintenanceMarginRate")), safe_float(contract.get("maintenanceMarginRate")))
        liquidation_fee = safe_float(contract.get("liquidationFeeRate"))
        margin_ratio = gross * (mmr + liquidation_fee) / equity if equity > 0 else 1.0
        liquidation_distance = 1.0 if net <= 0 else max(0.0, min(1.0, (equity - gross * (mmr + liquidation_fee)) / net))
        account = V3Account(
            wallet_balance=safe_float(usdt.get("availableBalance")) + safe_float(usdt.get("positionMargin")),
            equity=equity,
            available_margin=safe_float(usdt.get("availableOpen")),
            used_margin=safe_float(usdt.get("positionMargin")),
            maintenance_margin=gross * mmr,
            margin_ratio=margin_ratio,
            liquidation_distance=liquidation_distance,
            long_quantity=_mexc_v3_quantity(long), long_average=safe_float((long or {}).get("entryPrice")),
            long_notional=safe_float((long or {}).get("notionalUsd")), long_unrealized=safe_float((long or {}).get("unrealizedPnl")),
            short_quantity=_mexc_v3_quantity(short), short_average=safe_float((short or {}).get("entryPrice")),
            short_notional=safe_float((short or {}).get("notionalUsd")), short_unrealized=safe_float((short or {}).get("unrealizedPnl")),
            realized_pnl=safe_float(control.get("v3RealizedPnl")), fees=safe_float(control.get("v3Fees")),
            open_order_ids=tuple(str(item.get("orderId", "")) for item in open_orders),
            independent_rescue_account=False,
        )
        state = reconcile_v3_state(settings, v3_state_from_dict(control.get("v3State")), account)
        if protective_monitor_is_complete(
            protective_only=bool(control.get("protectiveOnly", False)),
            enabled=bool(control.get("enabled", False)),
            account=account,
        ):
            control_ref.set({
                "monitor": False,
                "lastAction": "HOLD",
                "lastReason": "Gestopt en alle BTC-posities en orders zijn gesloten",
                "lastSnapshot": {
                    "walletBalance": account.wallet_balance,
                    "equity": equity,
                    "available": account.available_margin,
                    "usedMargin": account.used_margin,
                    "maintenanceMargin": account.maintenance_margin,
                    "unrealizedPnl": 0.0,
                    "longNotional": 0.0,
                    "shortNotional": 0.0,
                    "netExposure": 0.0,
                    "marginRatio": account.margin_ratio,
                    "liquidationDistance": account.liquidation_distance,
                },
                "lastTickAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc),
            }, merge=True)
            return {"uid": uid, "status": "stopped-flat", "action": "HOLD"}
        market = V3Market(int(time.time()), price)
        action = enforce_protective_only(
            decide_v3(settings, state, account, market),
            protective_only=bool(control.get("protectiveOnly", False)) and not dry_run,
        )
        snapshot = {
            "walletBalance": account.wallet_balance, "equity": equity,
            "available": account.available_margin, "usedMargin": account.used_margin,
            "maintenanceMargin": account.maintenance_margin, "unrealizedPnl": account.long_unrealized + account.short_unrealized,
            "longNotional": account.long_notional, "shortNotional": account.short_notional,
            "netExposure": account.long_notional - account.short_notional,
            "marginRatio": account.margin_ratio, "liquidationDistance": account.liquidation_distance,
        }
        if dry_run or settings.mode == "paper":
            simulated_state = apply_paper_action(settings, state, account, market, action)
            result = {"uid": uid, "status": "simulated", "strategyVersion": settings.strategy_version,
                      "action": action.kind, "side": action.side, "reason": action.reason,
                      "targetNotional": action.target_notional, "targetQuantity": action.target_quantity,
                      "snapshot": snapshot, "state": v3_state_to_dict(simulated_state), "settings": settings.public_dict()}
            control_ref.set({"lastSimulation": result, "lastSimulationAt": datetime.now(timezone.utc)}, merge=True)
            return result
        next_state = (
            apply_paper_action(settings, state, account, market, action)
            if action.kind == "FREEZE"
            else _execute_mexc_v3_action(uid, client, control_ref, settings, state, action,
                                         positions, contract, price, market.timestamp)
        )
        control_ref.set({
            "v3State": v3_state_to_dict(next_state), "lastAction": action.kind,
            "lastReason": action.reason, "lastSnapshot": snapshot,
            "lastTickAt": datetime.now(timezone.utc), "updatedAt": datetime.now(timezone.utc),
        }, merge=True)
        return {"uid": uid, "status": "ok", "action": action.kind, "side": action.side, "reason": action.reason}
    except MexcCanaryUncertain as exc:
        control_ref.set({"paused": True, "pauseReason": str(exc), "lastTickAt": datetime.now(timezone.utc)}, merge=True)
        return {"uid": uid, "status": "paused-uncertain", "reason": str(exc)}
    except (MexcApiError, ValueError) as exc:
        control_ref.set({"lastAction": "API_ERROR", "lastReason": str(exc), "lastTickAt": datetime.now(timezone.utc)}, merge=True)
        return {"uid": uid, "status": "data-hold", "reason": str(exc)}


def _run_mexc_automation_tick(uid: str, *, dry_run: bool = False, ignore_monitor: bool = False, settings_override: dict[str, Any] | None = None) -> dict[str, Any]:
    control_ref = mexc_automation_reference(uid)
    control = control_ref.get().to_dict() or {}
    selected = settings_override or control.get("settings") or {}
    strategy_version = str(selected.get("strategyVersion", selected.get("strategy_version", "")))
    if strategy_version == "hedge_dca_v3":
        return _run_mexc_v3_tick(uid, dry_run=dry_run, ignore_monitor=ignore_monitor,
                                 settings_override=settings_override)
    if not ignore_monitor and not bool(control.get("monitor", False)):
        return {"uid": uid, "status": "inactive"}
    if not dry_run and bool(control.get("paused", False)):
        return {"uid": uid, "status": "paused", "reason": str(control.get("pauseReason", ""))}
    credentials = load_mexc_credentials({"uid": uid})
    client = MexcClient(credentials)
    settings = MexcAutoSettings.from_dict(settings_override or control.get("settings"))
    if errors := settings.validate():
        control_ref.set({"paused": True, "pauseReason": "; ".join(errors), "updatedAt": datetime.now(timezone.utc)}, merge=True)
        return {"uid": uid, "status": "paused", "reason": "; ".join(errors)}

    try:
        assets = client.assets()
        raw_positions = client.open_positions("BTC_USDT")
        open_orders = client.open_orders("BTC_USDT")
        contract = client.contract_detail("BTC_USDT")
        ticker = client.ticker("BTC_USDT")
        price = safe_float(ticker.get("fairPrice", ticker.get("lastPrice", ticker.get("last"))))
        usdt = usdt_asset(assets)
        if not usdt or price <= 0:
            raise MexcApiError("MEXC account- of prijsdata ontbreekt")
        if open_orders:
            own_pending = all(str(item.get("externalOid", "")).startswith("tma_") for item in open_orders)
            if own_pending:
                control_ref.set({"lastAction": "HOLD", "lastReason": "Wacht op openstaande TradeMentor-marktorder", "lastTickAt": datetime.now(timezone.utc)}, merge=True)
                return {"uid": uid, "status": "pending-order"}
            control_ref.set({"paused": True, "pauseReason": "Er staat een onbekende BTC-order open bij MEXC", "lastTickAt": datetime.now(timezone.utc)}, merge=True)
            return {"uid": uid, "status": "paused-external-order"}
        equity = safe_float(usdt.get("equity"))
        positions = normalized_positions(raw_positions, mark_price=price, contract=contract, account_equity=equity)
        long = _mexc_position(positions, "long")
        short = _mexc_position(positions, "short")
        state = _mexc_auto_state(control, equity)

        # Recover state from the immutable accepted-order journal if a container
        # stopped after MEXC accepted an order but before state was persisted.
        order_documents = list(control_ref.collection("orders").stream())
        accepted = []
        for document in order_documents:
            item = document.to_dict() or {}
            if item.get("status") == "accepted" and item.get("externalOid"):
                try:
                    exchange_order = client.order_by_external_id("BTC_USDT", str(item["externalOid"]))
                    order_state = int(safe_float(exchange_order.get("state")))
                    if order_state == 3:
                        item.update({
                            "status": "filled", "dealAvgPrice": safe_float(exchange_order.get("dealAvgPrice")),
                            "dealVolume": safe_float(exchange_order.get("dealVol")),
                            "takerFee": safe_float(exchange_order.get("takerFee")),
                            "profit": safe_float(exchange_order.get("profit")),
                        })
                        document.reference.set({key: item[key] for key in ("status", "dealAvgPrice", "dealVolume", "takerFee", "profit")}, merge=True)
                    elif order_state in {4, 5}:
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


def _strategy2_order_queue_enabled(raw:dict[str,Any])->bool:
    """Two-key, server-side and per-account gate; both default to off."""
    return os.getenv(QUEUE_FEATURE_FLAG,"false").lower()=="true" and bool(raw.get("orderQueueEnabled",False))


def _acquire_strategy2_queue_lease(reference)->str|None:
    """Acquire an account-scoped fenced lease without changing bot state."""
    transaction=db.transaction();token=python_secrets.token_hex(16)
    @firestore.transactional
    def acquire(txn):
        value=reference.get(transaction=txn).to_dict() or {};now=datetime.now(timezone.utc)
        lease=value.get("orderQueueLease") if isinstance(value.get("orderQueueLease"),dict) else {}
        until=lease.get("until")
        if isinstance(until,datetime):
            until=until.replace(tzinfo=timezone.utc) if until.tzinfo is None else until.astimezone(timezone.utc)
        if isinstance(until,datetime) and until>now:return None
        txn.set(reference,{"orderQueueLease":{"token":token,"until":now+timedelta(minutes=10),"acquiredAt":now}},merge=True)
        return token
    return acquire(transaction)


def _release_strategy2_queue_lease(reference,token:str)->None:
    transaction=db.transaction()
    @firestore.transactional
    def release(txn):
        value=reference.get(transaction=txn).to_dict() or {}
        lease=value.get("orderQueueLease") if isinstance(value.get("orderQueueLease"),dict) else {}
        if str(lease.get("token",""))!=token:return False
        txn.set(reference,{"orderQueueLease":{"token":"","until":datetime.now(timezone.utc),"releasedAt":datetime.now(timezone.utc)}},merge=True)
        return True
    release(transaction)


def _reserve_strategy2_queue_order(reference,scan_id:str,intent:AsterOrderIntent,
    details:dict[str,Any]|None=None,maximum_orders:int=MAX_ORDERS_PER_ACCOUNT_SCAN)->None:
    """Persist intent and consume one slot immediately before Aster submission."""
    transaction=db.transaction();now=datetime.now(timezone.utc)
    reservation_limit=max(1,min(int(maximum_orders),MAX_ORDERS_PER_ACCOUNT_SCAN))
    @firestore.transactional
    def reserve(txn):
        value=reference.get(transaction=txn).to_dict() or {}
        state=value.get("orderQueueState") if isinstance(value.get("orderQueueState"),dict) else {}
        if str(state.get("scanId",""))!=scan_id:
            raise RuntimeError("Strategy-2 scan-id veranderde tijdens orderreservering")
        used=int(safe_float(state.get("ordersUsed")))
        if used>=reservation_limit:raise Strategy2OrderBudgetExhausted(
            f"Strategy-2 accountscan heeft {reservation_limit} Aster-orders bereikt")
        current={"clientOrderId":intent.intent_id,"symbol":intent.symbol,"side":intent.position_side.value,
            "action":intent.action,"quantity":str(intent.quantity),"reservedAt":now,"scanId":scan_id}
        current.update(details or {})
        reserved=list(state.get("reservedActions",[])) if isinstance(state.get("reservedActions"),list) else []
        reserved.append(current)
        txn.set(reference,{"orderQueueState":{**state,"ordersUsed":used+1,"currentIntent":current,
            "reservedActions":reserved[-MAX_ORDERS_PER_ACCOUNT_SCAN:],"updatedAt":now}},merge=True)
    reserve(transaction)


def _reconcile_strategy2_queue_intent(uid:str,reference,raw:dict[str,Any],intent:dict[str,Any])->tuple[bool,str]:
    """Resolve a reserved intent from Aster truth without ever submitting it."""
    symbol=str(intent.get("symbol","")).upper();side=str(intent.get("side","")).upper()
    client_order_id=str(intent.get("clientOrderId",""));action=str(intent.get("action","")).upper()
    action_kind=str(intent.get("kind",action)).upper()
    slot_id=str(intent.get("slotId","")).strip();intent_cycle=str(intent.get("cycleId","")).strip()
    def recovered_role(existing_role:str="HARVEST")->str:
        if action_kind in {"FOCUS_SLOT_OPEN","FOCUS_SLOT_DCA"} and slot_id:return f"FOCUS_SLOT:{slot_id}"
        if action_kind in {"FOCUS_AIRBAG_INCREASE","FOCUS_AIRBAG_REDUCE"} and slot_id:return f"FOCUS_SLOT_AIRBAG:{slot_id}"
        if action_kind in {"FOCUS_HEDGE","FOCUS_HEDGE_CORRECTION"} and slot_id:return f"FOCUS_SLOT_HEDGE:{slot_id}"
        if action_kind in {"FOCUS_HEDGE","FOCUS_HEDGE_CORRECTION"} and side=="SHORT":return "FOCUS_HEDGE"
        if action_kind in {"OPEN_PROTECTION","PROTECTION_INCREASE"}:return "PROTECTION"
        return existing_role
    if not symbol or side not in {"LONG","SHORT"} or not client_order_id:
        return False,"Persistente intent mist betrouwbare identiteit"
    secret=load_aster_secret({"uid":uid})
    client=AsterV3Client(signer_address=secret.signer_address,sign_message=local_eip712_signer(secret),live_authorized=False)
    try:order=client.query_order(symbol,client_order_id)
    except AsterApiError as exc:
        # -2013 proves Aster has no such order. The slot remains consumed, but
        # execution may safely continue because no POST is repeated blindly.
        if "-2013" in str(exc) or "Order does not exist" in str(exc):return True,"INTENT_NOT_FOUND_BEFORE_SUBMIT"
        return False,str(exc)
    status=str(order.get("status","")).upper()
    if status in {"CANCELED","REJECTED","EXPIRED"}:return True,f"INTENT_{status}"
    if status!="FILLED":return False,f"Intentstatus is {status or 'ONBEKEND'}"
    executed_quantity=safe_float(order.get("executedQty"))
    if executed_quantity<=0:return False,"FILLED intent mist werkelijk uitgevoerde hoeveelheid"
    try:trades=paged_user_trades(client,symbol)
    except (AsterApiError,ValueError) as exc:return False,str(exc)
    order_id=str(order.get("orderId",""));matching_fills=[fill for fill in trades
        if (order_id and str(fill.get("orderId",""))==order_id) or
           str(fill.get("clientOrderId",fill.get("clientOrderID","")))==client_order_id]
    if not matching_fills:return False,"FILLED intent is nog niet betrouwbaar zichtbaar in fillhistorie"
    fill_ids=tuple(str(fill.get("id",fill.get("tradeId",""))) for fill in matching_fills
        if fill.get("id",fill.get("tradeId")) is not None)
    try:positions=client.position_risk()
    except (AsterApiError,ValueError) as exc:return False,str(exc)
    pos=active_position_map(positions);row=pos.get((symbol,side));owned=[]
    for item in raw.get("ownedLegs",[]) if isinstance(raw.get("ownedLegs"),list) else []:
        try:owned.append(owned_from_mapping(item))
        except (TypeError,ValueError):pass
    existing=next((leg for leg in owned if (leg.symbol,leg.side)==(symbol,side)),None)
    pending_reopens=list(raw.get("pendingReopens",[])) if isinstance(raw.get("pendingReopens"),list) else []
    if action=="OPEN":
        if row is None:return False,"Aster meldt FILLED OPEN maar de positie ontbreekt"
        quantity=abs(safe_float(row.get("positionAmt")));entry=safe_float(row.get("entryPrice"))
        if quantity<=0 or entry<=0:return False,"FILLED OPEN heeft geen betrouwbare positiehoeveelheid of entry"
        if existing:
            owned=[replace(leg,quantity=quantity,weighted_entry=entry,
                dca_count=leg.dca_count+(1 if action_kind=="ADD_DCA" or action_kind=="FOCUS_SLOT_DCA" else 0),
                role=recovered_role(leg.role),
                intent_ids=tuple(dict.fromkeys((*leg.intent_ids,client_order_id))),
                fill_ids=tuple(dict.fromkeys((*leg.fill_ids,*fill_ids))),last_order_at_ms=int(time.time()*1000))
                if leg==existing else leg for leg in owned]
        else:
            owned.append(OwnedLeg("aster-strategy-2","strategy2",symbol,side,intent_cycle or f"recovered-{client_order_id}",
                int(safe_float(raw.get("configVersion"))) or 1,quantity,entry,1 if action_kind=="FOCUS_SLOT_DCA" else 0,
                recovered_role(),(client_order_id,),fill_ids,(),
                int(time.time()*1000),last_order_at_ms=int(time.time()*1000)))
    elif action=="CLOSE":
        if row is None:
            owned=[leg for leg in owned if (leg.symbol,leg.side)!=(symbol,side)]
            settings=Strategy2Config.from_mapping(raw.get("settings"))
            if existing and not str(existing.role).upper().startswith("FOCUS") and bool(raw.get("enabled",False)) and settings.auto_restart:
                package=hashlib.sha256(f"{uid}|{existing.cycle_id}|{symbol}|{side}".encode()).hexdigest()[:24]
                if not any(str(item.get("packageId",""))==package for item in pending_reopens if isinstance(item,dict)):
                    pending_reopens.append({"symbol":symbol,"side":side,"closedCycleId":existing.cycle_id,
                        "packageId":package,"notional":settings.base_notional,"createdAt":datetime.now(timezone.utc),
                        "reason":"PROCESS_RESTART_AFTER_CONFIRMED_CLOSE","attempts":0,"cooldownUntilMs":0})
        elif existing:
            quantity=abs(safe_float(row.get("positionAmt")));entry=safe_float(row.get("entryPrice"))
            owned=[replace(leg,quantity=quantity,weighted_entry=entry,last_order_at_ms=int(time.time()*1000))
                if leg==existing else leg for leg in owned]
    else:return False,f"Onbekende persistente actie {action}"
    now=datetime.now(timezone.utc);batch=db.batch()
    batch.set(reference,{"ownedLegs":[owned_to_mapping(x) for x in owned],"pendingReopens":pending_reopens,"updatedAt":now},merge=True)
    batch.set(reference.collection("audit").document(),{"event":"QUEUE_INTENT_RECONCILED","symbol":symbol,"side":side,
        "action":action,"clientOrderId":client_order_id,"status":status,"timestamp":now});batch.commit()
    return True,"INTENT_FILLED_RECONCILED"


def _run_aster_strategy2_queue_scan(uid:str,*,reconcile_only:bool=False,drain_pending_only:bool=False,
    maximum_orders:int=MAX_ORDERS_PER_ACCOUNT_SCAN,management_only:bool=False,event_symbol:str="",
    event_mark_price:float|None=None)->dict[str,Any]:
    """Run one durable, account-local scan with a hard Aster request budget."""
    scan_limit=max(1,min(int(maximum_orders),MAX_ORDERS_PER_ACCOUNT_SCAN))
    # A queue scan may perform several signed Aster reads. Keep the HTTP scheduler
    # well below its platform timeout and continue remaining work next minute.
    scan_deadline=time.monotonic()+120
    ref=aster_strategy2_reference(uid);now=datetime.now(timezone.utc)
    scan_id=f"{now.strftime('%Y%m%dT%H%M%S')}-{python_secrets.token_hex(4)}"
    raw=ref.get().to_dict() or {};prior=raw.get("orderQueueState") if isinstance(raw.get("orderQueueState"),dict) else {}
    current_intent=prior.get("currentIntent") if isinstance(prior.get("currentIntent"),dict) else {}
    if not bool(raw.get("enabled",False)) and not (raw.get("ownedLegs") if isinstance(raw.get("ownedLegs"),list) else []) and not current_intent:
        return {"status":"stopped-flat","scanId":scan_id,"ordersSent":0,"ordersUsed":0,"maximumOrders":scan_limit,"actions":[]}
    if current_intent:
        reconciled,reconcile_reason=_reconcile_strategy2_queue_intent(uid,ref,raw,current_intent)
        if not reconciled:
            prior={**prior,"haltedUncertain":True,"uncertainReason":reconcile_reason,"updatedAt":now}
            ref.set({"orderQueueState":prior,"phase":"RECONCILING",
                "lastReason":"Onzekere Strategy-2-order wacht op betrouwbare Aster-reconciliatie"},merge=True)
            return {"status":"uncertain-hold","ordersSent":0,"reason":reconcile_reason}
        prior={**prior,"currentIntent":{},"haltedUncertain":False,"reconcileReason":reconcile_reason,"updatedAt":now}
        ref.set({"orderQueueState":prior},merge=True);raw=ref.get().to_dict() or {}
    if bool(prior.get("haltedUncertain",False)):
        # The normal tick's exchange reconciliation remains active, but order
        # execution must not resume until a later explicit reconciliation path
        # clears this durable marker.
        return {"status":"uncertain-hold","ordersSent":0,"scanId":str(prior.get("scanId","")),
            "reason":"Onzekere Aster-order moet eerst worden gereconcilieerd"}
    if reconcile_only:
        return {"status":"reconciled","ordersSent":0,"scanId":str(prior.get("scanId","")),
            "reason":str(prior.get("reconcileReason","Geen openstaande queue-intent"))}
    used=int(safe_float(prior.get("ordersUsed"))) if str(prior.get("scanId",""))==scan_id else 0
    starting_used=used
    existing_history=list(raw.get("scanActionHistory",[])) if isinstance(raw.get("scanActionHistory"),list) else []
    if not existing_history and isinstance(prior.get("actions"),list):
        existing_history=list(prior.get("actions",[]))[-MAX_ORDERS_PER_ACCOUNT_SCAN:]
    state={"scanId":scan_id,"ordersUsed":used,"maximumOrders":scan_limit,
        "haltedUncertain":False,"startedAt":prior.get("startedAt") if used else now,
        "pendingReopens":raw.get("pendingReopens",[]),"reservedActions":[],"actions":[]}
    ref.set({"orderQueueState":state,"scanActionHistory":existing_history[-MAX_ORDERS_PER_ACCOUNT_SCAN:]},merge=True)
    results=[]
    while used<scan_limit:
        if time.monotonic()>=scan_deadline:
            results.append({"status":"time-budget","ordersSent":0,
                "reason":"Strategy-2 accountscan tijdsbudget bereikt; volgende minuut gaat verder"})
            break
        try:
            result=_run_aster_strategy2_tick(uid,order_budget=scan_limit-used,management_only=management_only,event_symbol=event_symbol,
                event_mark_price=event_mark_price,
                before_order=lambda intent,details=None:_reserve_strategy2_queue_order(
                    ref,scan_id,intent,details,maximum_orders=scan_limit))
        except Strategy2OrderBudgetExhausted:
            latest=ref.get().to_dict() or {};latest_state=latest.get("orderQueueState",{})
            used=int(safe_float(latest_state.get("ordersUsed")));break
        except AsterSubmissionUncertain as exc:
            latest=ref.get().to_dict() or {};latest_state=latest.get("orderQueueState",{})
            used=int(safe_float(latest_state.get("ordersUsed")))
            state.update({"ordersUsed":used,"currentIntent":latest_state.get("currentIntent",{}),"haltedUncertain":True,
                "uncertainReason":str(exc),"updatedAt":datetime.now(timezone.utc)})
            ref.set({"orderQueueState":state,"phase":"RECONCILING",
                "lastReason":"Onzekere Aster-order; alleen deze accountwachtrij is gestopt"},merge=True)
            results.append({"status":"uncertain","ordersSent":1});break
        except Exception as exc:
            # Aster can reject a fully identified contract synchronously after
            # the queue slot was reserved (for example -5018 max notional).
            # That is symbol-local, not an account-wide DATA_HOLD. Clear only
            # the rejected intent and let the next scheduler scan continue.
            if not is_definite_contract_rejection(exc):
                raise
            latest=ref.get().to_dict() or {};latest_state=latest.get("orderQueueState",{})
            used=int(safe_float(latest_state.get("ordersUsed")))
            rejected=latest_state.get("currentIntent") if isinstance(latest_state.get("currentIntent"),dict) else {}
            state.update({"ordersUsed":used,"currentIntent":{},"haltedUncertain":False,
                "updatedAt":datetime.now(timezone.utc)})
            ref.set({"orderQueueState":state,"phase":"WAITING",
                "lastReason":f"Contract lokaal overgeslagen: {exc}"},merge=True)
            ref.collection("audit").add({"event":"QUEUE_CONTRACT_REJECTION_ISOLATED",
                "symbol":str(rejected.get("symbol","")),"side":str(rejected.get("side","")),
                "reason":str(exc),"timestamp":datetime.now(timezone.utc)})
            _record_reliability(uid,component="aster-strategy2-queue",error_code="-5018" if "5018" in str(exc) else "CONTRACT_REJECTION",category="contract_limit",cause=str(exc),original_status=str(latest.get("phase","")),recovery_action="contract geïsoleerd; volgende scan gaat verder",status="AUTO_RECOVERED")
            results.append({"status":"contract-skipped","ordersSent":0,"reason":str(exc)});break
        latest=ref.get().to_dict() or {};latest_state=latest.get("orderQueueState",{})
        new_used=int(safe_float(latest_state.get("ordersUsed")));sent=max(0,new_used-used)
        if new_used>scan_limit:raise RuntimeError("Strategy-2 queue adapter overschreed het accountbudget")
        confirmed_at=datetime.now(timezone.utc)
        reserved=latest_state.get("reservedActions",[]) if isinstance(latest_state.get("reservedActions"),list) else []
        confirmed_actions=list(state.get("actions",[])) if isinstance(state.get("actions"),list) else []
        if sent>0:
            for action in reserved[-sent:]:
                if isinstance(action,dict):confirmed_actions.append({**action,"executedAt":confirmed_at})
        used=new_used;state.update({"ordersUsed":used,"currentIntent":{},"updatedAt":confirmed_at,
            "reservedActions":reserved,"actions":confirmed_actions[-MAX_ORDERS_PER_ACCOUNT_SCAN:],
            "pendingReopens":ref.get().to_dict().get("pendingReopens",[])})
        latest_doc=ref.get().to_dict() or {}
        history=list(latest_doc.get("scanActionHistory",[])) if isinstance(latest_doc.get("scanActionHistory"),list) else []
        if sent>0:
            history.extend(confirmed_actions[-sent:])
        ref.set({"orderQueueState":state,"scanActionHistory":history[-MAX_ORDERS_PER_ACCOUNT_SCAN:]},merge=True);results.append(result)
        if drain_pending_only and not state.get("pendingReopens"):break
        if sent==0:
            # A symbol/leg-local management rejection must not consume the whole
            # account scan while configured Strategy-2 seats are empty. These
            # actions persist a cooldown/block marker, so the next tick advances
            # past that local issue and can use the remaining scan budget to refill.
            retryable_zero_order={"DCA_BLOCKED_MINIMUM","PROTECTION_BUDGET_SKIPPED",
                "CLOSE_BLOCKED_NET_NON_POSITIVE","RISK_BLOCKED","MANAGEMENT_SKIPPED"}
            if str(result.get("action","")) in retryable_zero_order:
                continue
            break
    final_status="ok" if results and any(int(safe_float(x.get("ordersSent"))) for x in results) else "waiting"
    completed_at=datetime.now(timezone.utc)
    # The durable queue wrapper is the account-scan boundary. Even when every
    # candidate is skipped, this scan was real server work and must advance the
    # visible Strategy-2 check time. Otherwise the UI can falsely show an old
    # last check while fresh candidate/audit evidence is being produced.
    ref.set({"lastTickAt":completed_at,"queueLastCompletedAt":completed_at,
        "orderQueueState":{**state,"ordersUsed":used,"updatedAt":completed_at,"completedAt":completed_at}},merge=True)
    return {"status":final_status,
        "scanId":scan_id,"ordersSent":used-starting_used,"ordersUsed":used,"maximumOrders":scan_limit,
        "actions":results}


_aster_realtime_worker: AsterRealtimeWorker | None = None
_aster_realtime_thread: threading.Thread | None = None
_aster_realtime_simple_uids: set[str] = set()

def _aster_realtime_subscription_mapping()->dict[str,set[str]]:
    global _aster_realtime_simple_uids
    mapping:dict[str,set[str]]={};simple_uids:set[str]=set()
    controls=list(db.collection("asterStrategy2").where("monitor","==",True).stream())
    for item in controls[:100]:
        raw=item.to_dict() or {};uid=item.id;symbols:set[str]=set()
        settings_raw=raw.get("settings") if isinstance(raw.get("settings"),dict) else {}
        is_multi_bb=str(settings_raw.get("engine",settings_raw.get("strategyKind","")))==MULTI_BB_ENGINE
        cfg=None if is_multi_bb else Strategy2Config.from_mapping(settings_raw)
        if is_multi_bb:
            # Validate the active engine with its own contract. A Multi BB TP may
            # legally exceed the retired Strategy2Config 20% ceiling.
            MultiBbConfig.from_mapping(settings_raw)
        owned_rows=raw.get("ownedLegs",[]) if isinstance(raw.get("ownedLegs"),list) else []
        queue=raw.get("orderQueueState") if isinstance(raw.get("orderQueueState"),dict) else {};intent=queue.get("currentIntent") if isinstance(queue.get("currentIntent"),dict) else {}
        # A stopped + exchange-flat account has nothing to protect in realtime.
        # Do not let stale legacy pendingReopens keep hammering the config doc.
        if not bool(raw.get("enabled",False)) and not owned_rows and not intent:
            continue
        if cfg is not None and cfg.focus_v2_enabled and cfg.focus_v2_simple_mode_enabled:
            simple_uids.add(uid)
        for row in owned_rows:
            if isinstance(row,dict) and row.get("symbol"):symbols.add(str(row.get("symbol")).upper())
        if intent.get("symbol"):symbols.add(str(intent.get("symbol")).upper())
        for row in raw.get("pendingReopens",[]) if isinstance(raw.get("pendingReopens"),list) else []:
            if isinstance(row,dict) and row.get("symbol"):symbols.add(str(row.get("symbol")).upper())
        for symbol in symbols:mapping.setdefault(symbol,set()).add(uid)
    _aster_realtime_simple_uids=simple_uids
    return mapping

def _aster_realtime_force_evaluate(uid:str,symbol:str)->bool:
    return uid in _aster_realtime_simple_uids

def _run_aster_realtime_evaluation(uid:str,event:RealtimeMarketEvent)->dict[str,Any]:
    ref=aster_strategy2_reference(uid);token=_acquire_strategy2_queue_lease(ref)
    if not token:return {"status":"lease-busy","ordersSent":0,"symbol":event.symbol}
    started=time.monotonic()
    try:
        result=_run_aster_strategy2_queue_scan(uid,maximum_orders=2,management_only=True,event_symbol=event.symbol,event_mark_price=event.mark_price)
        return {**result,"realtime":True,"marketEventAtMs":event.event_time_ms,"marketReceivedAtMs":event.received_at_ms,"reactionMs":round((time.monotonic()-started)*1000,2)}
    finally:_release_strategy2_queue_lease(ref,str(token))

def _persist_aster_realtime_health(payload:dict[str,Any])->None:
    db.collection("systemStatus").document("asterRealtime").set({**payload,"updatedAt":datetime.now(timezone.utc)},merge=True)

def _start_aster_realtime_worker()->None:
    global _aster_realtime_worker
    if os.getenv("ASTER_REALTIME_WORKER","false").lower()!="true":return
    worker=AsterRealtimeWorker(load_subscriptions=_aster_realtime_subscription_mapping,evaluate=_run_aster_realtime_evaluation,persist_health=_persist_aster_realtime_health,execution_enabled=os.getenv("ASTER_REALTIME_EXECUTION_ENABLED","false").lower()=="true",force_evaluate=_aster_realtime_force_evaluate)
    _aster_realtime_worker=worker;asyncio.run(worker.run())

@app.on_event("startup")
def start_aster_realtime_worker()->None:
    global _aster_realtime_thread
    if os.getenv("ASTER_REALTIME_WORKER","false").lower()!="true":return
    if _aster_realtime_thread and _aster_realtime_thread.is_alive():return
    _aster_realtime_thread=threading.Thread(target=_start_aster_realtime_worker,name="aster-realtime",daemon=True);_aster_realtime_thread.start()

@app.get("/internal/aster-realtime/health")
def aster_realtime_health(authorization:str|None=Header(default=None))->dict[str,Any]:
    verify_internal_cloud_request(authorization);worker=_aster_realtime_worker
    return {"workerEnabled":os.getenv("ASTER_REALTIME_WORKER","false").lower()=="true","executionEnabled":os.getenv("ASTER_REALTIME_EXECUTION_ENABLED","false").lower()=="true",**(worker.health() if worker else {"connected":False,"subscriptions":0,"tenants":0})}

@app.on_event("shutdown")
def stop_aster_realtime_worker()->None:
    worker=_aster_realtime_worker
    if worker is not None:worker.stop()


@app.get("/v1/me/aster/realtime/events")
def aster_realtime_events(user:dict[str,Any]=Depends(authenticated_user))->StreamingResponse:
    uid=str(user["uid"])
    async def stream():
        last_seen:dict[str,int]={};last_heartbeat=time.monotonic()
        while True:
            worker=_aster_realtime_worker
            if worker is None:
                yield "event: status\ndata: {\"connected\":false,\"reason\":\"worker-disabled\"}\n\n"
                await asyncio.sleep(2.0);continue
            allowed=worker.registry.symbols_for(uid)
            latest=worker.latest(allowed)
            for symbol,payload in latest.items():
                stamp=int(payload.get("receivedAtMs",0) or 0)
                if stamp<=last_seen.get(symbol,0):continue
                last_seen[symbol]=stamp
                yield f"event: mark\ndata: {json.dumps(payload,separators=(',',':'))}\n\n"
            now=time.monotonic()
            if now-last_heartbeat>=15:
                yield ": heartbeat\n\n";last_heartbeat=now
            await asyncio.sleep(.25)
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no","Connection":"keep-alive"})


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
    # Strategy 1 is retired app-wide. Historical asterAutomation documents are
    # read-only legacy state and are never scheduled or allowed to place orders.
    results=[]
    strategy2_controls=list(db.collection("asterStrategy2").where("monitor","==",True).stream())
    strategy2_results=[]

    def run_strategy2_account(uid:str)->dict[str,Any]:
        reference=aster_strategy2_reference(uid)
        raw=reference.get().to_dict() or {};queue_enabled=_strategy2_order_queue_enabled(raw)
        queue_state=raw.get("orderQueueState") if isinstance(raw.get("orderQueueState"),dict) else {}
        has_unresolved_intent=bool(queue_state.get("currentIntent")) or bool(queue_state.get("haltedUncertain",False))
        has_pending_reopen=bool(raw.get("pendingReopens"))
        queue_recovery_required=has_unresolved_intent or has_pending_reopen
        uses_queue_lease=queue_enabled or queue_recovery_required
        queue_token=_acquire_strategy2_queue_lease(reference) if uses_queue_lease else None
        if uses_queue_lease and not queue_token:return {"uid":uid,"status":"lease-busy"}
        if not uses_queue_lease and not _acquire_mexc_automation_lease(reference):return {"uid":uid,"status":"lease-busy"}
        try:
            result=(_run_aster_strategy2_queue_scan(uid,
                reconcile_only=not queue_enabled and has_unresolved_intent,
                drain_pending_only=not queue_enabled and has_pending_reopen)
                if uses_queue_lease else _run_aster_strategy2_tick(uid))
            return {"uid":uid,**result}
        except Exception as exc:
            message=f"Veilige Strategy-2-schedulerfout: {exc}"
            reference.set({"phase":"DATA_HOLD","lastReason":message,"lastTickAt":datetime.now(timezone.utc)},merge=True)
            return {"uid":uid,"status":"data-hold","reason":message}
        finally:
            if uses_queue_lease:_release_strategy2_queue_lease(reference,str(queue_token))
            else:reference.set({"leaseUntil":datetime.now(timezone.utc)},merge=True)

    strategy2_uids=[item.id for item in strategy2_controls[:100]]
    if strategy2_uids:
        workers=min(4,len(strategy2_uids))
        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix="s2-scheduler") as pool:
            futures=[pool.submit(run_strategy2_account,uid) for uid in strategy2_uids]
            for future in as_completed(futures):strategy2_results.append(future.result())
    # Strategy 1 and Strategy 3 are retired app-wide. Production Aster
    # scheduling is Strategy-2-only.
    return {"processed":len(strategy2_results),"strategy2":strategy2_results,"strategy2Only":True}


@app.post("/internal/aster-strategy2/{uid}/simulate")
def run_aster_strategy2_internal_simulation(uid:str,authorization:str|None=Header(default=None))->dict[str,Any]:
    verify_internal_cloud_request(authorization)
    if not uid or len(uid)>128:raise HTTPException(422,"Ongeldige gebruiker")
    return _run_aster_strategy2_tick(uid,dry_run=True)


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
