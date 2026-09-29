from __future__ import annotations

from pathlib import Path
import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from profit_notification_replay import replay_portfolio_tp, replay_profit_events
from profit_notifications import (
    aggregate_profit_events,
    completed_window_for_event,
    entry_push_payload,
    normalize_settings,
    notifiable_entry_action,
    portfolio_tp_push_payload,
    qualifying_profit,
    summary_push_payload,
    trade_push_payload,
    _vapid_private_der_b64,
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
    assert value["longEntryNotificationsEnabled"] is False
    assert value["shortEntryNotificationsEnabled"] is False
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


def test_entry_push_payload_is_immediate_and_contains_confirmed_entry_context():
    payload = entry_push_payload(
        {
            "eventId": "entry-1",
            "entryIdentity": "order-123",
            "symbol": "HYPEUSDT",
            "side": "LONG",
            "strategy": "Zone Warriors",
            "entryPrice": 42.18,
            "sizeUsd": 25.0,
        },
        {"portfolioValue": 347.26, "available": 214.80},
    )
    assert payload["type"] == "position_entry"
    assert payload["title"] == "🟢 LONG geopend · HYPE"
    assert "Instap: $42,18" in payload["body"]
    assert "Grootte: $25,00" in payload["body"]
    assert "Strategie: Zone Warriors" in payload["body"]
    assert "Portfolio: $347,26" in payload["body"]
    assert "Available: $214,80" in payload["body"]


@pytest.mark.parametrize("action", [
    "INITIAL_OPEN_LEG",
    "OPEN_LEG",
    "AUTO_RESTART",
    "PENDING_REOPEN",
])
def test_normal_new_position_actions_are_entry_notification_eligible(action):
    assert notifiable_entry_action(action) is True


@pytest.mark.parametrize("action", [
    "ADD_DCA",
    "PROTECTION_INCREASE",
    "OPEN_PROTECTION",
    "AUTO_HEDGE",
    "HEDGE_ADJUST",
    "RECOVERY",
    "HEDGE_REBALANCE",
    "FULL_TP",
    "PARTIAL_TP",
])
def test_dca_protection_hedge_recovery_and_close_actions_are_not_entry_notifications(action):
    assert notifiable_entry_action(action) is False


def test_entry_opt_in_has_side_specific_start_timestamp_to_prevent_backfill():
    source = Path("profit_notifications.py").read_text()
    assert '"longEntryEnabledAtMs"' in source
    assert '"shortEntryEnabledAtMs"' in source
    assert "notification_start = max(enabled_at, side_enabled_at)" in source
    assert "BEFORE_ENTRY_NOTIFICATIONS_ENABLED" in source


def test_entry_settings_are_backwards_compatible_for_older_clients():
    source = Path("profit_notifications.py").read_text()
    assert 'normalize_settings({**previous, **source})' in source
    assert 'request.model_dump(exclude_unset=True)' in source


def test_entry_notification_observer_requires_confirmed_fill_and_proven_normal_attribution():
    source = Path("main.py").read_text()
    start = source.index("def _reconcile_profit_notifications")
    end = source.index("\ndef require_verified_email", start)
    block = source[start:end]
    assert 'entries = activity.get("entries")' in block
    assert "entry_by_order_id" in block
    assert "entry_by_client_order_id" in block
    assert "notifiable_entry_action" in block
    assert "record_entry_event" in block
    assert "Fail closed" in block
    assert "live_authorized=False" in block
    assert "execute_aster" not in block
    assert "submit_order" not in block


def test_entry_notification_service_is_persistent_idempotent_and_independent_of_profit_summary_mode():
    source = Path("profit_notifications.py").read_text()
    assert '"longEntryNotificationsEnabled": False' in source
    assert '"shortEntryNotificationsEnabled": False' in source
    assert '"type": "POSITION_ENTRY"' in source
    assert 'key = "|".join(("entry"' in source
    assert 'dispatch_key = f"entry:' in source
    assert "_already_dispatched(uid, dispatch_key)" in source
    assert "_create_event(uid, key" in source
    entry_dispatch = source[source.index('for reference, row in [item for item in rows if str(item[1].get("type")) == "POSITION_ENTRY"]'):]
    entry_dispatch = entry_dispatch[:entry_dispatch.index('for reference, row in [item for item in rows if str(item[1].get("type")) == "PORTFOLIO_TP"]')]
    assert "deliveryMode" not in entry_dispatch
    assert "intervalMinutes" not in entry_dispatch


def test_portfolio_tp_payload_is_separate_and_immediate_shape():
    payload = portfolio_tp_push_payload(
        {"eventId": "p", "cycleId": "cycle", "cycleProfitUsd": 5.25},
        {"portfolioValue": 105.25, "available": 92.10},
    )
    assert payload["type"] == "portfolio_take_profit"
    assert "Portfolio Take Profit behaald" in payload["title"]
    assert "+$5,25" in payload["body"]


def test_multi_bb_persists_confirmed_entry_and_tp_order_attribution_for_notifications():
    source = Path("aster_multi_bb_core.py").read_text()
    assert "def _record_order_attribution" in source
    assert 'action="OPEN_LEG"' in source
    assert 'action="TAKE_PROFIT_CLOSE"' in source
    assert '"orderAttributions": rows[-2000:]' in source
    assert "closed.get(\"result\") or {}" in source
    assert "ref, fill, settings=settings" in source


def test_notification_reconcile_keeps_durable_symbol_backlog_until_history_read_succeeds():
    source = Path("main.py").read_text()
    start = source.index("def _reconcile_profit_notifications")
    end = source.index("\ndef require_verified_email", start)
    block = source[start:end]
    assert 'state.get("pendingHistorySymbols")' in block
    assert "event_symbols = list(dict.fromkeys([" in block
    assert "event_batch = event_symbols[:8]" in block
    assert "failed_history_symbols.add(symbol)" in block
    assert "remaining_history_symbols" in block
    assert "if not remaining_history_symbols" in block
    assert "pendingHistorySymbols=remaining_history_symbols[:100]" in block
    assert "historyScanIncomplete=bool(remaining_history_symbols)" in block
    assert 'status": "ok" if not remaining_history_symbols else "retry-pending"' in block
    assert "last_reconciled - 10 * 60_000" in block
    assert "last_reconciled - 10 * 60_000, now_ms - 24 * 60 * 60_000" not in block


def test_notification_reconcile_pages_income_and_fill_history_without_500_row_loss():
    source = Path("main.py").read_text()
    assert "def _notification_realized_income" in source
    assert 'income_type="REALIZED_PNL"' in source
    assert "page_size = 1000" in source
    assert "next_cursor = max(timestamps) + 1" in source
    start = source.index("def _reconcile_profit_notifications")
    end = source.index("\ndef require_verified_email", start)
    block = source[start:end]
    assert "recent_income = _notification_realized_income(client, start_ms)" in block
    assert "rows = paged_user_trades(" in block
    assert "start_time=start_ms or None" in block
    assert "page_size=500" in block
    assert "maximum_pages=20" in block


def test_delayed_paired_short_recovery_is_also_attributed_as_a_short_entry():
    source = Path("aster_multi_bb_core.py").read_text()
    recovery_start = source.index('actions.append({"kind": "ASYM_SHORT_RECOVERY"')
    recovery_end = source.index("# A soldier released by TP", recovery_start)
    block = source[recovery_start:recovery_end]
    assert "_record_order_attribution(" in block
    assert 'side="SHORT"' in block
    assert 'action="OPEN_LEG"' in block


def test_confirmed_tp_attribution_is_urgent_even_if_realized_income_is_delayed():
    source = Path("main.py").read_text()
    start = source.index("def _reconcile_profit_notifications")
    end = source.index("\ndef require_verified_email", start)
    block = source[start:end]
    assert '"TAKE_PROFIT_CLOSE"' in block
    assert "close_notification_actions" in block
    assert "symbol not in priority_symbols" in block


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


def test_vapid_pem_is_converted_to_der_base64_before_pywebpush():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    encoded = _vapid_private_der_b64(pem)
    assert "BEGIN PRIVATE KEY" not in encoded
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    der = base64.urlsafe_b64decode(encoded + padding)
    restored = serialization.load_der_private_key(der, password=None)
    assert isinstance(restored, ec.EllipticCurvePrivateKey)
    assert restored.private_numbers().private_value == key.private_numbers().private_value


def test_pywebpush_never_receives_raw_pem_text():
    source = Path("profit_notifications.py").read_text()
    assert 'vapid_private_key=vapid["privatePem"]' not in source
    assert "vapid_private_key=vapid_private_key" in source
    assert "_vapid_private_der_b64" in source


def test_test_push_title_has_no_bot_brand_text():
    source = Path("profit_notifications.py").read_text()
    assert '"title": "🧪 Testmelding"' in source
    assert '"title": "🧪 Testmelding · Amar Crypto Bot 2026"' not in source


def test_notification_reconcile_includes_all_realized_symbols_even_when_ledger_fragment_is_nonpositive():
    source = Path("main.py").read_text()
    start = source.index("def _reconcile_profit_notifications")
    end = source.index("\ndef require_verified_email", start)
    block = source[start:end]
    assert 'str(row.get("incomeType", "REALIZED_PNL")).upper() != "REALIZED_PNL"' in block
    assert 'if safe_float(row.get("income")) <= 0:' not in block
    assert "pendingHistorySymbols" in block
    assert "remaining_history_symbols" in block
    assert "historyScanIncomplete" in block
