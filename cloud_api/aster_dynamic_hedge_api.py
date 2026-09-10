"""Server-owned Dynamic Hedge state/adoption API.

This installer is intentionally fail-closed. Monitoring and ownership adoption
are available independently of live order execution. A risk-adding execution
path must pass a separately planned projected-margin gate before it can be wired
into the scheduler.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Callable

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from aster_cross_risk import cross_account_risk
from aster_dynamic_hedge import DynamicHedgeConfig, assess_dynamic_hedge, robust_hedge_coverage


class DynamicHedgeToggleRequest(BaseModel):
    enabled: bool
    confirm: bool = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat()
    return str(value) if value not in (None, "") else None


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and abs(result) != float("inf") else 0.0


def _position_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        qty = abs(_number(row.get("positionAmt", row.get("quantity"))))
        if qty <= 0:
            continue
        side = str(row.get("positionSide", row.get("side", ""))).upper()
        symbol = str(row.get("symbol", "")).upper()
        mark = _number(row.get("markPrice")) or _number(row.get("entryPrice"))
        if not symbol or side not in {"LONG", "SHORT"} or mark <= 0:
            continue
        positions.append({
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "markPrice": mark,
            "entryPrice": _number(row.get("entryPrice")),
            "leverage": int(_number(row.get("leverage")) or 1),
            "notionalUsd": qty * mark,
        })
    positions.sort(key=lambda item: (item["symbol"], item["side"]))
    return positions


def _fingerprint(positions: list[dict[str, Any]], open_orders: list[dict[str, Any]]) -> str:
    payload = {
        "positions": [
            {"symbol": p["symbol"], "side": p["side"], "quantity": round(float(p["quantity"]), 12)}
            for p in positions
        ],
        "openOrders": sorted(
            (str(row.get("symbol", "")).upper(), str(row.get("positionSide", "")).upper(), str(row.get("orderId", row.get("clientOrderId", ""))))
            for row in open_orders if isinstance(row, dict)
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def install_aster_dynamic_hedge_routes(
    app: Any,
    *,
    authenticated_user: Callable[..., Any],
    user_reference: Callable[[dict[str, Any]], Any],
    client_factory: Callable[[dict[str, Any], bool], Any],
) -> None:
    policy = DynamicHedgeConfig().validated()

    def ref(user: dict[str, Any]):
        return user_reference(user).collection("asterDynamicHedge").document("control")

    def read_exchange(user: dict[str, Any]) -> dict[str, Any]:
        client = client_factory(user, False)
        try:
            account = client.account_information()
            rows = client.position_risk()
            orders = client.open_orders()
        except Exception as exc:
            raise HTTPException(502, "Actuele Aster margin-/positiedata kon niet betrouwbaar worden gelezen") from exc
        if not isinstance(account, dict) or not isinstance(rows, list) or not isinstance(orders, list):
            raise HTTPException(502, "Aster gaf onvolledige margin-/positiedata terug")
        positions = _position_payload(rows)
        risk = cross_account_risk(account, rows)
        return {
            "account": account,
            "positions": positions,
            "openOrders": orders,
            "risk": risk,
            "fingerprint": _fingerprint(positions, orders),
            "capturedAt": _now(),
        }

    def exposure_from_risk(risk: dict[str, Any], positions: list[dict[str, Any]]) -> dict[str, Any]:
        long_value = _number(risk.get("longNotional"))
        short_value = _number(risk.get("shortNotional"))
        net = long_value - short_value
        return {
            "reliable": bool(risk.get("reliable", False)) and len(positions) == int(risk.get("positionCountIncluded", len(positions))),
            "longExposureUsd": long_value,
            "shortExposureUsd": short_value,
            "netExposureUsd": net,
            "netSide": "FLAT" if abs(net) < 1e-9 else ("LONG" if net > 0 else "SHORT"),
            "grossExposureUsd": long_value + short_value,
            "hedgeCoveragePercent": robust_hedge_coverage(long_value, short_value),
            "openPositionCount": len(positions),
            "longPositionCount": sum(item["side"] == "LONG" for item in positions),
            "shortPositionCount": sum(item["side"] == "SHORT" for item in positions),
        }

    def public_state(user: dict[str, Any], *, allow_reconcile: bool = True) -> dict[str, Any]:
        stored = ref(user).get().to_dict() or {}
        try:
            exchange = read_exchange(user)
        except HTTPException:
            return {
                "reliable": False,
                "monitoringAlwaysActive": True,
                "enabled": bool(stored.get("enabled", False)),
                "ownershipState": "ADOPTING" if stored.get("enabled") else "NORMAL",
                "engineState": "DATA_UNRELIABLE",
                "safetyStatus": "DATA_ONBETROUWBAAR",
                "reasonCode": "EXCHANGE_RISK_DATA_UNRELIABLE",
                "lastAction": str(stored.get("lastAction", "MONITORING")),
                "lastActionAt": _iso(stored.get("lastActionAt")),
                "generatedAt": _now().isoformat(),
                "executionGateOpen": False,
            }
        risk = exchange["risk"]
        positions = exchange["positions"]
        exposure = exposure_from_risk(risk, positions)
        enabled = bool(stored.get("enabled", False))
        owner = str(stored.get("ownershipState", "NORMAL" if not enabled else "ADOPTING")).upper()
        stored_fp = str(stored.get("positionFingerprint", ""))
        current_fp = str(exchange["fingerprint"])
        stable_reads = int(_number(stored.get("stableReads")))
        changed = bool(enabled and stored_fp and stored_fp != current_fp)
        update: dict[str, Any] = {}
        if enabled and allow_reconcile:
            if changed:
                owner = "ADOPTING"
                stable_reads = 1
                update = {
                    "ownershipState": owner,
                    "positionFingerprint": current_fp,
                    "stableReads": stable_reads,
                    "adoptedPositionCount": len(positions),
                    "lastReason": "Exchange-state wijzigde; Dynamic Hedge adopteert opnieuw vóór een nieuwe actie",
                    "lastAction": "ADOPTION_RECONCILE",
                    "lastActionAt": _now(),
                    "updatedAt": _now(),
                }
            elif owner == "ADOPTING":
                stable_reads += 1
                if stable_reads >= 2:
                    owner = "DYNAMIC_HEDGE_ACTIVE"
                    update = {
                        "ownershipState": owner,
                        "stableReads": stable_reads,
                        "positionFingerprint": current_fp,
                        "adoptedPositionCount": len(positions),
                        "lastReason": "Bestaande Aster-posities stabiel gereconcilieerd; Dynamic Hedge ownership actief",
                        "lastAction": "ADOPTION_CONFIRMED",
                        "lastActionAt": _now(),
                        "updatedAt": _now(),
                    }
                else:
                    update = {"stableReads": stable_reads, "positionFingerprint": current_fp, "updatedAt": _now()}
            elif not stored_fp:
                owner = "ADOPTING"
                update = {"ownershipState": owner, "stableReads": 1, "positionFingerprint": current_fp, "adoptedPositionCount": len(positions), "updatedAt": _now()}
            if update:
                ref(user).set(update, merge=True)
                stored = {**stored, **update}
        if not enabled:
            owner = "NORMAL"
        assessment = assess_dynamic_hedge(
            enabled=enabled,
            ownership_state=owner,
            exposure=exposure,
            risk=risk,
            candidate=None,
            config=policy,
        )
        execution_gate = os.getenv("ASTER_DYNAMIC_HEDGE_EXECUTION_ENABLED", "false").lower() == "true"
        if enabled and owner == "DYNAMIC_HEDGE_ACTIVE" and not execution_gate:
            assessment = {**assessment, "engineState": "AUTOMATION_PAUSED", "reasonCode": "LIVE_EXECUTION_GATE_CLOSED", "riskAddingAllowed": False}
        margin_balance = _number(risk.get("equity"))
        maintenance = _number(risk.get("maintenanceMarginUsd"))
        return {
            **assessment,
            "reliable": bool(assessment.get("reliable")) and bool(risk.get("reliable")),
            "monitoringAlwaysActive": True,
            "enabled": enabled,
            "ownershipState": owner,
            "adoptedPositionCount": int(stored.get("adoptedPositionCount", len(positions)) or 0),
            "positionFingerprint": current_fp,
            "positionCount": len(positions),
            "longPositionCount": exposure["longPositionCount"],
            "shortPositionCount": exposure["shortPositionCount"],
            "longExposureUsd": exposure["longExposureUsd"],
            "shortExposureUsd": exposure["shortExposureUsd"],
            "netExposureUsd": exposure["netExposureUsd"],
            "netSide": exposure["netSide"],
            "grossExposureUsd": exposure["grossExposureUsd"],
            "hedgeCoveragePercent": exposure["hedgeCoveragePercent"],
            "equity": margin_balance,
            "marginBalance": _number(risk.get("marginBalance")) or margin_balance,
            "maintenanceMarginUsd": maintenance,
            "marginBufferUsd": risk.get("marginBufferUsd"),
            "bufferRatio": risk.get("bufferRatio"),
            "liquidationRiskPct": risk.get("liquidationRiskPct"),
            "liquidationRiskSource": risk.get("liquidationRiskSource"),
            "safetyStatus": risk.get("liquidationSafetyStatus", assessment.get("safetyStatus")),
            "openOrderCount": len(exchange["openOrders"]),
            "executionGateOpen": execution_gate,
            "lastAction": str(stored.get("lastAction", "MONITORING")),
            "lastActionAt": _iso(stored.get("lastActionAt")),
            "lastReason": str(stored.get("lastReason", assessment.get("reasonCode", "MONITORING_ONLY"))),
            "policy": policy.public_dict(),
            "capturedAt": _iso(exchange["capturedAt"]),
            "generatedAt": _now().isoformat(),
        }

    @app.get("/v1/me/aster/dynamic-hedge/state")
    def dynamic_hedge_state(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        return public_state(user)

    @app.put("/v1/me/aster/dynamic-hedge/enabled")
    def dynamic_hedge_enabled(request: DynamicHedgeToggleRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        if not request.confirm:
            raise HTTPException(422, "Bevestig de wijziging van Dynamic Hedge expliciet")
        if request.enabled:
            exchange = read_exchange(user)
            if not bool(exchange["risk"].get("reliable", False)):
                raise HTTPException(409, "Dynamic Hedge kan niet starten zonder betrouwbare Aster margin-data")
            ref(user).set({
                "enabled": True,
                "ownershipState": "ADOPTING",
                "stableReads": 1,
                "positionFingerprint": exchange["fingerprint"],
                "adoptedPositionCount": len(exchange["positions"]),
                "enabledAt": _now(),
                "lastAction": "ADOPTION_STARTED",
                "lastActionAt": _now(),
                "lastReason": "Bestaande posities worden overgenomen; er is geen positie gesloten of opnieuw geopend",
                "updatedAt": _now(),
            }, merge=True)
        else:
            ref(user).set({
                "enabled": False,
                "ownershipState": "NORMAL",
                "stableReads": 0,
                "disabledAt": _now(),
                "lastAction": "DYNAMIC_HEDGE_DISABLED",
                "lastActionAt": _now(),
                "lastReason": "Automatisch hedgebeheer gestopt; bestaande posities zijn ongemoeid gelaten",
                "updatedAt": _now(),
            }, merge=True)
        return public_state(user)
