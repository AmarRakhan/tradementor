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


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _integer(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _money_grabber(state: dict[str, Any]) -> dict[str, Any]:
    public = _mapping(state.get("moneyGrabber"))
    settings = _mapping(state.get("settings"))
    round_state = _mapping(state.get("moneyGrabberRound"))
    shadow = _mapping(state.get("moneyGrabberSchedulerShadow"))
    pairs = _rows(state.get("moneyGrabberPairs"))
    actions = _rows(shadow.get("actions"))
    reasons = [str(reason) for reason in shadow.get("reasons", []) if str(reason)] if isinstance(
        shadow.get("reasons"), list
    ) else []
    blocked_symbols = [
        str(symbol) for symbol in shadow.get("blockedSymbols", []) if str(symbol)
    ] if isinstance(shadow.get("blockedSymbols"), list) else []

    enabled = bool(
        public.get(
            "enabled",
            state.get(
                "moneyGrabberEnabled",
                settings.get("moneyGrabberEnabled", settings.get("money_grabber_enabled", False)),
            ),
        )
    )
    activated = bool(public.get("activated", state.get("moneyGrabberActivated", False)))
    execution_enabled = bool(state.get("moneyGrabberExecutionEnabled", False))
    round_status = str(
        shadow.get(
            "roundStatus",
            public.get(
                "roundStatus",
                public.get(
                    "status",
                    round_state.get("status", "INACTIVE" if not enabled else "NOT_STARTED"),
                ),
            ),
        )
    )
    first_action = actions[0] if actions else {}
    protected_pairs = sum(
        str(pair.get("status", "")).upper()
        in {
            "PARTIAL_PROTECTION",
            "LOCKED",
            "PROTECTION_PENDING",
            "FULL_PROTECTION_PENDING",
            "PAIR_CLOSE_PENDING",
        }
        for pair in pairs
    )
    last_reason = str(
        public.get(
            "lastReason",
            reasons[-1] if reasons else state.get("lastReason", ""),
        )
    )

    return {
        "enabled": enabled,
        "activated": activated,
        "executionEnabled": execution_enabled,
        "readOnly": bool(shadow.get("readOnly", not execution_enabled)),
        "roundStatus": round_status,
        "roundId": str(public.get("roundId", round_state.get("roundId", ""))),
        "startNetValue": round_state.get("startNetValue"),
        "targetNetValue": round_state.get("targetNetValue"),
        "lastScanAt": _iso(
            public.get("lastScanAt", state.get("moneyGrabberShadowAt"))
        ),
        "lastAction": str(
            public.get("lastAction", first_action.get("kind", "NONE"))
        ),
        "lastReason": last_reason,
        "plannedActions": _integer(
            public.get(
                "plannedActions",
                shadow.get("wouldSendCount", len(actions)),
            )
        ),
        "executedActions": _integer(
            public.get(
                "executedActions",
                state.get("moneyGrabberExecutedActions", shadow.get("ordersSent", 0)),
            )
        ),
        "blockedActions": _integer(
            public.get(
                "blockedActions",
                shadow.get("blockedActions", len(blocked_symbols)),
            )
        ),
        "protectedPairs": protected_pairs,
        "blockedSymbols": blocked_symbols,
    }


def build_strategy2_bot_health(
    state: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Return one stable dashboard contract from persisted Strategy-2 runtime state."""
    now = now or datetime.now(timezone.utc)
    health = classify_bot_health(state, now=now)
    recovery = safe_recovery_plan(state, health, now=now)
    scheduler_age = None
    tick = state.get("lastTickAt")
    if isinstance(tick, datetime):
        current = tick if tick.tzinfo else tick.replace(tzinfo=timezone.utc)
        scheduler_age = max(
            0, int((now - current.astimezone(timezone.utc)).total_seconds())
        )

    return {
        "status": health.status,
        "category": health.category,
        "severity": health.severity,
        "summary": health.summary,
        "strategy": "strategy_2",
        "phase": str(state.get("phase", "UNKNOWN")),
        "lastSuccessfulScanAt": _iso(
            state.get("lastSuccessfulScanAt", state.get("lastTickAt"))
        ),
        "lastTickAt": _iso(state.get("lastTickAt")),
        "schedulerAgeSeconds": scheduler_age,
        "lastAction": str(state.get("lastAction", "NONE")),
        "lastActionAt": _iso(state.get("lastActionAt")),
        "lastReason": str(state.get("lastReason", "")),
        "lastErrorCode": str(state.get("lastErrorCode", "")),
        "takeProfitCandidates": _integer(state.get("takeProfitCandidates")),
        "entryCandidates": _integer(state.get("entryCandidates")),
        "blockedCandidates": _integer(state.get("blockedCandidates")),
        "recovery": {
            "eligible": bool(recovery),
            "safeActions": recovery,
            "lastResult": str(state.get("lastRecoveryResult", "")),
            "lastRecoveredAt": _iso(state.get("lastRecoveredAt")),
        },
        "moneyGrabber": _money_grabber(state),
    }


def merge_strategy2_bot_health(
    legacy: dict[str, Any],
    state: dict[str, Any],
    *,
    account_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Extend the established endpoint without breaking its existing fields."""
    projection = build_strategy2_bot_health(state, now=now)
    return {
        **legacy,
        "accountId": account_id,
        "operationalStatus": projection["status"],
        "summary": projection["summary"],
        "health": projection,
        "moneyGrabber": projection["moneyGrabber"],
        "recovery": projection["recovery"],
    }
