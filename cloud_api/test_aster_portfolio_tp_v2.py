from __future__ import annotations

from pathlib import Path

import pytest

from aster_multi_bb import MultiBbConfig
from aster_multi_bb_portfolio import (
    ensure_cycle,
    portfolio_cycle_gate,
    reset_cycle_to_equity,
    target_equity_v2,
)
from test_aster_portfolio_tp_mode import FakeClient, Ref, pos


def test_percent_and_usd_math_matches_product_examples():
    assert target_equity_v2(92.27, "PERCENT", 2.0) == pytest.approx(94.1154)
    assert target_equity_v2(92.27, "PERCENT", 0.25) == pytest.approx(92.500675)
    assert target_equity_v2(92.27, "USD", 5.0) == pytest.approx(97.27)
    assert target_equity_v2(135.55, "PERCENT", 0.35) == pytest.approx(136.024425)


def test_legacy_percent_settings_migrate_without_user_action():
    cfg = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1",
        "portfolioTpPercent": 0.35,
    })
    assert cfg.portfolio_tp_input_mode == "PERCENT"
    assert cfg.portfolio_tp_value == pytest.approx(0.35)
    assert cfg.portfolio_tp_base_mode == "CYCLE_START"
    public = cfg.public_dict()
    assert public["portfolioTpInputMode"] == "PERCENT"
    assert public["portfolioTpValue"] == pytest.approx(0.35)


def test_current_value_base_is_snapshotted_once_per_config_version():
    raw = {"multiBbCycle": {
        "cycleId": "abc",
        "cycleStartEquity": 135.55,
        "cycleStatus": "RUNNING",
    }}
    first, changed = ensure_cycle(
        raw,
        uid="u",
        current_equity=92.27,
        portfolio_tp_percent=2.0,
        portfolio_tp_input_mode="PERCENT",
        portfolio_tp_value=2.0,
        portfolio_tp_base_mode="CURRENT_VALUE",
        config_version=11,
        timestamp_ms=1,
    )
    assert changed is True
    assert first["cycleStartEquity"] == pytest.approx(135.55)
    assert first["baseEquity"] == pytest.approx(92.27)
    assert first["targetEquity"] == pytest.approx(94.1154)

    second_raw = {"multiBbCycle": first}
    second, changed_again = ensure_cycle(
        second_raw,
        uid="u",
        current_equity=93.00,
        portfolio_tp_percent=2.0,
        portfolio_tp_input_mode="PERCENT",
        portfolio_tp_value=2.0,
        portfolio_tp_base_mode="CURRENT_VALUE",
        config_version=11,
        timestamp_ms=2,
    )
    assert changed_again is False
    assert second["baseEquity"] == pytest.approx(92.27)
    assert second["targetEquity"] == pytest.approx(94.1154)


def test_custom_base_and_usd_mode_are_independent_from_cycle_start():
    raw = {"multiBbCycle": {
        "cycleId": "abc",
        "cycleStartEquity": 135.55,
        "cycleStatus": "RUNNING",
    }}
    cycle, changed = ensure_cycle(
        raw,
        uid="u",
        current_equity=92.27,
        portfolio_tp_percent=0.35,
        portfolio_tp_input_mode="USD",
        portfolio_tp_value=5.0,
        portfolio_tp_base_mode="CUSTOM",
        portfolio_tp_custom_base_equity=100.0,
        config_version=7,
        timestamp_ms=1,
    )
    assert changed is True
    assert cycle["cycleStartEquity"] == pytest.approx(135.55)
    assert cycle["baseEquity"] == pytest.approx(100.0)
    assert cycle["targetEquity"] == pytest.approx(105.0)


def test_manual_reset_helper_uses_current_equity_and_sends_no_orders():
    cycle = reset_cycle_to_equity(
        uid="u",
        current_equity=92.27,
        portfolio_tp_percent=2.0,
        portfolio_tp_input_mode="PERCENT",
        portfolio_tp_value=2.0,
        config_version=12,
        timestamp_ms=100,
    )
    assert cycle["cycleStartEquity"] == pytest.approx(92.27)
    assert cycle["baseEquity"] == pytest.approx(92.27)
    assert cycle["targetEquity"] == pytest.approx(94.1154)
    assert cycle["baselineSource"] == "MANUAL_RESET_CURRENT_EQUITY"


def test_percent_gate_triggers_once_at_threshold_and_restarts_from_actual_close_equity():
    raw = {
        "enabled": True,
        "settings": {
            "takeProfitMode": "PORTFOLIO",
            "portfolioTpPercent": 2.0,
            "portfolioTpInputMode": "PERCENT",
            "portfolioTpValue": 2.0,
            "portfolioTpBaseMode": "CYCLE_START",
        },
        "multiBbCycle": {
            "cycleId": "abc",
            "cycleStartEquity": 92.27,
            "baseEquity": 92.27,
            "baseMode": "CYCLE_START",
            "baseConfigVersion": 1,
            "takeProfitInputMode": "PERCENT",
            "takeProfitValue": 2.0,
            "targetEquity": 94.1154,
            "cycleStatus": "RUNNING",
        },
    }
    ref = Ref(raw)
    client = FakeClient(equity=94.11, positions=[pos("BTCUSDT", "LONG")])
    before = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw, uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[],
        timestamp_ms=1, take_profit_mode="PORTFOLIO", portfolio_tp_percent=2.0,
        portfolio_tp_input_mode="PERCENT", portfolio_tp_value=2.0, config_version=1,
    )
    assert before.handled is False
    assert client.submissions == []

    client.equity = 94.12
    at_target_raw = ref.get().to_dict()
    hit = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=at_target_raw, uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[],
        timestamp_ms=2, take_profit_mode="PORTFOLIO", portfolio_tp_percent=2.0,
        portfolio_tp_input_mode="PERCENT", portfolio_tp_value=2.0, config_version=1,
    )
    assert hit.handled is True and hit.restart is True
    assert len(client.submissions) == 1
    # FakeClient realizes +17.42 on close. The new baseline must be actual
    # post-close equity, never the theoretical 94.1154 target.
    expected_post_close = 94.12 + 17.42
    assert ref.data["multiBbCycle"]["cycleStartEquity"] == pytest.approx(expected_post_close)
    assert ref.data["multiBbCycle"]["baseEquity"] == pytest.approx(expected_post_close)
    assert ref.data["multiBbCycle"]["targetEquity"] == pytest.approx(expected_post_close * 1.02)
    assert ref.data["settings"]["portfolioTpBaseMode"] == "CYCLE_START"


def test_usd_mode_technical_replay_multiple_cycles():
    """Deterministic equity replay/backtest of cycle mechanics, not performance."""
    cycle_start = 100.0
    take_profit = 5.0
    traces = [
        ([101.0, 103.0, 104.99, 105.0], 104.91),
        ([105.2, 107.0, 109.90, 109.91], 109.84),
        ([110.0, 112.4, 114.83, 114.84], 114.75),
    ]
    hits = 0
    for equity_path, post_close in traces:
        target = target_equity_v2(cycle_start, "USD", take_profit)
        assert all(value < target for value in equity_path[:-1])
        assert equity_path[-1] >= target
        hits += 1
        cycle_start = post_close
    assert hits == 3
    assert target_equity_v2(cycle_start, "USD", take_profit) == pytest.approx(119.75)


def test_reset_route_is_read_only_at_exchange_layer_and_has_zero_order_contract():
    source = Path("main.py").read_text()
    start = source.index('@app.post("/v1/me/aster/strategy2/portfolio-cycle/reset")')
    end = source.index("\n\n@app.", start + 1)
    block = source[start:end]
    assert "live_authorized=False" in block
    assert '"ordersSent": 0' in block
    assert "multiBbPositions" not in block
    assert "execute_aster" not in block
    assert "submit_order" not in block
    assert "cancel_order" not in block


def test_settings_save_snapshots_current_value_server_side_with_read_only_exchange_access():
    source = Path("main.py").read_text()
    start = source.index('@app.put("/v1/me/aster/strategy2/settings")')
    end = source.index('\n\n@app.post("/v1/me/aster/strategy2/portfolio-cycle/reset")', start)
    block = source[start:end]
    assert 'saved.portfolio_tp_base_mode=="CURRENT_VALUE"' in block
    assert "live_authorized=False" in block
    assert "multi_bb_exchange_equity(read_client.account_information())" in block
    assert "ensure_multi_bb_portfolio_cycle(" in block
    assert '"multiBbCycle"' in block
    assert '"multiBbPositions":{}' not in block.split("else:", 1)[-1]
