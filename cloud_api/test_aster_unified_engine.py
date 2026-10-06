from types import SimpleNamespace
from pathlib import Path

import pytest

from aster_unified_engine import (
    ActionType, FilterResult, FilterStatus, InitialEntryContext, PositionActionContext,
    DecisionStatus, evaluate_initial_entry, evaluate_position_action,
    policy_from_settings, require_allowed,
)
from aster_multi_bb import MultiBbConfig, position_action_preview


def settings(**overrides):
    base = dict(
        version=7,
        maximum_positions=10,
        long_slots=6,
        short_slots=4,
        zone_soldiers_enabled=False,
        zone_base_long_soldiers=2,
        zone_base_short_soldiers=0,
        bollinger_entry_filter_15m_enabled=True,
        bollinger_entry_filter_timeframe="15m",
        bollinger_long_timeframe="15m",
        bollinger_short_timeframe="15m",
        dca_distance=.10,
        dca_margin_usd=.50,
        max_dca=10,
        long_dca_distance=.10,
        short_dca_distance=.10,
        long_dca_margin_usd=.50,
        short_dca_margin_usd=.50,
        max_dca_long=10,
        max_dca_short=10,
        take_profit=.10,
        long_take_profit_value=.10,
        short_take_profit_value=.10,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def context(**overrides):
    base = dict(
        uid="u1", symbol="BTCUSDT", side="LONG", bot_enabled=True,
        current_config_version=7, observed_config_version=7,
        account_position_count=0, side_position_count=0,
        active_zone=None, active_zone_side_count=0,
        duplicate_position_open=False,
        filter_results=(FilterResult("bollinger", FilterStatus.PASS),),
    )
    base.update(overrides)
    return InitialEntryContext(**base)


def test_classic_astrobotoff_zone_module_keeps_classic_slot_semantics():
    policy = policy_from_settings(settings(zone_soldiers_enabled=False))
    assert policy.price_zone.enabled is False
    assert evaluate_initial_entry(policy, context(side="LONG", side_position_count=5)).allowed
    denied = evaluate_initial_entry(policy, context(side="LONG", side_position_count=6))
    assert denied.reason_code == "LONG_SLOT_CAP_REACHED"


def test_price_zone_zero_short_is_absolute():
    policy = policy_from_settings(settings(zone_soldiers_enabled=True))
    denied = evaluate_initial_entry(
        policy,
        context(side="SHORT", active_zone=1, active_zone_side_count=0),
    )
    assert denied.status is DecisionStatus.DENY
    assert denied.reason_code == "SHORT_DISABLED"


def test_price_zone_two_long_never_admits_third():
    policy = policy_from_settings(settings(zone_soldiers_enabled=True))
    allowed = evaluate_initial_entry(
        policy,
        context(side="LONG", active_zone=2, active_zone_side_count=1),
    )
    assert allowed.allowed
    denied = evaluate_initial_entry(
        policy,
        context(side="LONG", active_zone=2, active_zone_side_count=2),
    )
    assert denied.reason_code == "ZONE_LONG_CAP_REACHED"


def test_global_max_is_absolute_for_price_zone_module():
    policy = policy_from_settings(settings(zone_soldiers_enabled=True))
    denied = evaluate_initial_entry(
        policy,
        context(side="LONG", active_zone=1, account_position_count=10),
    )
    assert denied.reason_code == "GLOBAL_POSITION_CAP_REACHED"


def test_stale_config_is_fail_closed():
    policy = policy_from_settings(settings(zone_soldiers_enabled=True))
    denied = evaluate_initial_entry(
        policy,
        context(side="LONG", active_zone=1, current_config_version=8),
    )
    assert denied.reason_code == "STALE_CONFIG_VERSION"
    with pytest.raises(PermissionError):
        require_allowed(denied, action_type=ActionType.INITIAL_ENTRY)


def test_filter_failure_blocks_entry():
    policy = policy_from_settings(settings(zone_soldiers_enabled=False))
    denied = evaluate_initial_entry(
        policy,
        context(filter_results=(FilterResult("bollinger", FilterStatus.FAIL, "below rule failed"),)),
    )
    assert denied.reason_code == "FILTER_FAIL:bollinger"


def test_new_price_zone_public_alias_normalizes_to_same_runtime_fields():
    cfg = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1",
        "version": 9,
        "universeTopN": 30,
        "maximumPositions": 10,
        "longSlots": 10,
        "shortSlots": 0,
        "priceZoneSeats": {"enabled": True, "longSeatsPerZone": 2, "shortSeatsPerZone": 0},
        "entryNotionalUsd": 250,
        "entryNotionalLongUsd": 250,
        "entryNotionalShortUsd": 250,
        "entryMarginUsd": 5,
        "entryMarginLongUsd": 5,
        "entryMarginShortUsd": 5,
        "dcaMarginUsd": 2,
        "longDcaMarginUsd": 2,
        "shortDcaMarginUsd": 2,
        "longDcaDistance": .10,
        "shortDcaDistance": .10,
        "maxDcaLong": 10,
        "maxDcaShort": 10,
        "longTakeProfitValue": .05,
        "shortTakeProfitValue": .05,
    })
    assert cfg.zone_soldiers_enabled is True
    assert cfg.zone_base_long_soldiers == 2
    assert cfg.zone_base_short_soldiers == 0
    public = cfg.public_dict()
    assert public["priceZoneSeats"] == {
        "enabled": True, "longSeatsPerZone": 2, "shortSeatsPerZone": 0,
    }


def test_active_position_preview_recalculates_dca_from_current_config_not_stale_state():
    row = {
        "symbol": "BTCUSDT", "positionSide": "LONG", "entryPrice": "100",
        "markPrice": "96", "positionAmt": "1",
    }
    stale_state = {
        "dcaCount": 2,
        "lastBotFillPrice": 100,
        "nextDcaPrice": 90,       # historical 10% policy; must not win
        "dcaDistance": .10,       # legacy policy copy; must not win
    }
    cfg = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1",
        "version": 11,
        "universeTopN": 30,
        "maximumPositions": 2,
        "longSlots": 2,
        "shortSlots": 0,
        "entryNotionalUsd": 250,
        "entryNotionalLongUsd": 250,
        "entryNotionalShortUsd": 250,
        "entryMarginUsd": 5,
        "entryMarginLongUsd": 5,
        "entryMarginShortUsd": 5,
        "dcaMarginUsd": .8,
        "longDcaMarginUsd": .8,
        "shortDcaMarginUsd": .8,
        "longDcaDistance": .05,
        "shortDcaDistance": .05,
        "maxDcaLong": 5,
        "maxDcaShort": 5,
        "longTakeProfitValue": .05,
        "shortTakeProfitValue": .05,
    })
    preview = position_action_preview(row=row, state=stale_state, settings=cfg)
    assert preview["nextDcaPrice"] == pytest.approx(95.0)
    assert preview["nextDcaNumber"] == 3


def test_initial_entry_open_has_canonical_admission_immediately_before_submit():
    source = (Path(__file__).parent / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    marker = 'id_prefix=f"mbb-open-'
    index = source.index(marker)
    before = source[max(0, index - 9000):index]
    assert "evaluate_initial_entry(" in before
    assert "require_allowed(admission)" in before
    assert "client.position_risk()" in before
    assert 'latest_doc=ref.get().to_dict() or {}' in before


def test_current_policy_action_gate_uses_new_dca_distance_amount_limit_and_tp():
    old = policy_from_settings(settings(
        version=7, long_dca_distance=.10, long_dca_margin_usd=.50,
        max_dca_long=10, long_take_profit_value=.10,
    ))
    new = policy_from_settings(settings(
        version=8, long_dca_distance=.05, long_dca_margin_usd=.80,
        max_dca_long=5, long_take_profit_value=.05,
    ))
    assert old.current_position_policy("LONG")["dcaDistance"] == pytest.approx(.10)
    current = new.current_position_policy("LONG")
    assert current["dcaDistance"] == pytest.approx(.05)
    assert current["dcaAmount"] == pytest.approx(.80)
    assert current["maxDca"] == 5
    assert current["takeProfit"] == pytest.approx(.05)

    allowed = evaluate_position_action(new, PositionActionContext(
        uid="u1", symbol="BTCUSDT", side="LONG", action_type=ActionType.DCA_ADD,
        position_open=True, trigger_met=True, dca_count=4,
    ))
    assert allowed.allowed
    blocked = evaluate_position_action(new, PositionActionContext(
        uid="u1", symbol="BTCUSDT", side="LONG", action_type=ActionType.DCA_ADD,
        position_open=True, trigger_met=True, dca_count=5,
    ))
    assert blocked.reason_code == "MAX_DCA_REACHED"


def test_explicit_bot_off_blocks_initial_entry_but_does_not_mutate_positions():
    policy = policy_from_settings(settings(zone_soldiers_enabled=True))
    denied = evaluate_initial_entry(
        policy,
        context(side="LONG", active_zone=1, bot_enabled=False),
    )
    assert denied.reason_code == "BOT_DISABLED"


def test_multi_bb_runtime_has_no_direct_low_level_leg_execution_bypass():
    source = (Path(__file__).parent / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert "from aster_unified_execution import execute_approved_leg_once" in source
    assert "execute_leg_once(" not in source
    assert source.count("execute_approved_leg_once(") >= 6
    for action in [
        "ActionType.INITIAL_ENTRY",
        "ActionType.DCA_ADD",
        "ActionType.CLOSE_TP",
        "ActionType.HEDGE_OPEN",
        "ActionType.HEDGE_CLOSE",
    ]:
        assert action in source


def test_execution_boundary_rejects_missing_or_wrong_action_decision():
    from aster_unified_execution import _validate_decision
    policy = policy_from_settings(settings())
    admission = evaluate_initial_entry(policy, context())
    assert admission.allowed
    with pytest.raises(PermissionError):
        _validate_decision(admission, ActionType.DCA_ADD)
