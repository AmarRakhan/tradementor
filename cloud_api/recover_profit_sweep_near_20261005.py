"""One-time 2026-10-05 recovery for the blocked NEAR Profit Sweep close.

Strictly scoped: one exact blocked sweep + one exact manual close intent on the
single enabled 5% USDC account. It only credits pendingSavings; no Spot transfer.
"""
from __future__ import annotations

from decimal import Decimal
import json
import os
import urllib.request

import main
from aster_gateway import AsterV3Client
from aster_signing import local_eip712_signer
from profit_sweep_live import recover_blocked_close_to_buffer

TARGET_SWEEP_ID = "80d8198a086ad7390c9af8a5fb67d8a98ac231e8c4ac53a16c46a257e712e2f8"
TARGET_MANUAL_INTENT_ID = "cf291df1a8c0350097f6e55d409f49c75a4bf1846637bff550e845af0ee70fb8"
TARGET_SYMBOL = "NEARUSDT"
TARGET_SIDE = "LONG"
TARGET_PERCENTAGE = 50
TARGET_ORDER_ID = "1253216610"
TARGET_EXPECTED_QTY = Decimal("43")
TARGET_CLOSED_QTY = Decimal("21")
TARGET_ASSET = "USDC"
TARGET_SWEEP_PERCENT = Decimal("5")


def _d(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _post_result(payload: dict) -> None:
    token = os.environ.get("RECOVERY_GH_TOKEN", "")
    repo = os.environ.get("RECOVERY_REPO", "")
    if not token or not repo:
        return
    body = "PROFIT_SWEEP_NEAR_RECOVERY_20261005 " + json.dumps(payload, separators=(",", ":"), sort_keys=True)
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/41/comments",
        data=json.dumps({"body": body}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "tradementor-profit-sweep-recovery",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"GitHub result report failed: {response.status}")


def main_once() -> None:
    matches = []
    for user_snap in main.db.collection("users").stream():
        user_ref = user_snap.reference
        control = user_ref.collection("executionControls").document("aster").get().to_dict() or {}
        settings = control.get("profitSweep") if isinstance(control.get("profitSweep"), dict) else {}
        if settings.get("enabled") is not True:
            continue
        if str(settings.get("transferAsset", "")).upper() != TARGET_ASSET:
            continue
        if _d(settings.get("sweepPercent", 0)) != TARGET_SWEEP_PERCENT:
            continue

        ledger_ref = user_ref.collection("asterProfitSweeps").document(TARGET_SWEEP_ID)
        ledger = ledger_ref.get().to_dict() or {}
        if not ledger:
            continue
        matches.append((user_snap, user_ref, settings, ledger))

    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one guarded recovery account, found {len(matches)}")

    user_snap, user_ref, settings, ledger = matches[0]
    if str(ledger.get("status", "")).upper() not in {"BLOCKED_EVIDENCE", "BUFFERED"}:
        raise RuntimeError(f"Unexpected sweep status: {ledger.get('status')}")
    if str(ledger.get("symbol", "")).upper() != TARGET_SYMBOL:
        raise RuntimeError("Sweep symbol guard failed")
    if str(ledger.get("positionSide", "")).upper() != TARGET_SIDE:
        raise RuntimeError("Sweep side guard failed")
    if _d(ledger.get("sweepPercent", 0)) != TARGET_SWEEP_PERCENT:
        raise RuntimeError("Sweep percentage guard failed")
    if str(ledger.get("asset", "")).upper() != TARGET_ASSET:
        raise RuntimeError("Sweep asset guard failed")

    intent = user_ref.collection("asterManualCloseIntents").document(TARGET_MANUAL_INTENT_ID).get().to_dict() or {}
    if str(intent.get("status", "")).lower() != "confirmed_closed":
        raise RuntimeError("Manual close was not exchange-confirmed")
    if str(intent.get("symbol", "")).upper() != TARGET_SYMBOL or str(intent.get("side", "")).upper() != TARGET_SIDE:
        raise RuntimeError("Manual close identity guard failed")
    if int(intent.get("percentage", 0) or 0) != TARGET_PERCENTAGE:
        raise RuntimeError("Manual close percentage guard failed")
    if _d(intent.get("expectedQuantity", 0)) != TARGET_EXPECTED_QTY:
        raise RuntimeError("Manual close pre-close quantity guard failed")
    if _d(intent.get("closedQuantity", 0)) != TARGET_CLOSED_QTY:
        raise RuntimeError("Manual close closed quantity guard failed")
    result_outer = intent.get("result") if isinstance(intent.get("result"), dict) else {}
    result_order = result_outer.get("result") if isinstance(result_outer.get("result"), dict) else {}
    if str(result_order.get("orderId", "")) != TARGET_ORDER_ID:
        raise RuntimeError("Manual close exchange order guard failed")

    state_ref = user_ref.collection("asterProfitSweepState").document("current")
    before_state = state_ref.get().to_dict() or {}
    before_pending = _d(before_state.get("pendingSavings", 0))

    user = {"uid": user_snap.id}
    secret = main.load_aster_secret(user)
    client = AsterV3Client(
        signer_address=secret.signer_address,
        sign_message=local_eip712_signer(secret),
        live_authorized=False,
    )
    result = recover_blocked_close_to_buffer(
        uid=user_snap.id,
        user_ref=user_ref,
        client=client,
        sweep_id=TARGET_SWEEP_ID,
        exchange_order_id=TARGET_ORDER_ID,
        expected_pre_close_quantity=TARGET_EXPECTED_QTY,
        recovery_reason="TODAY_BLOCKED_EVIDENCE_BACKFILL",
    )

    after_state = state_ref.get().to_dict() or {}
    after_pending = _d(after_state.get("pendingSavings", 0))
    final_ledger = user_ref.collection("asterProfitSweeps").document(TARGET_SWEEP_ID).get().to_dict() or {}

    if result.get("status") not in {"BUFFERED", "ALREADY_BOOKED"}:
        raise RuntimeError(f"Recovery did not buffer profit: {result}")
    if result.get("status") == "BUFFERED" and after_pending <= before_pending:
        raise RuntimeError("Recovery did not increase pendingSavings")
    if str(result.get("transferred", "0")) not in {"", "0"}:
        raise RuntimeError("One-time recovery must not transfer to Spot")
    if final_ledger.get("bufferBooked") is not True:
        raise RuntimeError("Recovered ledger is not idempotently bufferBooked")

    payload = {
        "status": str(result.get("status")),
        "symbol": TARGET_SYMBOL,
        "side": TARGET_SIDE,
        "percentage": TARGET_PERCENTAGE,
        "orderId": TARGET_ORDER_ID,
        "beforePending": format(before_pending, "f"),
        "contribution": str(final_ledger.get("sweepContribution", result.get("contribution", "0"))),
        "afterPending": format(after_pending, "f"),
        "spotTransferExecuted": False,
        "recoveredProfitSweep": bool(final_ledger.get("recoveredProfitSweep")),
        "recoveryReason": str(final_ledger.get("recoveryReason", "")),
    }
    print("PROFIT_SWEEP_NEAR_RECOVERY_20261005=" + json.dumps(payload, separators=(",", ":"), sort_keys=True))
    _post_result(payload)


if __name__ == "__main__":
    main_once()
