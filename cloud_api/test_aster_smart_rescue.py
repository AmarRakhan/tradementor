from __future__ import annotations

import math
import time
import pytest

import aster_multi_bb
import aster_smart_rescue_runtime as runtime
from aster_multi_bb import MultiBbConfig, _PairAwareSettings, run_multi_bb_step
from aster_smart_rescue import (
    advance_state, build_position_state, level_drop_percent, preview_ladder,
)
from test_aster_multi_bb import Client, Ref, cfg


def smart_cfg(**overrides):
    raw = {
        "engine": "multi_bb_v1", "universeTopN": 3, "maximumPositions": 2,
        "longSlots": 1, "shortSlots": 1, "minimumLeverage": 50,
        "entryMarginUsd": 0.15, "entryMarginLongUsd": 0.15, "entryMarginShortUsd": 0.15,
        "dcaDistance": .003, "dcaMarginUsd": .15, "maxDca": 20, "takeProfit": .015,
        "smartRescueEnabled": True, "smartRescueRangePercent": 10,
        "smartRescueDcaCount": 10, "smartRescueOrderGrowthMultiplier": 1.35,
        "smartRescueTrailingRecoveryPercent": .30,
    }
    raw.update(overrides)
    return MultiBbConfig.from_mapping(raw)


def test_smart_rescue_defaults_off_and_persist_round_trip():
    off = MultiBbConfig.from_mapping({})
    assert off.smart_rescue_enabled is False
    cfg = smart_cfg()
    public = cfg.public_dict()
    assert public["smartRescueEnabled"] is True
    assert public["smartRescueRangePercent"] == 10
    assert public["smartRescueDcaCount"] == 10
    assert public["smartRescueOrderGrowthMultiplier"] == pytest.approx(1.35)
    assert public["smartRescueTrailingRecoveryPercent"] == pytest.approx(.30)
    assert MultiBbConfig.from_mapping(public).public_dict()["smartRescueEnabled"] is True


def test_smart_rescue_progressive_curve_exact_examples():
    expected = [0.316, 0.894, 1.643, 2.530, 3.536, 4.648, 5.857, 7.155, 8.538, 10.0]
    actual = [level_drop_percent(10, i, 10) for i in range(1, 11)]
    for got, want in zip(actual, expected):
        assert got == pytest.approx(want, abs=.002)
    assert level_drop_percent(20, 25, 25) == 20.0


def test_deepest_crossed_level_wins_and_shallower_are_skipped():
    state = build_position_state(initial_entry_price=100, start_margin_usd=.15,
        rescue_range_percent=20, dca_count=25, order_growth_multiplier=1.2,
        trailing_recovery_percent=.3, config_version=1)
    # 90 crosses many levels in one uninterrupted fall.
    state, executable = advance_state(state, mark_price=90)
    assert executable is None
    armed = state["armedIndex"]
    assert armed and armed > 1
    assert sum(1 for row in state["levels"] if row["status"] == "ARMED") == 1
    assert all(row["status"] == "SKIPPED" for row in state["levels"] if row["index"] < armed)
    # New low moves the trailing anchor, still no buy.
    state, executable = advance_state(state, mark_price=88)
    assert executable is None and state["localLow"] == 88
    deeper_armed = state["armedIndex"]
    assert deeper_armed >= armed
    # 0.30% rebound releases exactly one deepest rescue.
    state, executable = advance_state(state, mark_price=88 * 1.003)
    assert executable is not None and executable["levelIndex"] == deeper_armed


def test_preview_break_even_recovery_is_real_price_move_not_leveraged_roi():
    preview = preview_ladder(initial_entry_price=1.0, start_margin_usd=.15, leverage=50,
        rescue_range_percent=10, dca_count=10, order_growth_multiplier=1.35)
    last = preview["rows"][-1]
    current = last["triggerPrice"]
    be = last["breakEvenPrice"]
    assert last["recoveryToBreakEvenPercent"] == pytest.approx((be / current - 1) * 100)
    assert last["recoveryToBreakEvenPercent"] > 0
    assert math.isfinite(preview["maxMarginUsd"])


def test_extreme_25x_1_50_preview_stays_finite_and_advisory():
    preview = preview_ladder(initial_entry_price=1, start_margin_usd=.15, leverage=50,
        rescue_range_percent=20, dca_count=25, order_growth_multiplier=1.5)
    assert len(preview["rows"]) == 25
    assert all(math.isfinite(row["cumulativeMarginUsd"]) for row in preview["rows"])
    assert preview["maxMarginUsd"] > 1000


def test_runtime_projection_is_long_only_but_storage_remains_unchanged():
    settings = smart_cfg(maximumPositions=6, longSlots=4, shortSlots=2)
    projected = _PairAwareSettings(settings)
    assert settings.long_slots == 4 and settings.short_slots == 2
    assert projected.long_slots == 6 and projected.short_slots == 0


def test_existing_non_smart_position_keeps_normal_dca_behavior():
    settings = smart_cfg(maximumPositions=1, longSlots=1, shortSlots=0)
    pos = {"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5","entryPrice":"100","markPrice":"99","leverage":"100"}
    raw = {"multiBbPositions":{"AAAUSDT|LONG":{"cycleId":"legacy","dcaCount":0,"lastBotFillPrice":100,
        "lastKnownQty":5,"lastKnownEntry":100,"cycleStartedAtMs":1}}}
    result = run_multi_bb_step(client=Client(positions=[pos], prices={"AAAUSDT":99}, leverage=100), ref=Ref(),
        raw_state=raw, settings=settings, uid="u", account={"availableBalance":"100"}, positions=[pos],
        open_orders=[], timestamp_ms=int(time.time()*1000), dry_run=True)
    # Enabling the mode does not retrofit the already-open cycle into Smart Rescue.
    assert any(a["kind"] == "DCA" for a in result["actions"])


def test_new_live_long_is_atomically_stamped_with_smart_rescue(monkeypatch):
    settings = smart_cfg(maximumPositions=1, longSlots=1, shortSlots=0)
    client = Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"1000"}], prices={"AAAUSDT":100}, leverage=100)
    def fake_execute(_client, plan, **kwargs):
        return {"result":{"avgPrice":"100","executedQty":str(plan.quantity),"orderId":"entry-1"},"leverage":plan.leverage}
    monkeypatch.setattr(aster_multi_bb, "execute_leg_once", fake_execute)
    ref = Ref()
    run_multi_bb_step(client=client, ref=ref, raw_state={}, settings=settings, uid="u",
        account={"availableBalance":"100"}, positions=[], open_orders=[], timestamp_ms=123456, dry_run=False)
    maps = [row["multiBbPositions"] for row in ref.updates if "multiBbPositions" in row]
    assert maps
    state = maps[-1]["AAAUSDT|LONG"]
    assert state["smartRescue"]["initialEntryPrice"] == pytest.approx(100)
    assert state["smartRescue"]["configVersion"] == settings.version
    assert state["smartRescue"]["dcaCountConfigured"] == 10


def test_smart_position_suppresses_legacy_dca_and_executes_only_after_rebound(monkeypatch):
    settings = smart_cfg(maximumPositions=1, longSlots=1, shortSlots=0, smartRescueDcaCount=5,
                         smartRescueRangePercent=5, smartRescueTrailingRecoveryPercent=.3)
    smart = build_position_state(initial_entry_price=100, start_margin_usd=.15,
        rescue_range_percent=5, dca_count=5, order_growth_multiplier=1.35,
        trailing_recovery_percent=.3, config_version=1)
    base_state = {"cycleId":"smartcycle","dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":5,
                  "lastKnownEntry":100,"leverage":100,"cycleStartedAtMs":1,"smartRescue":smart}
    # Cross first level: only arm/trail, no rescue and no legacy DCA.
    pos = {"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5","entryPrice":"100","markPrice":"99","leverage":"100"}
    ref = Ref(); raw={"multiBbPositions":{"AAAUSDT|LONG":base_state}}
    first = run_multi_bb_step(client=Client(positions=[pos], prices={"AAAUSDT":99}, leverage=100), ref=ref,
        raw_state=raw, settings=settings, uid="u", account={"availableBalance":"100"}, positions=[pos], open_orders=[],
        timestamp_ms=1000, dry_run=False)
    assert not any(a["kind"] == "DCA" for a in first.get("actions", []))
    latest = [u["multiBbPositions"] for u in ref.updates if "multiBbPositions" in u][-1]
    armed = latest["AAAUSDT|LONG"]["smartRescue"]
    assert armed["armedIndex"] is not None

    # Rebound from the tracked low: exactly one Smart Rescue execution.
    rebound = dict(pos); rebound["markPrice"] = str(99 * 1.0031)
    client = Client(positions=[rebound], prices={"AAAUSDT":float(rebound["markPrice"])}, leverage=100)
    def fake_rescue(_client, plan, **kwargs):
        return {"result":{"avgPrice":rebound["markPrice"],"executedQty":str(plan.quantity),"orderId":"rescue-1"},"leverage":plan.leverage}
    monkeypatch.setattr(runtime, "execute_leg_once", fake_rescue)
    ref2=Ref()
    second = run_multi_bb_step(client=client, ref=ref2, raw_state={"multiBbPositions":latest}, settings=settings,
        uid="u", account={"availableBalance":"100"}, positions=[rebound], open_orders=[], timestamp_ms=2000, dry_run=False)
    assert second["action"] == "SMART_RESCUE_DCA"
    assert len([a for a in second["actions"] if a["kind"] == "SMART_RESCUE_DCA"]) == 1


def test_smart_rescue_financial_risk_never_invalidates_config():
    # Financially extreme is allowed; warnings belong to UI. Only malformed values validate-fail.
    cfg = smart_cfg(smartRescueDcaCount=25, smartRescueOrderGrowthMultiplier=1.5, smartRescueRangePercent=20)
    assert cfg.smart_rescue_enabled is True
    with pytest.raises(ValueError):
        smart_cfg(smartRescueRangePercent=0)


def test_turning_global_toggle_off_does_not_freeze_existing_smart_cycle(monkeypatch):
    enabled = smart_cfg(maximumPositions=1, longSlots=1, shortSlots=0,
                        smartRescueDcaCount=5, smartRescueRangePercent=5,
                        smartRescueTrailingRecoveryPercent=.3)
    stored = build_position_state(initial_entry_price=100, start_margin_usd=.15,
        rescue_range_percent=5, dca_count=5, order_growth_multiplier=1.35,
        trailing_recovery_percent=.3, config_version=1)
    stored, _ = advance_state(stored, mark_price=99)
    base_state = {"cycleId":"smart-off-cycle","dcaCount":0,"lastBotFillPrice":100,
                  "lastKnownQty":5,"lastKnownEntry":100,"leverage":100,
                  "cycleStartedAtMs":1,"smartRescue":stored}
    disabled = MultiBbConfig.from_mapping({**enabled.public_dict(), "smartRescueEnabled": False})
    rebound = {"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5",
               "entryPrice":"100","markPrice":str(99 * 1.0031),"leverage":"100"}
    client = Client(positions=[rebound], prices={"AAAUSDT":float(rebound["markPrice"])}, leverage=100)
    def fake_rescue(_client, plan, **kwargs):
        return {"result":{"avgPrice":rebound["markPrice"],"executedQty":str(plan.quantity),"orderId":"rescue-off-1"},"leverage":plan.leverage}
    monkeypatch.setattr(runtime, "execute_leg_once", fake_rescue)
    result = run_multi_bb_step(client=client, ref=Ref(), raw_state={"multiBbPositions":{"AAAUSDT|LONG":base_state}},
        settings=disabled, uid="u", account={"availableBalance":"100"}, positions=[rebound], open_orders=[],
        timestamp_ms=3000, dry_run=False)
    assert result["action"] == "SMART_RESCUE_DCA"
    assert any(a["kind"] == "SMART_RESCUE_DCA" for a in result["actions"])


def test_enabling_smart_rescue_does_not_retrofit_adopted_existing_position(monkeypatch):
    settings = smart_cfg(maximumPositions=1, longSlots=1, shortSlots=0)
    pos = {"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5","entryPrice":"100","markPrice":"100","leverage":"100"}
    ref = Ref(); raw={"multiBbAdoptionPending":True,"multiBbPositions":{}}
    run_multi_bb_step(client=Client(positions=[pos], prices={"AAAUSDT":100}, leverage=100), ref=ref,
        raw_state=raw, settings=settings, uid="u", account={"availableBalance":"100"}, positions=[pos], open_orders=[],
        timestamp_ms=5555, dry_run=False)
    maps=[u["multiBbPositions"] for u in ref.updates if "multiBbPositions" in u]
    assert maps
    adopted=maps[-1]["AAAUSDT|LONG"]
    assert adopted.get("adoptedExisting") is True
    assert "smartRescue" not in adopted


def test_restart_preserves_armed_local_low_and_prevents_replaying_filled_level():
    smart = build_position_state(initial_entry_price=100, start_margin_usd=.15, rescue_range_percent=10,
        dca_count=10, order_growth_multiplier=1.2, trailing_recovery_percent=.3, config_version=4)
    smart, executable = advance_state(smart, mark_price=94)
    assert executable is None and smart["armedIndex"] is not None
    smart, executable = advance_state(smart, mark_price=93)
    assert executable is None and smart["localLow"] == 93
    # Persist/reload exactly the state a restart would restore.
    persisted = {**smart, "levels": [dict(row) for row in smart["levels"]]}
    resumed, executable = advance_state(persisted, mark_price=93 * 1.0031)
    assert executable is not None
    filled = runtime.apply_fill(resumed, level_index=executable["levelIndex"], fill_price=93 * 1.0031,
        fill_qty=.25, actual_margin_usd=.15, order_id="idempotent-order", timestamp_ms=9)
    again, duplicate = advance_state(filled, mark_price=93 * 1.0031)
    assert duplicate is None
    assert again["lastFillId"] == "idempotent-order"


def test_restart_after_unpersisted_fill_reconciles_armed_step_without_duplicate(monkeypatch):
    settings = smart_cfg(maximumPositions=1, longSlots=1, shortSlots=0,
                         smartRescueDcaCount=5, smartRescueRangePercent=5,
                         smartRescueTrailingRecoveryPercent=.3)
    smart = build_position_state(initial_entry_price=100, start_margin_usd=.15,
        rescue_range_percent=5, dca_count=5, order_growth_multiplier=1.35,
        trailing_recovery_percent=.3, config_version=1)
    smart, _ = advance_state(smart, mark_price=99)
    smart, executable = advance_state(smart, mark_price=99 * 1.0031)
    assert executable is not None and smart["armedIndex"] is not None
    base = {"cycleId":"restart-fill","dcaCount":0,"lastBotFillPrice":100,
            "lastKnownQty":5,"lastKnownEntry":100,"leverage":100,
            "cycleStartedAtMs":1,"smartRescue":smart}
    # Exchange already reflects an extra 0.2 qty after the process died before
    # the Smart Rescue state write. The runtime must reconcile, not resubmit.
    new_qty = 5.2; inferred_fill = 99.25
    new_entry = (100 * 5 + inferred_fill * .2) / new_qty
    pos = {"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":str(new_qty),
           "entryPrice":str(new_entry),"markPrice":str(99 * 1.0031),"leverage":"100"}
    def must_not_submit(*_args, **_kwargs):
        raise AssertionError("restart reconciliation must not submit a duplicate rescue")
    monkeypatch.setattr(runtime, "execute_leg_once", must_not_submit)
    result = runtime.run_gate(client=Client(positions=[pos], prices={"AAAUSDT":99 * 1.0031}, leverage=100),
        ref=Ref(), raw_state={"multiBbPositions":{"AAAUSDT|LONG":base}}, settings=settings, uid="u",
        account={"availableBalance":"100"}, positions=[pos], open_orders=[], timestamp_ms=4000, dry_run=False)
    updated = result["state"]["AAAUSDT|LONG"]
    assert updated["dcaCount"] == 1
    assert updated["lastKnownQty"] == pytest.approx(new_qty)
    assert updated["smartRescue"]["filledCount"] == 1
    assert updated["smartRescue"]["armedIndex"] is None
    assert any(a["kind"] == "SMART_RESCUE_FILL_RECONCILED" for a in result["actions"])
    # Replaying the identical exchange snapshot is idempotent.
    again = runtime.run_gate(client=Client(positions=[pos], prices={"AAAUSDT":99 * 1.0031}, leverage=100),
        ref=Ref(), raw_state={"multiBbPositions":result["state"]}, settings=settings, uid="u",
        account={"availableBalance":"100"}, positions=[pos], open_orders=[], timestamp_ms=5000, dry_run=False)
    assert not any(a["kind"] == "SMART_RESCUE_DCA" for a in again["actions"])
    assert again["state"]["AAAUSDT|LONG"]["dcaCount"] == 1


def test_restart_with_same_side_open_order_waits_instead_of_resubmitting(monkeypatch):
    settings = smart_cfg(maximumPositions=1, longSlots=1, shortSlots=0,
                         smartRescueDcaCount=5, smartRescueRangePercent=5,
                         smartRescueTrailingRecoveryPercent=.3)
    smart = build_position_state(initial_entry_price=100, start_margin_usd=.15,
        rescue_range_percent=5, dca_count=5, order_growth_multiplier=1.35,
        trailing_recovery_percent=.3, config_version=1)
    smart, _ = advance_state(smart, mark_price=99)
    base = {"cycleId":"restart-open","dcaCount":0,"lastBotFillPrice":100,
            "lastKnownQty":5,"lastKnownEntry":100,"leverage":100,
            "cycleStartedAtMs":1,"smartRescue":smart}
    rebound = 99 * 1.0031
    pos = {"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5",
           "entryPrice":"100","markPrice":str(rebound),"leverage":"100"}
    monkeypatch.setattr(runtime, "execute_leg_once", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("open order must block duplicate")))
    result = runtime.run_gate(client=Client(positions=[pos], prices={"AAAUSDT":rebound}, leverage=100), ref=Ref(),
        raw_state={"multiBbPositions":{"AAAUSDT|LONG":base}}, settings=settings, uid="u", account={"availableBalance":"100"},
        positions=[pos], open_orders=[{"symbol":"AAAUSDT","positionSide":"LONG"}], timestamp_ms=6000, dry_run=False)
    assert result["ordersSent"] == 0
    assert result["state"]["AAAUSDT|LONG"]["smartRescue"]["armedIndex"] is not None
