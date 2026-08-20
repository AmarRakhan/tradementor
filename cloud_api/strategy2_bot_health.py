"""Unified read-only Bot Health projection for Strategy 2 and Money Grabber.

This module never places, closes or resizes orders. It converts persisted runtime
state into deterministic health/recovery metadata for the dashboard and monitor.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from admin_platform import classify_bot_health, safe_recovery_plan


def _iso(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _money_grabber(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("moneyGrabber") if isinstance(state.get("moneyGrabber"), dict) else {}
    enabled = bool(raw.get("enabled", state.get("moneyGrabberEnabled", False)))
    return {
        "enabled": enabled,
        "roundStatus": str(raw.get("roundStatus", raw.get("status", "INACTIVE" if not enabled else "UNKNOWN"))),
        "roundId": str(raw.get("roundId", "")),
        "lastScanAt": _iso(raw.get("lastScanAt")),
        "lastAction": str(raw.get("lastAction", "NONE")),
        "lastReason": str(raw.get("lastReason", "")),
        "plannedActions": int(raw.get("plannedActions", 0) or 0),
        "executedActions": int(raw.get("executedActions", 0) or 0),
        "blockedActions": int(raw.get("blockedActions", 0) or 0),
    }


def build_strategy2_bot_health(state: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Return one stable dashboard contract from persisted Strategy-2 runtime state."""
    now = now or datetime.now(timezone.utc)
    health = classify_bot_health(state, now=now)
    recovery = safe_recovery_plan(state, health, now=now)
    scheduler_age = None
    tick = state.get("lastTickAt")
    if isinstance(tick, datetime):
        current = tick if tick.tzinfo else tick.replace(tzinfo=timezone.utc)
        scheduler_age = max(0, int((now - current.astimezone(timezone.utc)).total_seconds()))
    return {
        "status": health.status,
        "category": health.category,
        "severity": health.severity,
        "summary": health.summary,
        "strategy": "strategy_2",
        "phase": str(state.get("phase", "UNKNOWN")),
        "lastSuccessfulScanAt": _iso(state.get("lastSuccessfulScanAt", state.get("lastTickAt"))),
        "lastTickAt": _iso(state.get("lastTickAt")),
        "schedulerAgeSeconds": scheduler_age,
        "lastAction": str(state.get("lastAction", "NONE")),
        "lastActionAt": _iso(state.get("lastActionAt")),
        "lastReason": str(state.get("lastReason", "")),
        "lastErrorCode": str(state.get("lastErrorCode", "")),
        "takeProfitCandidates": int(state.get("takeProfitCandidates", 0) or 0),
        "entryCandidates": int(state.get("entryCandidates", 0) or 0),
        "blockedCandidates": int(state.get("blockedCandidates", 0) or 0),
        "recovery": {
            "eligible": bool(recovery),
            "safeActions": recovery,
            "lastResult": str(state.get("lastRecoveryResult", "")),
            "lastRecoveredAt": _iso(state.get("lastRecoveredAt")),
        },
        "moneyGrabber": _money_grabber(state),
    }
