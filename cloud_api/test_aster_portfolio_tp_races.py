from __future__ import annotations

from pathlib import Path

from aster_gateway import PositionSide
from aster_multi_bb_portfolio import PORTFOLIO_TP_EXECUTING, portfolio_cycle_gate
from test_aster_portfolio_tp_mode import FakeClient, Ref, pos


def test_per_trade_save_wins_if_stale_portfolio_worker_has_not_transitioned_yet():
    raw = {
        "enabled": True,
        "settings": {"takeProfitMode": "PER_TRADE", "portfolioTpPercent": 20},
        "multiBbCycle": {"cycleId": "abc", "cycleStartEquity": 1000, "cycleStatus": "RUNNING"},
    }
    ref = Ref(raw)
    client = FakeClient(equity=1250, positions=[pos("BTCUSDT", "LONG")])
    result = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw, uid="u", account=client.account_information(),
        positions=client.position_risk(), open_orders=[], timestamp_ms=10,
        # Worker-local snapshot is stale; durable config is already PER_TRADE.
        take_profit_mode="PORTFOLIO", portfolio_tp_percent=20,
    )
    assert result.handled is False
    assert client.positions
    assert client.submissions == []
    assert ref.data["multiBbCycle"]["cycleStatus"] == "RUNNING"


def test_once_portfolio_exit_is_durable_it_finishes_even_if_mode_is_changed():
    raw = {
        "enabled": True,
        "settings": {"takeProfitMode": "PER_TRADE", "portfolioTpPercent": 20},
        "multiBbCycle": {"cycleId": "abc", "cycleStartEquity": 1000, "cycleStatus": PORTFOLIO_TP_EXECUTING},
    }
    ref = Ref(raw)
    client = FakeClient(equity=1210, positions=[pos("BTCUSDT", "LONG"), pos("ETHUSDT", "SHORT")])
    result = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw, uid="u", account=client.account_information(),
        positions=client.position_risk(), open_orders=[], timestamp_ms=11,
        take_profit_mode="PER_TRADE", portfolio_tp_percent=20,
    )
    assert result.handled is True
    assert result.restart is True
    assert client.positions == []
    assert {intent.position_side for intent in client.submissions} == {PositionSide.LONG, PositionSide.SHORT}


def test_main_settings_route_preserves_active_multi_bb_state_and_immediately_evaluates_portfolio_switch():
    source = Path("main.py").read_text()
    start = source.index('@app.put("/v1/me/aster/strategy2/settings")')
    end = source.index("\n\n@app.", start + 1)
    block = source[start:end]
    assert "activeStatePreserved" in block
    assert "settingsChangedAt" in block
    assert "_run_aster_strategy2_queue_scan(uid,maximum_orders=MAX_ORDERS_PER_ACCOUNT_SCAN)" in block
    assert "_run_aster_strategy2_tick(uid)" in block
    # These resets are allowed only inside the explicit engine-migration branch.
    assert "if switching:" in block
    assert "else:" in block
    assert "actieve positie-, DCA- en cycle-state behouden" in block


def test_stop_keeps_monitoring_only_while_transactional_portfolio_exit_is_unfinished():
    source = Path("main.py").read_text()
    start = source.index('@app.post("/v1/me/aster/strategy2/stop")')
    end = source.index("\n\n@app.", start + 1)
    block = source[start:end]
    assert 'exit_in_progress=cycle_status in {"PORTFOLIO_TP_EXECUTING","FLAT_CONFIRMING"}' in block
    assert '"enabled":False,"monitor":exit_in_progress' in block
    assert "finishingPortfolioExit" in block
    assert "FLAT_CONFIRMED" in block


def test_queue_does_not_misclassify_stopped_but_closing_portfolio_as_flat():
    source = Path("main.py").read_text()
    assert "portfolio_exit_active" in source
    assert "and not portfolio_exit_active" in source


def test_bot_off_flat_confirmation_disables_monitor_permanently():
    source = Path("aster_multi_bb_portfolio.py").read_text()
    assert 'extra={**base_extra, "monitor": False}' in source

def test_portfolio_tp_preempts_dynamic_hedge_and_is_never_suppressed():
    source = Path("main.py").read_text()
    tick = source[source.index("def _run_aster_strategy2_tick("):]
    preempt = tick.index("# Portfolio TP is the account-level risk reset")
    dynamic = tick.index("dynamic=run_dynamic_hedge_sequence")
    assert preempt < dynamic
    assert 'portfolio_cycle_gate(' in tick[preempt:dynamic]
    assert 'take_profit_mode="OFF"' not in tick[preempt:dynamic + 5000]
    assert '"portfolioTpSuppressed":False' in tick


def test_portfolio_tp_close_bypasses_only_auto_hedge_quantity_lock():
    source = Path("main.py").read_text()
    start = source.index("def _block_strategy2_order_during_conflict")
    end = source.index("\n\ndef ", start + 1)
    block = source[start:end]
    assert 'str(intent.intent_id).lower().startswith("mbb-ptp-")' in block
    assert '_block_order_during_close_all(uid,allow_auto_hedge_locked=True)' in block
    assert 'normal_close_guard=_block_order_during_close_all(uid)' in block


def test_dynamic_hedge_order_guard_never_owns_portfolio_tp_close():
    source = Path("main.py").read_text()
    start = source.index("def _run_aster_strategy2_tick(")
    block = source[start:source.index("# Realtime Simple Mode legacy runtime below", start)]
    assert "if not is_portfolio_tp_close:" in block
    assert "dynamic_strategy_order_guard(dynamic_ref,intent,account,positions)" in block

