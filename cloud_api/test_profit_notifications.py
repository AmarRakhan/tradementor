from __future__ import annotations

from pathlib import Path

import pytest

from profit_notification_replay import replay_portfolio_tp, replay_profit_events
from profit_notifications import (
    aggregate_profit_events,
    completed_window_for_event,
    normalize_settings,
    portfolio_tp_push_payload,
    qualifying_profit,
    summary_push_payload,
    trade_push_payload,
)


def event(index: int, pnl: float, at_ms: int = 1_000) -> dict:
    return {
        "eventId": f"e-{index}",
        "symbol": "BTCUSDT" if index % 2 == 0 else "ETHUSDT",
        "side": "LONG" if index % 2 == 0 else "SHORT",
        "realizedNetPnlUsd": pnl,
        "occurredAtMs": at_ms + index,
    }


def test_defaults_are_opt_in_and_summary_30_min():
    value = normalize_settings({})
    assert value["enabled"] is False
    assert value["tradeProfitEnabled"] is True
    assert value["mode"] == "SUMMARY"
    assert value["intervalMinutes"] == 30
    assert value["minimumProfitUsd"] == pytest.approx(0.50)
    assert value["portfolioTpEnabled"] is True
    assert value["refreshBalancesAtDispatch"] is True


@pytest.mark.parametrize("pnl,expected", [
    (-1.0, False),
    (0.0, False),
    (0.11, False),
    (0.49, False),
    (0.50, True),
    (0.51, True),
    (4.0, True),
])
def test_minimum_profit_boundary(pnl, expected):
    assert qualifying_profit(pnl, 0.50) is expected


def test_one_win_produces_one_completed_summary():
    rows = [event(1, 1.25, 60_000)]
    result = replay_profit_events(rows, interval_minutes=30, now_ms=1_800_001)
    assert result["pushCount"] == 1
    assert result["summaries"][0]["count"] == 1
    assert result["summaries"][0]["totalProfitUsd"] == pytest.approx(1.25)


def test_47_wins_collapse_to_one_summary_with_max_count_and_sum():
    rows = [event(index, 0.50 + index / 100, 100_000) for index in range(47)]
    result = replay_profit_events(rows, interval_minutes=30, now_ms=1_800_001)
    assert result["pushCount"] == 1
    summary = result["summaries"][0]
    assert summary["count"] == 47
    assert summary["bestProfitUsd"] == pytest.approx(max(row["realizedNetPnlUsd"] for row in rows))
    assert summary["totalProfitUsd"] == pytest.approx(sum(row["realizedNetPnlUsd"] for row in rows))


def test_500_wins_still_produce_exactly_one_summary():
    rows = [event(index, 0.50 + (index % 25) / 100, 100_000) for index in range(500)]
    result = replay_profit_events(rows, interval_minutes=30, now_ms=1_800_001)
    assert result["pushCount"] == 1
    assert result["qualifyingCount"] == 500
    assert result["summaries"][0]["count"] == 500


def test_no_win_loss_and_break_even_produce_no_summary():
    rows = [event(1, -2.0), event(2, 0.0), event(3, 0.49)]
    result = replay_profit_events(rows, interval_minutes=30, now_ms=1_800_001)
    assert result["pushCount"] == 0
    assert result["qualifyingCount"] == 0


def test_incomplete_window_stays_silent_until_window_end():
    start, end = completed_window_for_event(10 * 60_000, 30)
    row = event(1, 2.0, 10 * 60_000)
    assert replay_profit_events([row], interval_minutes=30, now_ms=end - 1)["pushCount"] == 0
    assert replay_profit_events([row], interval_minutes=30, now_ms=end)["pushCount"] == 1
    assert start == 0


def test_duplicate_close_event_is_replayed_once():
    row = event(1, 3.0, 100_000)
    result = replay_profit_events([row, dict(row)], interval_minutes=30, now_ms=1_800_001)
    assert result["duplicates"] == 1
    assert result["pushCount"] == 1
    assert result["summaries"][0]["count"] == 1


def test_every_win_mode_keeps_each_qualifying_close():
    rows = [event(1, 1.0), event(2, 2.0), event(3, -1.0)]
    result = replay_profit_events(rows, mode="EVERY_WIN", minimum_profit_usd=0.50, now_ms=2_000_000)
    assert result["pushCount"] == 2


def test_portfolio_tp_replay_dedupes_one_cycle_even_with_100_close_side_effects():
    ptp = [{"cycleId": "cycle-1", "cycleStartEquity": 100, "cycleEndEquity": 106}] * 100
    result = replay_portfolio_tp(ptp)
    assert result["pushCount"] == 1
    assert result["duplicates"] == 99
    assert result["pushes"][0]["cycleProfitUsd"] == pytest.approx(6.0)


def test_realtime_balance_example_uses_dispatch_values_not_close_snapshot():
    rows = [{
        "eventId": "btc-1007",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "realizedNetPnlUsd": 12.85,
        "occurredAtMs": 10 * 60_000 + 7_000,
        "capturedPortfolioValue": 1276.32,
        "capturedAvailable": 842.17,
    }]
    payload = summary_push_payload(
        rows, 30,
        {"portfolioValue": 1284.74, "available": 854.21},
        0, 30 * 60_000,
    )
    assert payload["data"]["bestProfitUsd"] == pytest.approx(12.85)
    assert payload["data"]["portfolioValue"] == pytest.approx(1284.74)
    assert payload["data"]["available"] == pytest.approx(854.21)
    assert "$1.284,74" in payload["body"]
    assert "$854,21" in payload["body"]


def test_payloads_keep_profit_portfolio_available_and_no_quantity_noise():
    row = event(2, 12.85)
    account = {"portfolioValue": 1276.32, "available": 842.17}
    payload = trade_push_payload(row, account)
    assert "+$12,85" in payload["body"]
    assert "$1.276,32" in payload["body"]
    assert "$842,17" in payload["body"]
    assert "quantity" not in payload["body"].lower()
    assert "leverage" not in payload["body"].lower()


def test_portfolio_tp_payload_is_separate_and_immediate_shape():
    payload = portfolio_tp_push_payload(
        {"eventId": "p", "cycleId": "cycle", "cycleProfitUsd": 5.25},
        {"portfolioValue": 105.25, "available": 92.10},
    )
    assert payload["type"] == "portfolio_take_profit"
    assert "Portfolio Take Profit behaald" in payload["title"]
    assert "+$5,25" in payload["body"]


def test_backend_observer_is_read_only_and_scheduler_failure_isolated():
    source = Path("main.py").read_text()
    start = source.index("def _reconcile_profit_notifications")
    end = source.index("\ndef require_verified_email", start)
    block = source[start:end]
    assert "live_authorized=False" in block
    assert "record_trade_event" in block
    assert "record_portfolio_tp_event" in block
    assert "process_pending" in block
    assert "execute_aster" not in block
    assert "submit_order" not in block
    assert "cancel_order" not in block
    assert '"ordersSent": 0' in block

    scheduler_start = source.index('@app.post("/internal/aster-automation/tick")')
    scheduler_end = source.index('\n\n@app.post("/internal/aster-strategy2/', scheduler_start)
    scheduler = source[scheduler_start:scheduler_end]
    assert "profitNotificationControls" in scheduler
    assert "notification-error" in scheduler
    assert "reference.set({\"phase\":\"DATA_HOLD\"" in scheduler  # strategy failures unchanged
    assert "profitNotifications" in scheduler


def test_notification_module_has_no_execution_imports_or_trade_mutations():
    source = Path("profit_notifications.py").read_text()
    forbidden = [
        "execute_aster_leg",
        "execute_leg_once",
        "submit_order",
        "cancel_order",
        "execute_close_all",
        "change_leverage",
        "change_margin_type",
    ]
    for value in forbidden:
        assert value not in source


def test_replay_module_is_exchange_free():
    source = Path("profit_notification_replay.py").read_text()
    assert "AsterV3Client" not in source
    assert "execute_" not in source
    assert "place_order" not in source


def test_push_provider_failures_are_classified_for_safe_device_repair():
    source = Path("profit_notifications.py").read_text()
    assert "providerStatuses" in source
    assert "PUSH_SUBSCRIPTION_EXPIRED" in source
    assert "PUSH_PROVIDER_AUTH_REJECTED" in source
    assert "{400, 401, 403}" in source
    assert "{404, 410}" in source
    assert "execute_aster" not in source
