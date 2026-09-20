"""Fail-closed automatic Profit Pot transfers for confirmed Aster closes.

A sweep may only use positive realized net profit.  The implementation snapshots
per-user settings before the close, proves actual realized PnL/fees from Aster
fills, projects cross-margin safety after the transfer, and sends at most one
FUTURE_SPOT transfer for a deterministic close id.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import hashlib
import math
import os
import time
from typing import Any

from google.api_core import exceptions as google_exceptions

from aster_close_guard import CloseEvidence
from aster_dynamic_hedge import DynamicHedgeConfig
from aster_gateway import AsterApiError, AsterSubmissionUncertain
from profit_sweep import ProfitSweepError, normalize_sweep_percent, sweep_contribution

LIVE_ENV = "ASTER_PROFIT_SWEEP_LIVE_ENABLED"
TRANSFER_PATH = "/api/v3/asset/wallet/transfer"
SPOT_TRANSACTION_HISTORY_PATH = "/api/v3/transactionHistory"
SPOT_TRANSFER_HISTORY_TYPE = "TRANSFER_FUTURE_TO_SPOT"
TRANSFER_KIND = "FUTURE_SPOT"
TRANSFER_ASSET = "USDT"
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
    master_address: str
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
    asset = str(row.get("commissionAsset", TRANSFER_ASSET)).upper().strip()
    if asset not in {"", TRANSFER_ASSET}:
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
        if str(row.get("asset", "")).upper() != TRANSFER_ASSET:
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
        if str(row.get("asset", "")).upper() != TRANSFER_ASSET:
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
) -> tuple[str, dict[str, Any] | None]:
    spot_state, spot_match = _spot_transfer_history_match(
        spot_rows, amount=amount, submitted_at=submitted_at,
    )
    if spot_match is not None or spot_state == "AMBIGUOUS_SPOT":
        return spot_state, spot_match
    future_state, future_match = _transfer_history_match(
        futures_rows, amount=amount, submitted_at=submitted_at,
    )
    if future_match is not None or future_state == "AMBIGUOUS":
        return future_state, future_match
    return "NOT_FOUND", None


def reconcile_transfer_history(
    *,
    client: Any,
    amount: Decimal,
    submitted_at: Any,
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
                "asset": TRANSFER_ASSET,
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
) -> dict[str, Any]:
    state, record = reconcile_transfer_history(
        client=client,
        amount=contribution,
        submitted_at=submitted_at,
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
    if settings.get("enabled") is not True:
        return None
    try:
        percent = normalize_sweep_percent(settings.get("sweepPercent", 25))
    except ProfitSweepError:
        return None
    if percent <= 0:
        return None
    master = str(control.get("masterAddress", "")).strip().lower()
    if not (master.startswith("0x") and len(master) == 42):
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
        "asset": TRANSFER_ASSET,
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
            master_address=master,
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


def finalize_close_sweep(
    prepared: PreparedSweep | None,
    *,
    client: Any,
    confirmed_order: dict[str, Any],
    evidence: CloseEvidence | None = None,
) -> dict[str, Any] | None:
    """Transfer only after Aster confirmed the close and every safety gate passes."""
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
            "calculation": detail,
            "calculatedAt": _now(),
        }, merge=True)
        if contribution <= 0:
            ref.set({"status": "SKIPPED_NONPOSITIVE", "completedAt": _now()}, merge=True)
            return {"status": "SKIPPED_NONPOSITIVE", "contribution": "0"}

        account = client.account_information()
        safe, reason, projection = transfer_safety(account, contribution)
        ref.set({"marginSafety": projection, "marginSafetyReason": reason, "updatedAt": _now()}, merge=True)
        if not safe:
            ref.set({"status": "BLOCKED_MARGIN", "completedAt": _now()}, merge=True)
            return {"status": "BLOCKED_MARGIN", "reason": reason}
        if not live_enabled():
            ref.set({"status": "BLOCKED_GLOBAL_GATE", "completedAt": _now()}, merge=True)
            return {"status": "BLOCKED_GLOBAL_GATE"}

        submitted_at = _now()
        ref.set({"status": "SUBMITTING", "submittedAt": submitted_at}, merge=True)
        try:
            # Aster documents perp->spot as a Spot TRADE endpoint. Using the
            # Futures host produced repeated -1006 unknown-execution responses.
            # Submit through the approved API-wallet signer on Spot V3.
            payload = client.signed_spot_request("POST", TRANSFER_PATH, {
                "asset": TRANSFER_ASSET,
                "amount": _plain(contribution),
                "clientTranId": prepared.client_tran_id,
                "kindType": TRANSFER_KIND,
            })
        except AsterSubmissionUncertain as exc:
            # -1006, -1007 and HTTP 503 explicitly mean execution status
            # unknown. Reconcile read-only history first and never blind-retry.
            return _uncertain_result(
                ref=ref,
                reason=str(exc),
                client=client,
                contribution=contribution,
                submitted_at=submitted_at,
            )
        except AsterApiError as exc:
            # Defensive compatibility for older clients that still surface
            # Aster's unknown-execution codes as a regular API error.
            message = str(exc)
            if "-1006" in message or "-1007" in message or "execution status unknown" in message.lower():
                return _uncertain_result(
                    ref=ref,
                    reason=message,
                    client=client,
                    contribution=contribution,
                    submitted_at=submitted_at,
                )
            ref.set({"status": "FAILED_EXCHANGE", "reason": message[:500], "completedAt": _now()}, merge=True)
            return {"status": "FAILED_EXCHANGE"}

        if not isinstance(payload, dict) or str(payload.get("status", "")).upper() != "SUCCESS" or payload.get("tranId") in (None, ""):
            return _uncertain_result(
                ref=ref,
                reason="Aster bevestigde geen SUCCESS + tranId",
                client=client,
                contribution=contribution,
                submitted_at=submitted_at,
            )
        ref.set({
            "status": "SUCCEEDED",
            "providerTransactionId": str(payload.get("tranId")),
            "providerStatus": "SUCCESS",
            "completedAt": _now(),
        }, merge=True)
        return {
            "status": "SUCCEEDED",
            "contribution": _plain(contribution),
            "tranId": str(payload.get("tranId")),
        }
    except Exception as exc:
        ref.set({"status": "FAILED_INTERNAL", "reason": str(exc)[:500], "updatedAt": _now()}, merge=True)
        return {"status": "FAILED_INTERNAL"}
