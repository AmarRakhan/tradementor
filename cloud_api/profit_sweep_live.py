"""Fail-closed automatic Profit Pot transfers for confirmed Aster closes.

A sweep may only use positive realized net profit.  The implementation snapshots
per-user settings before the close, proves actual realized PnL/fees from Aster
fills, projects cross-margin safety after the transfer, and sends at most one
FUTURE_SPOT transfer for a deterministic close id.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import hashlib
import math
import os
import time
from typing import Any

from google.api_core import exceptions as google_exceptions
from google.cloud import firestore

from aster_close_guard import CloseEvidence
from aster_dynamic_hedge import DynamicHedgeConfig
from aster_gateway import AsterApiError, AsterSubmissionUncertain
from profit_sweep import ProfitSweepError, normalize_sweep_percent, sweep_contribution

LIVE_ENV = "ASTER_PROFIT_SWEEP_LIVE_ENABLED"
TRANSFER_PATH = "/api/v3/asset/wallet/transfer"
SPOT_TRANSACTION_HISTORY_PATH = "/api/v3/transactionHistory"
SPOT_TRANSFER_HISTORY_TYPE = "TRANSFER_FUTURE_TO_SPOT"
TRANSFER_KIND = "FUTURE_SPOT"
DEFAULT_TRANSFER_ASSET = "USDT"
SUPPORTED_TRANSFER_ASSETS = {"USDT", "USDC"}
DEFAULT_MINIMUM_TRANSFER = Decimal("1.00")
LOCAL_DAY_TZ = ZoneInfo("Europe/Amsterdam")
_AMOUNT_QUANTUM = Decimal("0.00000001")


@dataclass
class PreparedSweep:
    uid: str
    sweep_id: str
    intent_id: str
    client_tran_id: str
    symbol: str
    position_side: str
    sweep_percent: Decimal
    transfer_asset: str
    minimum_transfer: Decimal
    user_ref: Any
    ledger_ref: Any
    open_quantity: Decimal
    entry_commission_pool: Decimal
    cycle_start_ms: int
    negative_funding: Decimal
    evidence_entry_fees: Decimal
    evidence_funding: Decimal
    evidence_other_costs: Decimal


def _d(value: Any, default: str = "0") -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)
    return result if result.is_finite() else Decimal(default)


def _plain(value: Decimal) -> str:
    quantized = value.quantize(_AMOUNT_QUANTUM, rounding=ROUND_DOWN)
    text = format(quantized, "f").rstrip("0").rstrip(".")
    return text or "0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def live_enabled() -> bool:
    return os.getenv(LIVE_ENV, "false").strip().lower() == "true"


def is_closing_fill(row: dict[str, Any], position_side: str | None = None) -> bool:
    pos = str(position_side or row.get("positionSide", "")).upper()
    side = str(row.get("side", "")).upper()
    return (pos == "LONG" and side == "SELL") or (pos == "SHORT" and side == "BUY")


def is_opening_fill(row: dict[str, Any], position_side: str | None = None) -> bool:
    pos = str(position_side or row.get("positionSide", "")).upper()
    side = str(row.get("side", "")).upper()
    return (pos == "LONG" and side == "BUY") or (pos == "SHORT" and side == "SELL")


def _commission_cost(row: dict[str, Any]) -> Decimal:
    raw = _d(row.get("commission"))
    if raw == 0:
        return Decimal("0")
    asset = str(row.get("commissionAsset", "USDT")).upper().strip()
    if asset not in {"", "USDT"}:
        raise ProfitSweepError(f"Commissie in {asset} kan niet veilig als USDT-nettowinst worden gewaardeerd")
    # Aster currently reports commission as a negative value.  abs() also
    # makes a future sign-format change conservative instead of profit-inflating.
    return -abs(raw)


def _fill_quantity(row: dict[str, Any]) -> Decimal:
    return abs(_d(row.get("qty", row.get("quantity"))))


def _fill_time(row: dict[str, Any]) -> int:
    try:
        return max(0, int(float(row.get("time", row.get("updateTime", 0)) or 0)))
    except (TypeError, ValueError):
        return 0


def open_inventory(trades: list[dict[str, Any]], position_side: str) -> tuple[Decimal, Decimal, int]:
    """Return remaining qty, signed entry-fee pool and current-cycle start.

    Entry commissions are carried with the remaining inventory and allocated
    proportionally as partial closes occur.  This keeps a later full close from
    treating previously paid entry fees as fresh profit.
    """
    pos = position_side.upper()
    rows = sorted(
        (row for row in trades if str(row.get("positionSide", "")).upper() == pos),
        key=lambda row: (_fill_time(row), str(row.get("id", row.get("tradeId", "")))),
    )
    quantity = Decimal("0")
    fee_pool = Decimal("0")
    cycle_start = 0
    for row in rows:
        qty = _fill_quantity(row)
        if qty <= 0:
            continue
        if is_opening_fill(row, pos):
            if quantity <= 0:
                cycle_start = _fill_time(row)
                fee_pool = Decimal("0")
            quantity += qty
            fee_pool += _commission_cost(row)
            continue
        if not is_closing_fill(row, pos) or quantity <= 0:
            continue
        closing = min(qty, quantity)
        ratio = closing / quantity if quantity > 0 else Decimal("0")
        fee_pool -= fee_pool * ratio
        quantity -= closing
        if quantity <= Decimal("0.000000000001"):
            quantity = Decimal("0")
            fee_pool = Decimal("0")
            cycle_start = 0
    return quantity, fee_pool, cycle_start


def net_realized_for_order(
    *,
    target_fills: list[dict[str, Any]],
    position_side: str,
    pre_open_quantity: Decimal,
    pre_entry_commission_pool: Decimal,
    negative_funding: Decimal = Decimal("0"),
    evidence: CloseEvidence | None = None,
) -> tuple[Decimal, dict[str, str]]:
    rows = [row for row in target_fills if is_closing_fill(row, position_side)]
    if not rows:
        raise ProfitSweepError("Aster bevestigde nog geen sluitfills voor deze order")
    closed_qty = sum((_fill_quantity(row) for row in rows), Decimal("0"))
    if closed_qty <= 0 or pre_open_quantity <= 0:
        raise ProfitSweepError("Sluitingshoeveelheid kan niet betrouwbaar aan open inventory worden gekoppeld")
    ratio = min(Decimal("1"), closed_qty / pre_open_quantity)
    realized = sum((_d(row.get("realizedPnl", row.get("realizedProfit"))) for row in rows), Decimal("0"))
    close_commission = sum((_commission_cost(row) for row in rows), Decimal("0"))
    allocated_entry_commission = pre_entry_commission_pool * ratio
    entry_fee_cost = abs(allocated_entry_commission)
    evidence_entry = _d(evidence.entry_fees) if evidence is not None else Decimal("0")
    if evidence_entry > entry_fee_cost:
        entry_fee_cost = evidence_entry
    funding_adjustment = min(Decimal("0"), negative_funding * ratio)
    evidence_funding = _d(evidence.funding) if evidence is not None else Decimal("0")
    funding_adjustment = min(funding_adjustment, evidence_funding, Decimal("0"))
    other_cost = max(Decimal("0"), _d(evidence.other_costs) if evidence is not None else Decimal("0"))
    net = realized + close_commission - entry_fee_cost + funding_adjustment - other_cost
    return net, {
        "realizedPnl": _plain(realized),
        "closedQuantity": _plain(closed_qty),
        "closeCommission": _plain(close_commission),
        "allocatedEntryFee": _plain(-entry_fee_cost),
        "fundingAdjustment": _plain(funding_adjustment),
        "otherCostAdjustment": _plain(-other_cost),
    }


def transfer_safety(account: dict[str, Any], amount: Decimal) -> tuple[bool, str, dict[str, float]]:
    """Project the account after removing ``amount`` from Futures margin."""
    try:
        available = float(account.get("availableBalance", 0) or 0)
        equity = float(account.get("totalMarginBalance", 0) or 0)
        maintenance = float(account.get("totalMaintMargin", 0) or 0)
    except (TypeError, ValueError):
        return False, "ACCOUNT_VALUES_INVALID", {}
    if not all(math.isfinite(x) and x >= 0 for x in (available, equity, maintenance)):
        return False, "ACCOUNT_VALUES_INVALID", {}
    value = float(amount)
    if value <= 0:
        return False, "TRANSFER_NOT_POSITIVE", {}
    if value > available + 1e-9:
        return False, "INSUFFICIENT_AVAILABLE_BALANCE", {"available": available}
    projected_equity = equity - value
    projected_buffer = projected_equity - maintenance
    projected_ratio = projected_equity / maintenance if maintenance > 0 else None
    projected_risk = maintenance / projected_equity * 100 if projected_equity > 0 and maintenance > 0 else 0.0
    details = {
        "available": available,
        "equity": equity,
        "maintenance": maintenance,
        "projectedEquity": projected_equity,
        "projectedBuffer": projected_buffer,
        "projectedRiskPct": projected_risk,
        "projectedBufferRatio": projected_ratio or 0.0,
    }
    if maintenance <= 0:
        return projected_equity >= 0, "SAFE_FLAT_ACCOUNT" if projected_equity >= 0 else "NEGATIVE_PROJECTED_EQUITY", details
    policy = DynamicHedgeConfig().validated()
    if projected_equity <= maintenance:
        return False, "PROJECTED_EQUITY_AT_MAINTENANCE", details
    if projected_buffer < policy.minimum_projected_buffer_usd:
        return False, "PROJECTED_MARGIN_BUFFER_TOO_LOW", details
    if projected_ratio is None or projected_ratio < policy.minimum_projected_buffer_ratio:
        return False, "PROJECTED_BUFFER_RATIO_TOO_LOW", details
    if projected_risk >= policy.safe_risk_pct:
        return False, "PROJECTED_LIQUIDATION_RISK_NOT_SAFE", details
    return True, "SAFE", details


def _client_tran_id(uid: str, intent_id: str) -> str:
    return "tmpp-" + hashlib.sha256(f"{uid}:{intent_id}".encode()).hexdigest()[:27]


def _sweep_id(uid: str, intent_id: str) -> str:
    return hashlib.sha256(f"ASTER:{uid}:{intent_id}".encode()).hexdigest()


def _timestamp_ms(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _transfer_history_match(
    rows: list[dict[str, Any]],
    *,
    amount: Decimal,
    submitted_at: Any,
    asset: str = DEFAULT_TRANSFER_ASSET,
) -> tuple[str, dict[str, Any] | None]:
    """Match one FUTURE_SPOT transfer without issuing another money movement.

    Aster's futures income history exposes transfer transaction id, amount,
    asset and timestamp, but not clientTranId. We therefore only accept a
    unique, exact USDT debit in a tight window around this submission. Zero or
    multiple matches remain uncertain and are never treated as proof.
    """
    submitted_ms = _timestamp_ms(submitted_at)
    if submitted_ms <= 0 or amount <= 0:
        return "INVALID_EVIDENCE", None
    lower = max(0, submitted_ms - 15_000)
    upper = submitted_ms + 180_000
    expected = (-abs(amount)).quantize(_AMOUNT_QUANTUM)
    matches: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("incomeType", "")).upper() != "TRANSFER":
            continue
        if str(row.get("asset", "")).upper() != asset:
            continue
        row_time = _timestamp_ms(row.get("time"))
        if row_time < lower or row_time > upper:
            continue
        if _d(row.get("income")).quantize(_AMOUNT_QUANTUM) != expected:
            continue
        if row.get("tranId") in (None, ""):
            continue
        matches.append(row)
    if len(matches) == 1:
        return "CONFIRMED", matches[0]
    if len(matches) > 1:
        return "AMBIGUOUS", None
    return "NOT_FOUND", None


def _spot_transfer_history_match(
    rows: list[dict[str, Any]],
    *,
    amount: Decimal,
    submitted_at: Any,
    asset: str = DEFAULT_TRANSFER_ASSET,
) -> tuple[str, dict[str, Any] | None]:
    """Match a FUTURE->SPOT credit in Aster Spot transaction history."""
    submitted_ms = _timestamp_ms(submitted_at)
    if submitted_ms <= 0 or amount <= 0:
        return "INVALID_EVIDENCE", None
    lower = max(0, submitted_ms - 15_000)
    upper = submitted_ms + 180_000
    expected = abs(amount).quantize(_AMOUNT_QUANTUM)
    matches: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("type", "")).upper() != SPOT_TRANSFER_HISTORY_TYPE:
            continue
        if str(row.get("asset", "")).upper() != asset:
            continue
        row_time = _timestamp_ms(row.get("time"))
        if row_time < lower or row_time > upper:
            continue
        if abs(_d(row.get("balanceDelta"))).quantize(_AMOUNT_QUANTUM) != expected:
            continue
        if row.get("tranId") in (None, ""):
            continue
        matches.append(row)
    if len(matches) == 1:
        return "CONFIRMED_SPOT", matches[0]
    if len(matches) > 1:
        return "AMBIGUOUS_SPOT", None
    return "NOT_FOUND_SPOT", None


def reconcile_transfer_rows(
    *,
    spot_rows: list[dict[str, Any]],
    futures_rows: list[dict[str, Any]],
    amount: Decimal,
    submitted_at: Any,
    asset: str = DEFAULT_TRANSFER_ASSET,
) -> tuple[str, dict[str, Any] | None]:
    spot_state, spot_match = _spot_transfer_history_match(
        spot_rows, amount=amount, submitted_at=submitted_at, asset=asset,
    )
    if spot_match is not None or spot_state == "AMBIGUOUS_SPOT":
        return spot_state, spot_match
    future_state, future_match = _transfer_history_match(
        futures_rows, amount=amount, submitted_at=submitted_at, asset=asset,
    )
    if future_match is not None or future_state == "AMBIGUOUS":
        return future_state, future_match
    return "NOT_FOUND", None


def reconcile_transfer_history(
    *,
    client: Any,
    amount: Decimal,
    submitted_at: Any,
    asset: str = DEFAULT_TRANSFER_ASSET,
    poll_attempts: int = 2,
    poll_delay_seconds: float = 0.35,
) -> tuple[str, dict[str, Any] | None]:
    """Read-only reconciliation across Spot and Futures ledgers."""
    submitted_ms = _timestamp_ms(submitted_at)
    if submitted_ms <= 0:
        return "INVALID_EVIDENCE", None
    attempts = max(1, int(poll_attempts))
    last_state = "NOT_FOUND"
    for attempt in range(attempts):
        spot_rows: list[dict[str, Any]] = []
        futures_rows: list[dict[str, Any]] = []
        spot_ok = futures_ok = False
        try:
            payload = client.signed_spot_request("GET", SPOT_TRANSACTION_HISTORY_PATH, {
                "asset": asset,
                "type": SPOT_TRANSFER_HISTORY_TYPE,
                "startTime": max(0, submitted_ms - 15_000),
                "endTime": submitted_ms + 180_000,
                "limit": 1000,
            })
            if isinstance(payload, list) and len(payload) < 1000:
                spot_rows = [row for row in payload if isinstance(row, dict)]
                spot_ok = True
            elif isinstance(payload, list):
                return "SPOT_HISTORY_TRUNCATED", None
        except (AsterApiError, AsterSubmissionUncertain):
            pass
        try:
            payload = client.income_history(
                income_type="TRANSFER",
                start_time=max(0, submitted_ms - 15_000),
                end_time=submitted_ms + 180_000,
                limit=1000,
            )
            if len(payload) < 1000:
                futures_rows = list(payload)
                futures_ok = True
            else:
                return "FUTURES_HISTORY_TRUNCATED", None
        except (AsterApiError, AsterSubmissionUncertain):
            pass
        if spot_ok or futures_ok:
            state, match = reconcile_transfer_rows(
                spot_rows=spot_rows,
                futures_rows=futures_rows,
                amount=amount,
                submitted_at=submitted_at,
                asset=asset,
            )
            if match is not None or state in {"AMBIGUOUS", "AMBIGUOUS_SPOT"}:
                return state, match
            last_state = state
        else:
            last_state = "HISTORY_UNAVAILABLE"
        if attempt + 1 < attempts and poll_delay_seconds > 0:
            time.sleep(poll_delay_seconds)
    return last_state, None


def _reconciled_result(
    *,
    ref: Any,
    contribution: Decimal,
    record: dict[str, Any],
) -> dict[str, Any]:
    tran_id = str(record.get("tranId", "")).strip()
    ref.set({
        "status": "SUCCEEDED",
        "providerTransactionId": tran_id,
        "providerStatus": "SUCCESS",
        "reconciledFromHistory": True,
        "reconciledAt": _now(),
        "completedAt": _now(),
    }, merge=True)
    return {
        "status": "SUCCEEDED",
        "contribution": _plain(contribution),
        "tranId": tran_id,
        "reconciled": True,
    }


def _uncertain_result(
    *,
    ref: Any,
    reason: str,
    client: Any,
    contribution: Decimal,
    submitted_at: Any,
    asset: str = DEFAULT_TRANSFER_ASSET,
) -> dict[str, Any]:
    state, record = reconcile_transfer_history(
        client=client,
        amount=contribution,
        submitted_at=submitted_at,
        asset=asset,
    )
    if record is not None:
        return _reconciled_result(ref=ref, contribution=contribution, record=record)
    ref.set({
        "status": "UNCERTAIN",
        "reason": str(reason)[:500],
        "reconciliationStatus": state,
        "reconciledAt": _now(),
        "updatedAt": _now(),
    }, merge=True)
    return {"status": "UNCERTAIN", "reconciliationStatus": state}


def _recovery_client_tran_id(uid: str, sweep_id: str) -> str:
    return "tmpr-" + hashlib.sha256(f"{uid}:{sweep_id}:spot-recovery".encode()).hexdigest()[:27]


def _unknown_execution_reason(value: Any) -> bool:
    text = str(value or "").lower()
    return (
        "-1006" in text
        or "-1007" in text
        or "execution status unknown" in text
        or "uitvoeringsstatus onbekend" in text
        or "status unknown" in text
    )


def recover_failed_sweep(
    *,
    uid: str,
    sweep_id: str,
    user_ref: Any,
    ledger_ref: Any,
    ledger: dict[str, Any],
    client: Any,
    spot_rows: list[dict[str, Any]] | None = None,
    futures_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Safely recover one old unknown sweep with a deterministic idempotency key.

    The original submission is reconciled first. A recovery uses a deterministic
    clientTranId that Aster requires to be unique for seven days. If Aster returns
    -1006/-1007, at most one replay of that exact same clientTranId is allowed;
    this cannot intentionally create a second transfer and avoids inventing a
    fresh transaction id for an unknown execution state.
    """
    status = str(ledger.get("status", "")).upper()
    if status == "SUCCEEDED":
        return {"status": "ALREADY_SUCCEEDED"}
    if status not in {"FAILED_EXCHANGE", "UNCERTAIN", "RECOVERY_UNCERTAIN"}:
        return {"status": "NOT_RECOVERABLE", "sourceStatus": status}
    if not _unknown_execution_reason(ledger.get("reason")):
        return {"status": "NOT_RECOVERABLE", "sourceStatus": status}

    contribution = _d(ledger.get("sweepContribution"))
    transfer_asset = str(ledger.get("asset", DEFAULT_TRANSFER_ASSET)).upper().strip()
    if transfer_asset not in SUPPORTED_TRANSFER_ASSETS:
        transfer_asset = DEFAULT_TRANSFER_ASSET
    submitted_at = ledger.get("submittedAt") or ledger.get("updatedAt") or ledger.get("completedAt")
    if contribution <= 0 or _timestamp_ms(submitted_at) <= 0:
        return {"status": "INVALID_RECOVERY_EVIDENCE"}

    if spot_rows is not None or futures_rows is not None:
        reconcile_state, record = reconcile_transfer_rows(
            spot_rows=list(spot_rows or []),
            futures_rows=list(futures_rows or []),
            amount=contribution,
            submitted_at=submitted_at,
            asset=transfer_asset,
        )
    else:
        reconcile_state, record = reconcile_transfer_history(
            client=client,
            amount=contribution,
            submitted_at=submitted_at,
            asset=transfer_asset,
            poll_attempts=1,
            poll_delay_seconds=0,
        )
    if record is not None:
        result = _reconciled_result(ref=ledger_ref, contribution=contribution, record=record)
        ledger_ref.set({
            "recoveryAvoidedDuplicate": True,
            "reconciliationStatus": reconcile_state,
        }, merge=True)
        return result
    if reconcile_state in {"AMBIGUOUS", "AMBIGUOUS_SPOT", "HISTORY_UNAVAILABLE"}:
        ledger_ref.set({
            "status": "UNCERTAIN",
            "reconciliationStatus": reconcile_state,
            "updatedAt": _now(),
        }, merge=True)
        return {"status": "UNCERTAIN", "reconciliationStatus": reconcile_state}

    recovery_ref = user_ref.collection("asterProfitSweepRecoveries").document(sweep_id)
    recovery_client_id = _recovery_client_tran_id(uid, sweep_id)
    existing_recovery: dict[str, Any] = {}
    try:
        recovery_ref.create({
            "uid": uid,
            "sweepId": sweep_id,
            "clientTranId": recovery_client_id,
            "asset": transfer_asset,
            "kindType": TRANSFER_KIND,
            "amount": _plain(contribution),
            "status": "CLAIMED",
            "submitAttempts": 0,
            "createdAt": _now(),
        })
    except google_exceptions.AlreadyExists:
        existing_recovery = recovery_ref.get().to_dict() or {}
        # Never continue a claim whose immutable identity/economic fields differ.
        if (
            str(existing_recovery.get("clientTranId", "")) != recovery_client_id
            or str(existing_recovery.get("asset", "")).upper() != transfer_asset
            or str(existing_recovery.get("kindType", "")).upper() != TRANSFER_KIND
            or _d(existing_recovery.get("amount")) != contribution
        ):
            ledger_ref.set({
                "status": "RECOVERY_UNCERTAIN",
                "reason": "Bestaande recovery-claim komt niet overeen; geen geldverplaatsing verstuurd",
                "updatedAt": _now(),
            }, merge=True)
            return {"status": "RECOVERY_ALREADY_CLAIMED"}

        provider_id = existing_recovery.get("providerTransactionId")
        if str(existing_recovery.get("status", "")).upper() == "SUCCEEDED" and provider_id not in (None, ""):
            ledger_ref.set({
                "status": "SUCCEEDED",
                "providerTransactionId": str(provider_id),
                "providerStatus": "SUCCESS",
                "recoveredViaSpotV3": True,
                "recoveryClientTranId": recovery_client_id,
                "completedAt": _now(),
            }, merge=True)
            return {
                "status": "SUCCEEDED",
                "contribution": _plain(contribution),
                "tranId": str(provider_id),
                "recovered": True,
            }

        prior_recovery_submitted = existing_recovery.get("submittedAt") or ledger.get("recoverySubmittedAt")
        if _timestamp_ms(prior_recovery_submitted) > 0:
            prior_state, prior_record = reconcile_transfer_history(
                client=client,
                amount=contribution,
                submitted_at=prior_recovery_submitted,
                asset=transfer_asset,
                poll_attempts=2,
                poll_delay_seconds=0.35,
            )
            if prior_record is not None:
                result = _reconciled_result(ref=ledger_ref, contribution=contribution, record=prior_record)
                recovery_ref.set({
                    "status": "SUCCEEDED",
                    "providerTransactionId": str(prior_record.get("tranId")),
                    "reconciliationStatus": prior_state,
                    "completedAt": _now(),
                }, merge=True)
                return {**result, "recovered": True}
            if prior_state in {"AMBIGUOUS", "AMBIGUOUS_SPOT", "HISTORY_UNAVAILABLE"}:
                ledger_ref.set({
                    "status": "RECOVERY_UNCERTAIN",
                    "reconciliationStatus": prior_state,
                    "updatedAt": _now(),
                }, merge=True)
                return {"status": "UNCERTAIN", "reconciliationStatus": prior_state}

    if not live_enabled():
        return {"status": "BLOCKED_GLOBAL_GATE"}

    account = client.account_information()
    safe, margin_reason, projection = transfer_safety(account, contribution)
    ledger_ref.set({
        "recoveryMarginSafety": projection,
        "recoveryMarginSafetyReason": margin_reason,
        "updatedAt": _now(),
    }, merge=True)
    if not safe:
        ledger_ref.set({"status": "RECOVERY_BLOCKED_MARGIN", "updatedAt": _now()}, merge=True)
        return {"status": "RECOVERY_BLOCKED_MARGIN", "reason": margin_reason}

    # Aster documents clientTranId as unique for seven days. Therefore a replay
    # is only permitted with this exact deterministic id, never with a fresh id.
    if existing_recovery:
        try:
            attempts = int(existing_recovery.get("submitAttempts", 1 if existing_recovery.get("submittedAt") else 0))
        except (TypeError, ValueError):
            attempts = 1 if existing_recovery.get("submittedAt") else 0
    else:
        attempts = 0
    if attempts >= 2:
        ledger_ref.set({
            "status": "RECOVERY_UNCERTAIN",
            "reason": "Recovery bleef onzeker na idempotente replay; geen extra geldverplaatsing verstuurd",
            "updatedAt": _now(),
        }, merge=True)
        return {"status": "UNCERTAIN", "reconciliationStatus": "IDEMPOTENT_REPLAY_EXHAUSTED"}

    while attempts < 2:
        attempts += 1
        recovery_submitted_at = _now()
        recovery_ref.set({
            "status": "SUBMITTING" if attempts == 1 else "RESUBMITTING_SAME_ID",
            "submitAttempts": attempts,
            "submittedAt": existing_recovery.get("submittedAt", recovery_submitted_at) if existing_recovery else recovery_submitted_at,
            "lastSubmittedAt": recovery_submitted_at,
            "updatedAt": _now(),
        }, merge=True)
        ledger_ref.set({
            "status": "RECOVERY_SUBMITTING",
            "recoveryClientTranId": recovery_client_id,
            "recoverySubmittedAt": recovery_submitted_at,
            "recoverySubmitAttempts": attempts,
            "updatedAt": _now(),
        }, merge=True)
        try:
            payload = client.signed_spot_request("POST", TRANSFER_PATH, {
                "asset": transfer_asset,
                "amount": _plain(contribution),
                "clientTranId": recovery_client_id,
                "kindType": TRANSFER_KIND,
            })
        except AsterSubmissionUncertain as exc:
            result = _uncertain_result(
                ref=ledger_ref,
                reason=str(exc),
                client=client,
                contribution=contribution,
                submitted_at=recovery_submitted_at,
                asset=transfer_asset,
            )
            if str(result.get("status", "")).upper() == "SUCCEEDED":
                recovery_ref.set({
                    "status": "SUCCEEDED",
                    "providerTransactionId": str(result.get("tranId")),
                    "reconciliationStatus": result.get("reconciliationStatus"),
                    "completedAt": _now(),
                }, merge=True)
                return {**result, "recovered": True}
            recovery_ref.set({
                "status": "UNCERTAIN",
                "reason": str(exc)[:500],
                "submitAttempts": attempts,
                "updatedAt": _now(),
            }, merge=True)
            if attempts < 2 and str(result.get("reconciliationStatus", "")).upper() == "NOT_FOUND":
                continue
            return result
        except AsterApiError as exc:
            message = str(exc)
            if "-4115" in message:
                # Same clientTranId is already known to Aster. Never invent a new
                # id; reconcile the existing transfer and otherwise remain safe.
                dup_state, dup_record = reconcile_transfer_history(
                    client=client,
                    amount=contribution,
                    submitted_at=existing_recovery.get("submittedAt") or recovery_submitted_at,
                    asset=transfer_asset,
                    poll_attempts=2,
                    poll_delay_seconds=0.35,
                )
                if dup_record is not None:
                    result = _reconciled_result(ref=ledger_ref, contribution=contribution, record=dup_record)
                    recovery_ref.set({
                        "status": "SUCCEEDED",
                        "providerTransactionId": str(dup_record.get("tranId")),
                        "reconciliationStatus": dup_state,
                        "completedAt": _now(),
                    }, merge=True)
                    return {**result, "recovered": True}
                recovery_ref.set({
                    "status": "UNCERTAIN",
                    "reason": "DUPLICATED_CLIENT_TRAN_ID",
                    "submitAttempts": attempts,
                    "reconciliationStatus": dup_state,
                    "updatedAt": _now(),
                }, merge=True)
                ledger_ref.set({
                    "status": "RECOVERY_UNCERTAIN",
                    "reason": "Aster kent dezelfde recovery-id; historie bevestigt de transfer nog niet",
                    "reconciliationStatus": dup_state,
                    "updatedAt": _now(),
                }, merge=True)
                return {"status": "UNCERTAIN", "reconciliationStatus": dup_state}
            recovery_ref.set({
                "status": "FAILED_EXCHANGE",
                "reason": message[:500],
                "submitAttempts": attempts,
                "completedAt": _now(),
            }, merge=True)
            ledger_ref.set({
                "status": "RECOVERY_FAILED_EXCHANGE",
                "reason": message[:500],
                "updatedAt": _now(),
            }, merge=True)
            return {"status": "RECOVERY_FAILED_EXCHANGE"}

        if not isinstance(payload, dict) or str(payload.get("status", "")).upper() != "SUCCESS" or payload.get("tranId") in (None, ""):
            result = _uncertain_result(
                ref=ledger_ref,
                reason="Aster Spot bevestigde geen SUCCESS + tranId",
                client=client,
                contribution=contribution,
                submitted_at=recovery_submitted_at,
            )
            if str(result.get("status", "")).upper() == "SUCCEEDED":
                recovery_ref.set({
                    "status": "SUCCEEDED",
                    "providerTransactionId": str(result.get("tranId")),
                    "reconciliationStatus": result.get("reconciliationStatus"),
                    "completedAt": _now(),
                }, merge=True)
                return {**result, "recovered": True}
            recovery_ref.set({
                "status": "UNCERTAIN",
                "providerResponse": payload if isinstance(payload, dict) else {},
                "submitAttempts": attempts,
                "updatedAt": _now(),
            }, merge=True)
            if attempts < 2 and str(result.get("reconciliationStatus", "")).upper() == "NOT_FOUND":
                continue
            return result

        tran_id = str(payload.get("tranId"))
        recovery_ref.set({
            "status": "SUCCEEDED",
            "providerTransactionId": tran_id,
            "submitAttempts": attempts,
            "completedAt": _now(),
        }, merge=True)
        ledger_ref.set({
            "status": "SUCCEEDED",
            "providerTransactionId": tran_id,
            "providerStatus": "SUCCESS",
            "recoveredViaSpotV3": True,
            "recoveryClientTranId": recovery_client_id,
            "completedAt": _now(),
        }, merge=True)
        return {
            "status": "SUCCEEDED",
            "contribution": _plain(contribution),
            "tranId": tran_id,
            "recovered": True,
        }

    return {"status": "UNCERTAIN", "reconciliationStatus": "IDEMPOTENT_REPLAY_EXHAUSTED"}


def prepare_close_sweep(
    *,
    uid: str,
    user_ref: Any,
    client: Any,
    intent_id: str,
    symbol: str,
    position_side: str,
    close_quantity: Any,
    evidence: CloseEvidence | None = None,
) -> PreparedSweep | None:
    """Snapshot settings/evidence before the close; never blocks the close itself."""
    if not live_enabled():
        return None
    control_ref = user_ref.collection("executionControls").document("aster")
    control = control_ref.get().to_dict() or {}
    settings = control.get("profitSweep") if isinstance(control.get("profitSweep"), dict) else {}
    transfer_asset = str(settings.get("transferAsset", DEFAULT_TRANSFER_ASSET)).upper().strip()
    if transfer_asset not in SUPPORTED_TRANSFER_ASSETS:
        transfer_asset = DEFAULT_TRANSFER_ASSET
    minimum_transfer = _d(settings.get("minimumTransfer", DEFAULT_MINIMUM_TRANSFER))
    if minimum_transfer <= 0:
        minimum_transfer = DEFAULT_MINIMUM_TRANSFER
    if settings.get("enabled") is not True:
        return None
    try:
        percent = normalize_sweep_percent(settings.get("sweepPercent", 25))
    except ProfitSweepError:
        return None
    if percent <= 0:
        return None
    sweep_id = _sweep_id(uid, intent_id)
    ledger_ref = user_ref.collection("asterProfitSweeps").document(sweep_id)
    created = {
        "uid": uid,
        "exchange": "ASTER",
        "closureId": intent_id,
        "symbol": symbol.upper(),
        "positionSide": position_side.upper(),
        "sweepPercent": float(percent),
        "asset": transfer_asset,
        "kindType": TRANSFER_KIND,
        "clientTranId": _client_tran_id(uid, intent_id),
        "status": "PREPARING",
        "principalIncluded": False,
        "unrealizedPnlIncluded": False,
        "createdAt": _now(),
    }
    try:
        ledger_ref.create(created)
    except google_exceptions.AlreadyExists:
        return None

    try:
        pre_trades = client.user_trades(symbol.upper(), limit=1000)
        if len(pre_trades) >= 1000:
            raise ProfitSweepError("Fillhistorie is begrensd; entrykosten kunnen niet volledig worden bewezen")
        open_qty, fee_pool, cycle_start = open_inventory(pre_trades, position_side)
        requested = abs(_d(close_quantity))
        if open_qty <= 0 or requested <= 0 or requested > open_qty + Decimal("0.00000001"):
            raise ProfitSweepError("Open inventory en sluitingshoeveelheid komen niet betrouwbaar overeen")
        if cycle_start <= 0:
            raise ProfitSweepError("Start van de huidige positiecyclus ontbreekt")
        funding_rows = client.income_history(
            symbol=symbol.upper(), income_type="FUNDING_FEE", start_time=cycle_start, limit=1000,
        )
        if len(funding_rows) >= 1000:
            raise ProfitSweepError("Fundinghistorie is begrensd; nettowinst kan niet conservatief worden bewezen")
        # Positive funding is deliberately ignored; negative funding is a cost.
        negative_funding = sum((min(Decimal("0"), _d(row.get("income"))) for row in funding_rows), Decimal("0"))
        ledger_ref.set({
            "status": "PREPARED",
            "openQuantityBeforeClose": _plain(open_qty),
            "entryCommissionPool": _plain(fee_pool),
            "negativeFundingObserved": _plain(negative_funding),
            "cycleStartMs": cycle_start,
            "preparedAt": _now(),
        }, merge=True)
        return PreparedSweep(
            uid=uid,
            sweep_id=sweep_id,
            intent_id=intent_id,
            client_tran_id=created["clientTranId"],
            symbol=symbol.upper(),
            position_side=position_side.upper(),
            sweep_percent=percent,
            transfer_asset=transfer_asset,
            minimum_transfer=minimum_transfer,
            user_ref=user_ref,
            ledger_ref=ledger_ref,
            open_quantity=open_qty,
            entry_commission_pool=fee_pool,
            cycle_start_ms=cycle_start,
            negative_funding=negative_funding,
            evidence_entry_fees=_d(evidence.entry_fees) if evidence else Decimal("0"),
            evidence_funding=_d(evidence.funding) if evidence else Decimal("0"),
            evidence_other_costs=_d(evidence.other_costs) if evidence else Decimal("0"),
        )
    except Exception as exc:
        ledger_ref.set({"status": "BLOCKED_EVIDENCE", "reason": str(exc)[:500], "updatedAt": _now()}, merge=True)
        return None



def _local_day_key(value: datetime | None = None) -> str:
    current = value or _now()
    return current.astimezone(LOCAL_DAY_TZ).date().isoformat()


def _buffer_client_tran_id(uid: str, sequence: int) -> str:
    return "tmpp2-" + hashlib.sha256(f"{uid}:buffer:{sequence}".encode()).hexdigest()[:26]


def _state_snapshot(prepared: PreparedSweep) -> tuple[Any, dict[str, Any]]:
    ref = prepared.user_ref.collection("asterProfitSweepState").document("current")
    return ref, (ref.get().to_dict() or {})


def _book_contribution(prepared: PreparedSweep, contribution: Decimal) -> dict[str, Any]:
    """Idempotently credit one realized-profit contribution to the persistent buffer."""
    state_ref = prepared.user_ref.collection("asterProfitSweepState").document("current")
    ledger_ref = prepared.ledger_ref
    client = getattr(state_ref, "_client", None)

    def apply(transaction: Any | None = None) -> dict[str, Any]:
        if transaction is None:
            ledger = ledger_ref.get().to_dict() or {}
            state = state_ref.get().to_dict() or {}
        else:
            ledger = ledger_ref.get(transaction=transaction).to_dict() or {}
            state = state_ref.get(transaction=transaction).to_dict() or {}
        pending = _d(state.get("pendingSavings"))
        today_key = _local_day_key()
        stored_day = str(state.get("todayKey", ""))
        today_total = _d(state.get("todayTransferred")) if stored_day == today_key else Decimal("0")
        if ledger.get("bufferBooked") is True:
            return {
                "pendingSavings": pending,
                "todayTransferred": today_total,
                "alreadyBooked": True,
            }
        next_pending = pending + contribution
        state_update = {
            "pendingSavings": _plain(next_pending),
            "todayTransferred": _plain(today_total),
            "todayKey": today_key,
            "minimumTransfer": _plain(prepared.minimum_transfer),
            "asset": prepared.transfer_asset,
            "updatedAt": _now(),
        }
        ledger_update = {
            "bufferBooked": True,
            "bufferBookedAmount": _plain(contribution),
            "bufferBookedAt": _now(),
            "status": "BUFFERED",
        }
        if transaction is None:
            state_ref.set(state_update, merge=True)
            ledger_ref.set(ledger_update, merge=True)
        else:
            transaction.set(state_ref, state_update, merge=True)
            transaction.set(ledger_ref, ledger_update, merge=True)
        return {
            "pendingSavings": next_pending,
            "todayTransferred": today_total,
            "alreadyBooked": False,
        }

    if client is None:
        return apply()
    @firestore.transactional
    def run(transaction: Any) -> dict[str, Any]:
        return apply(transaction)
    return run(client.transaction())


def _claim_threshold_transfer(prepared: PreparedSweep) -> dict[str, Any] | None:
    """Atomically reserve exactly one threshold block without reducing the buffer."""
    state_ref = prepared.user_ref.collection("asterProfitSweepState").document("current")
    transfers = prepared.user_ref.collection("asterProfitSweepTransfers")
    client = getattr(state_ref, "_client", None)

    def apply(transaction: Any | None = None) -> dict[str, Any] | None:
        state = (state_ref.get().to_dict() or {}) if transaction is None else (state_ref.get(transaction=transaction).to_dict() or {})
        existing = state.get("inFlight")
        if isinstance(existing, dict) and existing.get("claimId"):
            return dict(existing)
        pending = _d(state.get("pendingSavings"))
        threshold = prepared.minimum_transfer
        if pending + _AMOUNT_QUANTUM < threshold:
            return None
        sequence = int(state.get("transferSequence", 0) or 0) + 1
        claim_id = hashlib.sha256(f"{prepared.uid}:{sequence}:{prepared.transfer_asset}:{_plain(threshold)}".encode()).hexdigest()
        claim = {
            "claimId": claim_id,
            "sequence": sequence,
            "amount": _plain(threshold),
            "asset": prepared.transfer_asset,
            "clientTranId": _buffer_client_tran_id(prepared.uid, sequence),
            "status": "CLAIMED",
            "createdAt": _now(),
        }
        update = {
            "inFlight": claim,
            "transferSequence": sequence,
            "minimumTransfer": _plain(threshold),
            "asset": prepared.transfer_asset,
            "updatedAt": _now(),
        }
        transfer_ref = transfers.document(claim_id)
        transfer_row = {
            "uid": prepared.uid,
            "claimId": claim_id,
            "sequence": sequence,
            "amount": _plain(threshold),
            "asset": prepared.transfer_asset,
            "kindType": TRANSFER_KIND,
            "clientTranId": claim["clientTranId"],
            "status": "CLAIMED",
            "createdAt": claim["createdAt"],
        }
        if transaction is None:
            state_ref.set(update, merge=True)
            transfer_ref.set(transfer_row, merge=True)
        else:
            transaction.set(state_ref, update, merge=True)
            transaction.set(transfer_ref, transfer_row, merge=True)
        return claim

    if client is None:
        return apply()
    @firestore.transactional
    def run(transaction: Any) -> dict[str, Any] | None:
        return apply(transaction)
    return run(client.transaction())


def _mark_claim(prepared: PreparedSweep, claim: dict[str, Any], *, status: str, **fields: Any) -> dict[str, Any]:
    state_ref = prepared.user_ref.collection("asterProfitSweepState").document("current")
    transfer_ref = prepared.user_ref.collection("asterProfitSweepTransfers").document(str(claim["claimId"]))
    current_state = state_ref.get().to_dict() or {}
    current = current_state.get("inFlight")
    if not isinstance(current, dict) or current.get("claimId") != claim.get("claimId"):
        return claim
    next_claim = {**current, "status": status, **fields, "updatedAt": _now()}
    state_ref.set({"inFlight": next_claim, "updatedAt": _now()}, merge=True)
    transfer_ref.set({"status": status, **fields, "updatedAt": _now()}, merge=True)
    return next_claim


def _complete_claim(prepared: PreparedSweep, claim: dict[str, Any], *, tran_id: str, reconciled: bool = False) -> dict[str, Any]:
    """Only after exchange-confirmed success: subtract one block and raise today's total."""
    state_ref = prepared.user_ref.collection("asterProfitSweepState").document("current")
    transfer_ref = prepared.user_ref.collection("asterProfitSweepTransfers").document(str(claim["claimId"]))
    client = getattr(state_ref, "_client", None)
    amount = _d(claim.get("amount"))

    def apply(transaction: Any | None = None) -> dict[str, Any]:
        state = (state_ref.get().to_dict() or {}) if transaction is None else (state_ref.get(transaction=transaction).to_dict() or {})
        current = state.get("inFlight")
        if not isinstance(current, dict) or current.get("claimId") != claim.get("claimId"):
            return state
        pending = _d(state.get("pendingSavings"))
        next_pending = max(Decimal("0"), pending - amount)
        today_key = _local_day_key()
        today_total = _d(state.get("todayTransferred")) if str(state.get("todayKey", "")) == today_key else Decimal("0")
        next_today = today_total + amount
        update = {
            "pendingSavings": _plain(next_pending),
            "todayTransferred": _plain(next_today),
            "todayKey": today_key,
            "inFlight": None,
            "lastTransferAt": _now(),
            "lastTransferAmount": _plain(amount),
            "updatedAt": _now(),
        }
        transfer_update = {
            "status": "SUCCEEDED",
            "providerTransactionId": str(tran_id),
            "providerStatus": "SUCCESS",
            "reconciledFromHistory": bool(reconciled),
            "completedAt": _now(),
        }
        if transaction is None:
            state_ref.set(update, merge=True)
            transfer_ref.set(transfer_update, merge=True)
        else:
            transaction.set(state_ref, update, merge=True)
            transaction.set(transfer_ref, transfer_update, merge=True)
        return {**state, **update}

    if client is None:
        return apply()
    @firestore.transactional
    def run(transaction: Any) -> dict[str, Any]:
        return apply(transaction)
    return run(client.transaction())


def _execute_buffer_claim(prepared: PreparedSweep, claim: dict[str, Any], *, client: Any) -> dict[str, Any]:
    amount = _d(claim.get("amount"))
    submitted_at = claim.get("submittedAt")
    if submitted_at is not None:
        state, record = reconcile_transfer_history(
            client=client,
            amount=amount,
            submitted_at=submitted_at,
            asset=prepared.transfer_asset,
            poll_attempts=2,
            poll_delay_seconds=0.25,
        )
        if record is not None:
            next_state = _complete_claim(
                prepared, claim, tran_id=str(record.get("tranId", "")), reconciled=True,
            )
            return {"status": "SUCCEEDED", "state": next_state, "reconciled": True}
        if state in {"AMBIGUOUS", "AMBIGUOUS_SPOT", "HISTORY_UNAVAILABLE", "SPOT_HISTORY_TRUNCATED", "FUTURES_HISTORY_TRUNCATED"}:
            _mark_claim(prepared, claim, status="UNCERTAIN", reconciliationStatus=state)
            return {"status": "UNCERTAIN", "reconciliationStatus": state}

    account = client.account_information()
    safe, reason, projection = transfer_safety(account, amount)
    if not safe:
        _mark_claim(prepared, claim, status="BLOCKED_MARGIN", reason=reason, marginSafety=projection)
        return {"status": "BLOCKED_MARGIN", "reason": reason}

    if not live_enabled():
        _mark_claim(prepared, claim, status="BLOCKED_GLOBAL_GATE")
        return {"status": "BLOCKED_GLOBAL_GATE"}

    submitted_at = _now()
    claim = _mark_claim(prepared, claim, status="SUBMITTING", submittedAt=submitted_at)
    try:
        payload = client.signed_spot_request("POST", TRANSFER_PATH, {
            "asset": prepared.transfer_asset,
            "amount": _plain(amount),
            "clientTranId": str(claim.get("clientTranId")),
            "kindType": TRANSFER_KIND,
        })
    except (AsterSubmissionUncertain, AsterApiError) as exc:
        message = str(exc)
        state, record = reconcile_transfer_history(
            client=client,
            amount=amount,
            submitted_at=submitted_at,
            asset=prepared.transfer_asset,
            poll_attempts=3,
            poll_delay_seconds=0.35,
        )
        if record is not None:
            next_state = _complete_claim(
                prepared, claim, tran_id=str(record.get("tranId", "")), reconciled=True,
            )
            return {"status": "SUCCEEDED", "state": next_state, "reconciled": True}

        unknown = isinstance(exc, AsterSubmissionUncertain) or _unknown_execution_reason(message)
        if unknown and state == "NOT_FOUND":
            # One immediate idempotent replay is allowed only with the exact same
            # deterministic clientTranId. This restores the proven legacy safety
            # behavior without creating a second logical transfer.
            replay_at = _now()
            claim = _mark_claim(
                prepared, claim, status="RESUBMITTING_SAME_ID",
                replaySubmittedAt=replay_at, reconciliationStatus=state,
            )
            try:
                replay = client.signed_spot_request("POST", TRANSFER_PATH, {
                    "asset": prepared.transfer_asset,
                    "amount": _plain(amount),
                    "clientTranId": str(claim.get("clientTranId")),
                    "kindType": TRANSFER_KIND,
                })
            except (AsterSubmissionUncertain, AsterApiError) as replay_exc:
                replay_state, replay_record = reconcile_transfer_history(
                    client=client,
                    amount=amount,
                    submitted_at=submitted_at,
                    asset=prepared.transfer_asset,
                    poll_attempts=3,
                    poll_delay_seconds=0.35,
                )
                if replay_record is not None:
                    next_state = _complete_claim(
                        prepared, claim, tran_id=str(replay_record.get("tranId", "")), reconciled=True,
                    )
                    return {"status": "SUCCEEDED", "state": next_state, "reconciled": True}
                _mark_claim(
                    prepared, claim, status="UNCERTAIN", reason=str(replay_exc)[:500],
                    reconciliationStatus=replay_state,
                )
                return {"status": "UNCERTAIN", "reconciliationStatus": replay_state}
            if (
                isinstance(replay, dict)
                and str(replay.get("status", "")).upper() == "SUCCESS"
                and replay.get("tranId") not in (None, "")
            ):
                next_state = _complete_claim(prepared, claim, tran_id=str(replay.get("tranId")))
                return {
                    "status": "SUCCEEDED",
                    "state": next_state,
                    "tranId": str(replay.get("tranId")),
                    "replayed": True,
                }
            _mark_claim(prepared, claim, status="UNCERTAIN", reason="Aster replay bevestigde geen SUCCESS + tranId")
            return {"status": "UNCERTAIN", "reconciliationStatus": state}

        retry_status = "UNCERTAIN" if unknown else "RETRYABLE"
        _mark_claim(
            prepared, claim, status=retry_status, reason=message[:500], reconciliationStatus=state,
        )
        return {"status": retry_status, "reconciliationStatus": state}

    if not isinstance(payload, dict) or str(payload.get("status", "")).upper() != "SUCCESS" or payload.get("tranId") in (None, ""):
        _mark_claim(prepared, claim, status="UNCERTAIN", reason="Aster bevestigde geen SUCCESS + tranId")
        return {"status": "UNCERTAIN"}

    next_state = _complete_claim(prepared, claim, tran_id=str(payload.get("tranId")))
    return {"status": "SUCCEEDED", "state": next_state, "tranId": str(payload.get("tranId"))}


def drain_profit_savings_buffer(prepared: PreparedSweep, *, client: Any, max_blocks: int = 20) -> dict[str, Any]:
    """Drain whole threshold blocks; the remainder stays persistent."""
    transferred = Decimal("0")
    transfer_count = 0
    last_status = "BUFFERED"
    for _ in range(max(1, int(max_blocks))):
        claim = _claim_threshold_transfer(prepared)
        if claim is None:
            break
        result = _execute_buffer_claim(prepared, claim, client=client)
        last_status = str(result.get("status", "BUFFERED"))
        if last_status != "SUCCEEDED":
            break
        amount = _d(claim.get("amount"))
        transferred += amount
        transfer_count += 1
    _, state = _state_snapshot(prepared)
    today_key = _local_day_key()
    today_total = _d(state.get("todayTransferred")) if str(state.get("todayKey", "")) == today_key else Decimal("0")
    return {
        "status": "SUCCEEDED" if transfer_count else last_status,
        "transferred": _plain(transferred),
        "transferCount": transfer_count,
        "pendingSavings": _plain(_d(state.get("pendingSavings"))),
        "todayTransferred": _plain(today_total),
    }


def reconcile_profit_savings_buffer(
    *,
    uid: str,
    user_ref: Any,
    client: Any,
    max_blocks: int = 20,
) -> dict[str, Any]:
    """Minute-scheduler reconciliation for an already persisted Profit Pot buffer.

    This never invents a contribution. It only retries/reconciles full threshold
    blocks that were previously booked from confirmed positive realized closes.
    """
    control = user_ref.collection("executionControls").document("aster").get().to_dict() or {}
    settings = control.get("profitSweep") if isinstance(control.get("profitSweep"), dict) else {}
    if settings.get("enabled") is not True:
        return {"status": "OFF", "transferred": "0"}
    try:
        percent = normalize_sweep_percent(settings.get("sweepPercent", 25))
    except ProfitSweepError:
        return {"status": "INVALID_SETTINGS", "transferred": "0"}
    if percent <= 0:
        return {"status": "OFF", "transferred": "0"}
    asset = str(settings.get("transferAsset", DEFAULT_TRANSFER_ASSET)).upper().strip()
    if asset not in SUPPORTED_TRANSFER_ASSETS:
        asset = DEFAULT_TRANSFER_ASSET
    threshold = _d(settings.get("minimumTransfer", DEFAULT_MINIMUM_TRANSFER))
    if threshold <= 0:
        threshold = DEFAULT_MINIMUM_TRANSFER

    # A synthetic ledger reference is supplied only to satisfy the immutable
    # PreparedSweep shape. Reconciliation/drain never writes close accounting.
    prepared = PreparedSweep(
        uid=uid,
        sweep_id="buffer-reconcile",
        intent_id="buffer-reconcile",
        client_tran_id="",
        symbol="",
        position_side="",
        sweep_percent=percent,
        transfer_asset=asset,
        minimum_transfer=threshold,
        user_ref=user_ref,
        ledger_ref=user_ref.collection("asterProfitSweeps").document("_buffer_reconcile"),
        open_quantity=Decimal("0"),
        entry_commission_pool=Decimal("0"),
        cycle_start_ms=0,
        negative_funding=Decimal("0"),
        evidence_entry_fees=Decimal("0"),
        evidence_funding=Decimal("0"),
        evidence_other_costs=Decimal("0"),
    )
    return drain_profit_savings_buffer(prepared, client=client, max_blocks=max_blocks)


def finalize_close_sweep(
    prepared: PreparedSweep | None,
    *,
    client: Any,
    confirmed_order: dict[str, Any],
    evidence: CloseEvidence | None = None,
) -> dict[str, Any] | None:
    """Book a positive realized-profit share and transfer only complete threshold blocks."""
    if prepared is None:
        return None
    ref = prepared.ledger_ref
    order_id = str(confirmed_order.get("orderId", "")).strip()
    if not order_id:
        ref.set({"status": "BLOCKED_EVIDENCE", "reason": "Aster bevestigde geen orderId", "updatedAt": _now()}, merge=True)
        return None

    try:
        target: list[dict[str, Any]] = []
        for attempt in range(6):
            rows = client.user_trades(
                prepared.symbol,
                start_time=max(0, prepared.cycle_start_ms - 1000),
                limit=1000,
            )
            if len(rows) >= 1000:
                raise ProfitSweepError("Sluitfillhistorie is begrensd")
            target = [row for row in rows if str(row.get("orderId", "")) == order_id]
            if target:
                break
            if attempt < 5:
                time.sleep(0.25)
        if not target:
            raise ProfitSweepError("Aster-sluitfills zijn na bevestiging nog niet zichtbaar")

        net, detail = net_realized_for_order(
            target_fills=target,
            position_side=prepared.position_side,
            pre_open_quantity=prepared.open_quantity,
            pre_entry_commission_pool=prepared.entry_commission_pool,
            negative_funding=prepared.negative_funding,
            evidence=evidence,
        )
        contribution = sweep_contribution(net, prepared.sweep_percent, enabled=True)
        ref.set({
            "status": "CALCULATED",
            "exchangeOrderId": order_id,
            "netRealizedProfit": _plain(net),
            "sweepContribution": _plain(contribution),
            "minimumTransfer": _plain(prepared.minimum_transfer),
            "calculation": detail,
            "calculatedAt": _now(),
        }, merge=True)
        if contribution <= 0:
            ref.set({"status": "SKIPPED_NONPOSITIVE", "completedAt": _now()}, merge=True)
            return {"status": "SKIPPED_NONPOSITIVE", "contribution": "0"}

        booked = _book_contribution(prepared, contribution)
        drained = drain_profit_savings_buffer(prepared, client=client)
        ref.set({
            "status": "BUFFERED",
            "pendingSavingsAfter": drained.get("pendingSavings"),
            "todayTransferredAfter": drained.get("todayTransferred"),
            "thresholdTransferStatus": drained.get("status"),
            "updatedAt": _now(),
        }, merge=True)
        return {
            "status": "BUFFERED",
            "contribution": _plain(contribution),
            "alreadyBooked": bool(booked.get("alreadyBooked")),
            **drained,
        }
    except Exception as exc:
        ref.set({"status": "FAILED_INTERNAL", "reason": str(exc)[:500], "updatedAt": _now()}, merge=True)
        return {"status": "FAILED_INTERNAL"}
