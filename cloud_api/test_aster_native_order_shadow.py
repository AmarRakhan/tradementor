from pathlib import Path

import pytest

from aster_multi_bb import ENGINE, MultiBbConfig
from aster_native_order_shadow import build_native_order_shadow, build_shadow_transition_plan


def settings(**overrides):
    raw = {
        "engine": ENGINE,
        "universeTopN": 20,
        "maximumPositions": 2,
        "longSlots": 1,
        "shortSlots": 1,
        "minimumLeverage": 50,
        "entryMarginUsd": 5,
        "dcaDistance": 0.10,
        "dcaMarginUsd": 2,
        "maxDca": 3,
        "takeProfit": 0.015,
        "takeProfitEnabled": True,
    }
    raw.update(overrides)
    return MultiBbConfig.from_mapping(raw)


def test_shadow_projects_exact_existing_tp_and_next_dca_without_orders():
    result = build_native_order_shadow(
        positions=[{
            "symbol": "AAAUSDT",
            "side": "LONG",
            "quantity": 2,
            "entryPrice": 100,
            "markPrice": 101,
            "leverage": 50,
        }],
        managed_positions={
            "AAAUSDT|LONG": {
                "dcaCount": 0,
                "lastBotFillPrice": 100,
                "nextDcaPrice": 90,
            }
        },
        settings=settings(),
        account_equity=250,
    )
    assert result["mode"] == "SHADOW_ONLY"
    assert result["ordersSent"] == 0
    assert result["exchangeCalls"] == 0
    assert result["managedOpenPositions"] == 1
    row = result["rows"][0]
    assert row["tp"]["targetPrice"] == pytest.approx(101.5)
    assert row["tp"]["orderIntent"] == "REDUCE_ONLY_LIMIT_CLOSE"
    assert row["tp"]["shadowEligible"] is True
    assert row["tp"]["canPreplaceNow"] is False
    assert row["dca"]["targetPrice"] == pytest.approx(90.0)
    assert row["dca"]["targetParity"] is True
    assert row["dca"]["orderIntent"] == "LIMIT_OPEN_NEXT_DCA"
    assert row["dca"]["canPreplaceNow"] is False


def test_auto_hedge_marks_tp_as_blocked_but_never_changes_runtime():
    result = build_native_order_shadow(
        positions=[{
            "symbol": "AAAUSDT",
            "side": "LONG",
            "quantity": 2,
            "entryPrice": 100,
            "markPrice": 101,
        }],
        managed_positions={
            "AAAUSDT|LONG": {
                "dcaCount": 0,
                "lastBotFillPrice": 100,
                "nextDcaPrice": 90,
            }
        },
        settings=settings(),
        auto_hedge_symbols={"AAAUSDT"},
    )
    row = result["rows"][0]
    assert "AUTO_HEDGE_CLOSE_GUARD" in row["tp"]["blockers"]
    assert row["tp"]["shadowEligible"] is False
    assert result["ordersSent"] == 0


def test_shadow_detects_stored_next_dca_drift_instead_of_hiding_it():
    result = build_native_order_shadow(
        positions=[{
            "symbol": "AAAUSDT",
            "side": "LONG",
            "quantity": 2,
            "entryPrice": 100,
            "markPrice": 95,
        }],
        managed_positions={
            "AAAUSDT|LONG": {
                "dcaCount": 0,
                "lastBotFillPrice": 100,
                "nextDcaPrice": 97,
            }
        },
        settings=settings(),
    )
    row = result["rows"][0]
    assert row["dca"]["targetPrice"] == pytest.approx(90.0)
    assert row["dca"]["targetParity"] is False
    assert row["dca"]["shadowEligible"] is False
    assert result["allDcaTargetsMatchRuntimeState"] is False


def test_shadow_endpoint_is_stored_state_only_and_has_no_order_or_exchange_client_path():
    source = Path(__file__).with_name("main.py").read_text()
    route = source.split('@app.get("/v1/me/aster/native-order-shadow")', 1)[1].split(
        '@app.get("/v1/me/aster/portfolio-chart/events")', 1
    )[0]
    assert "build_native_order_shadow" in route
    assert "STORED_CANONICAL_ASTER_SNAPSHOT" in route
    assert "AsterV3Client" not in route
    assert "execute_" not in route
    assert ".set(" not in route


def test_shadow_transition_replaces_tp_and_rearms_next_dca_after_confirmed_dca_fill():
    before_position = {
        "symbol": "AAAUSDT", "side": "LONG", "quantity": 2,
        "entryPrice": 100, "markPrice": 95,
    }
    after_position = {
        "symbol": "AAAUSDT", "side": "LONG", "quantity": 3,
        "entryPrice": 96, "markPrice": 90,
    }
    before_state = {"dcaCount": 0, "lastBotFillPrice": 100, "nextDcaPrice": 90}
    after_state = {"dcaCount": 1, "lastBotFillPrice": 90, "nextDcaPrice": 81}
    plan = build_shadow_transition_plan(
        before_position=before_position,
        after_position=after_position,
        before_state=before_state,
        after_state=after_state,
        before_settings=settings(),
        after_settings=settings(),
    )
    kinds = [row["kind"] for row in plan["actions"]]
    assert "REPLACE_TP" in kinds
    assert "REPLACE_DCA" in kinds
    dca = next(row for row in plan["actions"] if row["kind"] == "REPLACE_DCA")
    assert dca["reason"] == "DCA_FILL_REARM"
    assert dca["oldTargetPrice"] == pytest.approx(90)
    assert dca["newTargetPrice"] == pytest.approx(81)
    assert plan["ordersSent"] == 0


def test_shadow_transition_cancels_resting_orders_when_position_is_closed():
    plan = build_shadow_transition_plan(
        before_position={
            "symbol": "AAAUSDT", "side": "LONG", "quantity": 2,
            "entryPrice": 100, "markPrice": 101,
        },
        after_position=None,
        before_state={"dcaCount": 0, "lastBotFillPrice": 100, "nextDcaPrice": 90},
        after_state={},
        before_settings=settings(),
        after_settings=settings(),
    )
    kinds = {row["kind"] for row in plan["actions"]}
    assert kinds == {"CANCEL_TP", "CANCEL_DCA"}
    assert plan["afterOpen"] is False


def test_shadow_transition_cancels_tp_when_auto_hedge_becomes_active():
    plan = build_shadow_transition_plan(
        before_position={
            "symbol": "AAAUSDT", "side": "LONG", "quantity": 2,
            "entryPrice": 100, "markPrice": 101,
        },
        after_position={
            "symbol": "AAAUSDT", "side": "LONG", "quantity": 2,
            "entryPrice": 100, "markPrice": 99,
        },
        before_state={"dcaCount": 0, "lastBotFillPrice": 100, "nextDcaPrice": 90},
        after_state={"dcaCount": 0, "lastBotFillPrice": 100, "nextDcaPrice": 90},
        before_settings=settings(),
        after_settings=settings(),
        auto_hedge_before=False,
        auto_hedge_after=True,
    )
    assert any(
        row["kind"] == "CANCEL_TP" and row["reason"] == "AUTO_HEDGE_CLOSE_GUARD"
        for row in plan["actions"]
    )
    assert plan["safetyContract"]["mustRespectAutoHedgeCloseLock"] is True


def test_shadow_transition_replaces_dca_when_user_changes_distance():
    plan = build_shadow_transition_plan(
        before_position={
            "symbol": "AAAUSDT", "side": "LONG", "quantity": 2,
            "entryPrice": 100, "markPrice": 95,
        },
        after_position={
            "symbol": "AAAUSDT", "side": "LONG", "quantity": 2,
            "entryPrice": 100, "markPrice": 95,
        },
        before_state={"dcaCount": 0, "lastBotFillPrice": 100, "nextDcaPrice": 90},
        after_state={"dcaCount": 0, "lastBotFillPrice": 100, "nextDcaPrice": 80},
        before_settings=settings(dcaDistance=0.10),
        after_settings=settings(dcaDistance=0.20),
    )
    row = next(item for item in plan["actions"] if item["kind"] == "REPLACE_DCA")
    assert row["reason"] == "DCA_CONFIG_OR_ANCHOR_CHANGED"
    assert row["oldTargetPrice"] == pytest.approx(90)
    assert row["newTargetPrice"] == pytest.approx(80)


def test_shadow_transition_never_claims_live_execution():
    source = Path(__file__).with_name("aster_native_order_shadow.py").read_text()
    assert "ordersSent" in source
    assert "exchangeCalls" in source
    assert "client." not in source
    assert "execute_" not in source
