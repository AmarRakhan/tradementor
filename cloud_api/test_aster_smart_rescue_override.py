from copy import deepcopy
import pytest

from aster_smart_rescue import advance_state, apply_fill, build_position_state
from aster_smart_rescue_override import active_cycle_summary, extend_future_levels, extension_preview


def base_state():
    return build_position_state(initial_entry_price=100, start_margin_usd=.15,
        rescue_range_percent=5, dca_count=10, order_growth_multiplier=1.35,
        trailing_recovery_percent=.1, config_version=7)


def position(mark=95):
    return {"symbol":"SOLUSDT","positionSide":"LONG","positionAmt":"1.5",
        "entryPrice":"97.25","markPrice":str(mark),"leverage":"100"}


def outer(smart):
    return {"cycleId":"cycle-sol-1","smartRescue":smart,"lastKnownQty":1.5,
        "lastKnownEntry":97.25,"leverage":100}


def test_10_to_25_appends_15_and_preserves_every_old_level():
    smart=base_state(); before=deepcopy(smart["levels"])
    extended=extend_future_levels(smart,new_total_dca=25,new_rescue_range_percent=8,
        future_growth_multiplier=1.1,timestamp_ms=123)
    assert extended["levels"][:10] == before
    assert len(extended["levels"]) == 25
    assert extended["levels"][-1]["dropPercent"] == pytest.approx(8)
    assert extended["levels"][-1]["triggerPrice"] == pytest.approx(92)
    assert all(x["status"]=="PENDING" for x in extended["levels"][10:])
    assert extended["extensionHistory"][-1]["addedSteps"] == 15


def test_filled_skipped_and_armed_history_is_unchanged():
    smart=base_state()
    smart["levels"][0]["status"]="FILLED"; smart["levels"][0]["actualFillPrice"]=99.8
    smart["levels"][1]["status"]="SKIPPED"
    smart["levels"][2]["status"]="ARMED"; smart["armedIndex"]=3; smart["localLow"]=98.1
    before=deepcopy(smart["levels"])
    extended=extend_future_levels(smart,new_total_dca=12,new_rescue_range_percent=7,
        future_growth_multiplier=1.2,timestamp_ms=456)
    assert extended["levels"][:10] == before
    assert extended["armedIndex"] == 3
    assert extended["localLow"] == 98.1


def test_growth_applies_only_to_appended_orders():
    smart=base_state(); before=deepcopy(smart["levels"])
    last=float(before[-1]["orderMarginUsd"])
    extended=extend_future_levels(smart,new_total_dca=12,new_rescue_range_percent=7,
        future_growth_multiplier=1.1,timestamp_ms=1)
    assert extended["levels"][:10] == before
    assert extended["levels"][10]["orderMarginUsd"] == pytest.approx(last*1.1)
    assert extended["levels"][11]["orderMarginUsd"] == pytest.approx(last*1.1*1.1)


def test_downgrade_or_shallower_range_is_rejected():
    smart=base_state()
    with pytest.raises(ValueError,match="groter"):
        extend_future_levels(smart,new_total_dca=8,new_rescue_range_percent=8,future_growth_multiplier=1.1,timestamp_ms=1)
    with pytest.raises(ValueError,match="dieper"):
        extend_future_levels(smart,new_total_dca=25,new_rescue_range_percent=2,future_growth_multiplier=1.1,timestamp_ms=1)


def test_summary_uses_actual_exchange_weighted_entry_for_be():
    smart=base_state(); summary=active_cycle_summary(smart_state=smart,outer_state=outer(smart),position=position(95))
    assert summary["cycleId"] == "cycle-sol-1"
    assert summary["breakEvenNowPercent"] == pytest.approx((97.25/95-1)*100)
    assert summary["dcaTotal"] == 10


def test_preview_starts_from_actual_open_position_and_keeps_finite_math():
    smart=base_state(); preview=extension_preview(smart_state=smart,outer_state=outer(smart),position=position(),
        new_total_dca=25,new_rescue_range_percent=8,future_growth_multiplier=1.1,timestamp_ms=2)
    assert preview["dcaTotal"] == 25
    assert preview["lastNewDcaDropPercent"] == 8
    assert preview["finalBreakEvenPrice"] > 0
    assert preview["finalRecoveryToBreakEvenPercent"] >= 0
    assert sum(1 for row in preview["previewRows"] if row["new"]) == 15


def test_extension_does_not_change_partial_fill_metadata():
    smart=base_state()
    smart=apply_fill(smart,level_index=1,fill_price=99.8,fill_qty=.123,actual_margin_usd=.2,order_id="partial-1",timestamp_ms=10)
    old=deepcopy(smart["levels"][0])
    extended=extend_future_levels(smart,new_total_dca=11,new_rescue_range_percent=6,
        future_growth_multiplier=1.05,timestamp_ms=11)
    assert extended["levels"][0] == old
    assert extended["levels"][0]["actualFillQty"] == pytest.approx(.123)


def test_extension_history_is_bounded():
    smart=base_state()
    for i in range(1,25):
        current=int(smart["dcaCountConfigured"])
        smart=extend_future_levels(smart,new_total_dca=current+1,
            new_rescue_range_percent=float(smart["rescueRangePercent"])+.1,
            future_growth_multiplier=1.01,timestamp_ms=i)
    assert len(smart["extensionHistory"]) == 20
