from datetime import datetime, timedelta, timezone

from strategy2_bot_health import (
    build_strategy2_bot_health,
    merge_strategy2_bot_health,
)


def test_recent_strategy2_and_money_grabber_health() -> None:
    now = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    state = {
        "enabled": True,
        "monitor": True,
        "phase": "RUNNING",
        "lastTickAt": now - timedelta(seconds=30),
        "lastSuccessfulScanAt": now - timedelta(seconds=30),
        "lastAction": "FULL_TP",
        "lastReason": "Scan afgerond",
        "takeProfitCandidates": 2,
        "settings": {"moneyGrabberEnabled": True},
        "moneyGrabberActivated": True,
        "moneyGrabberRound": {
            "roundId": "round-1",
            "status": "RUNNING",
            "startNetValue": 100.0,
            "targetNetValue": 105.0,
        },
        "moneyGrabberSchedulerShadow": {
            "readOnly": True,
            "roundStatus": "RUNNING",
            "wouldSendCount": 1,
            "ordersSent": 0,
            "actions": [{"kind": "PROTECT", "symbol": "BTCUSDT"}],
            "blockedSymbols": ["BTCUSDT"],
            "reasons": ["Money Grabber-scan veilig gepland"],
        },
        "moneyGrabberShadowAt": now - timedelta(seconds=15),
        "moneyGrabberPairs": [
            {"symbol": "BTCUSDT", "status": "PARTIAL_PROTECTION"}
        ],
    }

    result = build_strategy2_bot_health(state, now=now)

    assert result["status"] == "healthy"
    assert result["schedulerAgeSeconds"] == 30
    assert result["takeProfitCandidates"] == 2
    assert result["moneyGrabber"]["enabled"] is True
    assert result["moneyGrabber"]["activated"] is True
    assert result["moneyGrabber"]["roundStatus"] == "RUNNING"
    assert result["moneyGrabber"]["plannedActions"] == 1
    assert result["moneyGrabber"]["executedActions"] == 0
    assert result["moneyGrabber"]["protectedPairs"] == 1
    assert result["moneyGrabber"]["lastAction"] == "PROTECT"


def test_stale_scheduler_has_only_safe_recovery_actions() -> None:
    now = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    state = {
        "enabled": True,
        "monitor": True,
        "phase": "RUNNING",
        "lastTickAt": now - timedelta(minutes=31),
        "leaseUntil": now - timedelta(minutes=1),
    }

    result = build_strategy2_bot_health(state, now=now)

    assert result["status"] == "action_required"
    assert result["category"] == "stale_scheduler"
    assert set(result["recovery"]["safeActions"]) == {
        "release_stale_lease",
        "request_reconciliation",
    }
    forbidden = {
        "place_order",
        "close_position",
        "resize_position",
        "restart_bot",
    }
    assert forbidden.isdisjoint(result["recovery"]["safeActions"])


def test_disabled_money_grabber_is_inactive() -> None:
    now = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    result = build_strategy2_bot_health(
        {
            "enabled": True,
            "monitor": True,
            "phase": "RUNNING",
            "lastTickAt": now,
            "settings": {"moneyGrabberEnabled": False},
        },
        now=now,
    )

    assert result["moneyGrabber"]["enabled"] is False
    assert result["moneyGrabber"]["activated"] is False
    assert result["moneyGrabber"]["roundStatus"] == "INACTIVE"


def test_missing_tick_is_fail_closed() -> None:
    result = build_strategy2_bot_health(
        {"enabled": True, "monitor": True, "phase": "RUNNING"}
    )

    assert result["status"] == "action_required"
    assert result["category"] == "missing_data"
    assert result["schedulerAgeSeconds"] is None
    assert result["recovery"]["safeActions"] == []


def test_merge_preserves_legacy_contract() -> None:
    now = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    legacy = {
        "status": "OK",
        "yourBot": {"found": 0},
        "platform": {"activeBots": 4},
        "incidents": [],
    }
    state = {
        "enabled": True,
        "monitor": True,
        "phase": "RUNNING",
        "lastTickAt": now,
    }

    result = merge_strategy2_bot_health(
        legacy, state, account_id="immutable-account-id", now=now
    )

    assert result["status"] == "OK"
    assert result["yourBot"] == {"found": 0}
    assert result["accountId"] == "immutable-account-id"
    assert result["operationalStatus"] == "healthy"
    assert result["health"]["strategy"] == "strategy_2"
    assert result["moneyGrabber"]["roundStatus"] == "INACTIVE"
