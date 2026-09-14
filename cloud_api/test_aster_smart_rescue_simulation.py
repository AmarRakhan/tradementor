from __future__ import annotations

from types import SimpleNamespace
import time

import pytest

import aster_multi_bb
import aster_smart_rescue_runtime as runtime
from aster_multi_bb import run_multi_bb_step
from aster_smart_rescue import advance_state, apply_fill, build_position_state, preview_ladder
from test_aster_multi_bb import Client, Ref
from test_aster_smart_rescue import smart_cfg


def simulate_path(*, prices: list[float], rescue_range: float = 10, dca_count: int = 10,
                  growth: float = 1.2, recovery: float = .3, leverage: int = 50):
    state = build_position_state(initial_entry_price=100, start_margin_usd=.15,
        rescue_range_percent=rescue_range, dca_count=dca_count,
        order_growth_multiplier=growth, trailing_recovery_percent=recovery, config_version=1)
    fills: list[dict] = []
    for tick, price in enumerate(prices, 1):
        state, executable = advance_state(state, mark_price=price)
        if executable is None:
            continue
        margin = float(executable["orderMarginUsd"])
        qty = margin * leverage / price
        fills.append(dict(executable))
        state = apply_fill(state, level_index=int(executable["levelIndex"]), fill_price=price,
            fill_qty=qty, actual_margin_usd=margin, order_id=f"sim-{tick}", timestamp_ms=tick)
    return state, fills


def test_scenario_a_calm_decline_with_rebounds_can_fill_multiple_rescues():
    probe = build_position_state(initial_entry_price=100, start_margin_usd=.15, rescue_range_percent=10,
        dca_count=10, order_growth_multiplier=1.2, trailing_recovery_percent=.3, config_version=1)
    t1 = probe["levels"][0]["triggerPrice"]
    t2 = probe["levels"][1]["triggerPrice"]
    low1 = t1 * .999; low2 = t2 * .999
    state, fills = simulate_path(prices=[100, low1, low1 * 1.0031, low2, low2 * 1.0031])
    assert [row["levelIndex"] for row in fills] == [1, 2]
    assert state["filledCount"] == 2


def test_scenario_b_free_fall_arms_deepest_only_without_buying():
    state, fills = simulate_path(prices=[100, 97, 94, 91, 88], rescue_range=20, dca_count=25)
    assert fills == []
    assert state["armedIndex"] is not None
    assert state["skippedCount"] > 0
    assert sum(1 for row in state["levels"] if row["status"] == "ARMED") == 1


def test_scenario_c_deep_rescue_improves_weighted_entry_on_rebound():
    state = build_position_state(initial_entry_price=100, start_margin_usd=.15, rescue_range_percent=10,
        dca_count=5, order_growth_multiplier=1.35, trailing_recovery_percent=.3, config_version=1)
    state, executable = advance_state(state, mark_price=90)
    assert executable is None
    state, executable = advance_state(state, mark_price=90 * 1.0031)
    assert executable is not None
    margin = float(executable["orderMarginUsd"]); price = 90 * 1.0031; leverage = 50
    start_qty = .15 * leverage / 100
    add_qty = margin * leverage / price
    average = (.15 * leverage + margin * leverage) / (start_qty + add_qty)
    assert price < average < 100
    assert (average / price - 1) * 100 < (100 / price - 1) * 100


def test_scenario_d_rising_market_never_arms_or_buys():
    state, fills = simulate_path(prices=[100, 100.5, 101, 102, 103, 105])
    assert fills == []
    assert state["armedIndex"] is None
    assert state["filledCount"] == 0


def test_scenario_e_full_twenty_percent_ladder_has_finite_final_break_even():
    probe = build_position_state(initial_entry_price=100, start_margin_usd=.15, rescue_range_percent=20,
        dca_count=25, order_growth_multiplier=1.2, trailing_recovery_percent=.3, config_version=1)
    path = [100.0]
    for row in probe["levels"]:
        low = float(row["triggerPrice"]) * .9999
        path.extend([low, low * 1.0031])
    state, fills = simulate_path(prices=path, rescue_range=20, dca_count=25, growth=1.2)
    assert len(fills) == 25
    assert state["filledCount"] == 25 and state["skippedCount"] == 0
    preview = preview_ladder(initial_entry_price=100, start_margin_usd=.15, leverage=50,
        rescue_range_percent=20, dca_count=25, order_growth_multiplier=1.2)
    assert preview["maxMarginUsd"] == pytest.approx(85.1065949796621)
    assert 0 < preview["finalRecoveryToBreakEvenPercent"] < 20


def test_scenario_f_insufficient_margin_waits_without_corrupting_armed_state():
    settings = smart_cfg(maximumPositions=1, longSlots=1, shortSlots=0,
        smartRescueDcaCount=5, smartRescueRangePercent=5, smartRescueTrailingRecoveryPercent=.3)
    smart = build_position_state(initial_entry_price=100, start_margin_usd=.15, rescue_range_percent=5,
        dca_count=5, order_growth_multiplier=1.35, trailing_recovery_percent=.3, config_version=1)
    smart, _ = advance_state(smart, mark_price=99)
    rebound = 99 * 1.0031
    pos = {"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5","entryPrice":"100","markPrice":str(rebound),"leverage":"100"}
    outer = {"cycleId":"margin-wait","dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":5,
        "lastKnownEntry":100,"leverage":100,"cycleStartedAtMs":1,"smartRescue":smart}
    result = runtime.run_gate(client=Client(positions=[pos], prices={"AAAUSDT":rebound}, leverage=100), ref=Ref(),
        raw_state={"multiBbPositions":{"AAAUSDT|LONG":outer}}, settings=settings, uid="u",
        account={"availableBalance":"0.0001"}, positions=[pos], open_orders=[], timestamp_ms=2, dry_run=False)
    assert any(row["kind"] == "SMART_RESCUE_MARGIN_WAIT" for row in result["actions"])
    persisted = result["state"]["AAAUSDT|LONG"]["smartRescue"]
    assert persisted["armedIndex"] is not None
    assert persisted["lastDecision"].startswith("RETRY_")


def test_scenario_g_portfolio_tp_has_priority_over_smart_rescue(monkeypatch):
    settings = smart_cfg(maximumPositions=1, longSlots=1, shortSlots=0, takeProfitMode="PORTFOLIO", portfolioTpPercent=2)
    gate = SimpleNamespace(handled=True, restart=False, report={"cycleStatus":"PORTFOLIO_TP_EXECUTING","ordersSent":1})
    monkeypatch.setattr(aster_multi_bb, "portfolio_cycle_gate", lambda **_kwargs: gate)
    monkeypatch.setattr(aster_multi_bb, "run_smart_rescue_gate", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("Smart Rescue must not run before Portfolio TP")))
    result = run_multi_bb_step(client=Client(), ref=Ref(), raw_state={}, settings=settings, uid="u",
        account={"availableBalance":"100"}, positions=[], open_orders=[], timestamp_ms=int(time.time()*1000), dry_run=True)
    assert result["action"] == "PORTFOLIO_TP"


def test_partial_fill_uses_actual_executed_quantity(monkeypatch):
    settings = smart_cfg(maximumPositions=1, longSlots=1, shortSlots=0,
        smartRescueDcaCount=5, smartRescueRangePercent=5, smartRescueTrailingRecoveryPercent=.3)
    smart = build_position_state(initial_entry_price=100, start_margin_usd=.15, rescue_range_percent=5,
        dca_count=5, order_growth_multiplier=1.35, trailing_recovery_percent=.3, config_version=1)
    smart, _ = advance_state(smart, mark_price=99)
    rebound = 99 * 1.0031
    pos = {"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5","entryPrice":"100","markPrice":str(rebound),"leverage":"100"}
    outer = {"cycleId":"partial","dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":5,
        "lastKnownEntry":100,"leverage":100,"cycleStartedAtMs":1,"smartRescue":smart}
    seen = {}
    def fake_execute(_client, plan, **_kwargs):
        actual = float(plan.quantity) / 2
        seen["qty"] = actual
        return {"result":{"avgPrice":str(rebound),"executedQty":str(actual),"orderId":"partial-1"},"leverage":plan.leverage}
    monkeypatch.setattr(runtime, "execute_leg_once", fake_execute)
    ref = Ref()
    result = runtime.run_gate(client=Client(positions=[pos], prices={"AAAUSDT":rebound}, leverage=100), ref=ref,
        raw_state={"multiBbPositions":{"AAAUSDT|LONG":outer}}, settings=settings, uid="u",
        account={"availableBalance":"100"}, positions=[pos], open_orders=[], timestamp_ms=2, dry_run=False)
    updated = result["state"]["AAAUSDT|LONG"]
    assert updated["lastKnownQty"] == pytest.approx(5 + seen["qty"])
    assert updated["smartRescue"]["lastFillQty"] == pytest.approx(seen["qty"])
