from __future__ import annotations

from pathlib import Path

from profit_notifications import latest_portfolio_tp_from_state


def test_no_state_means_no_portfolio_tp():
    assert latest_portfolio_tp_from_state(None) is None
    assert latest_portfolio_tp_from_state({}) is None
    assert latest_portfolio_tp_from_state({"multiBbCycle": {"cycleId": "c1", "cycleStatus": "RUNNING"}}) is None


def test_executing_cycle_is_reported_at_trigger_moment():
    state = {"multiBbCycle": {"cycleId": "c2", "cycleStatus": "PORTFOLIO_TP_EXECUTING", "portfolioTpTriggeredAtMs": 5000},
             "multiBbLastCompletedCycle": {"cycleId": "c1", "portfolioTpTriggeredAtMs": 1000}}
    result = latest_portfolio_tp_from_state(state)
    assert result == {"cycleId": "c2", "phase": "EXECUTING", "occurredAtMs": 5000, "cycleProfitUsd": None}


def test_completed_cycle_keeps_same_cycle_id_as_trigger():
    # Same cycleId during EXECUTING and after COMPLETED: the web app plays only once per Portfolio TP.
    state = {"multiBbCycle": {"cycleId": "c3", "cycleStatus": "RUNNING"},
             "multiBbLastCompletedCycle": {"cycleId": "c2", "portfolioTpTriggeredAtMs": 5000, "flatConfirmedAtMs": 9000,
                                           "cycleStartEquity": 100.0, "cycleEndEquity": 110.5}}
    result = latest_portfolio_tp_from_state(state)
    assert result["cycleId"] == "c2" and result["phase"] == "COMPLETED"
    assert result["occurredAtMs"] == 5000
    assert abs(result["cycleProfitUsd"] - 10.5) < 1e-9


def test_completed_without_trigger_time_falls_back_to_flat_time():
    state = {"multiBbLastCompletedCycle": {"cycleId": "c9", "flatConfirmedAtMs": 7000}}
    assert latest_portfolio_tp_from_state(state)["occurredAtMs"] == 7000


def test_recent_endpoint_is_read_only_and_exposes_latest_portfolio_tp():
    source = Path(__file__).with_name("profit_notifications.py").read_text()
    start = source.index("def latest_portfolio_tp(self")
    block = source[start:source.index("def _active_subscriptions", start)]
    assert ".get()" in block
    for forbidden in (".set(", ".update(", ".add(", ".delete(", "submit_order", "cancel_order"):
        assert forbidden not in block
    assert '"latestPortfolioTp": service.latest_portfolio_tp(uid)' in source
