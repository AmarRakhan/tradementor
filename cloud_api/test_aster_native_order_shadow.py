from pathlib import Path

import pytest

from aster_multi_bb import ENGINE, MultiBbConfig
from aster_native_order_shadow import build_native_order_shadow


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
        "version": 7,
    }
    raw.update(overrides)
    return MultiBbConfig.from_mapping(raw)


def position(entry=100, mark=101, qty=2):
    return {
        "symbol": "AAAUSDT", "side": "LONG", "quantity": qty,
        "entryPrice": entry, "markPrice": mark, "leverage": 50,
    }


def state(next_dca=90, dca_count=0, **extra):
    return {"AAAUSDT|LONG": {
        "dcaCount": dca_count,
        "lastBotFillPrice": 100,
        "nextDcaPrice": next_dca,
        "policyConfigVersion": 7,
        **extra,
    }}


def test_shadow_projects_current_tp_and_next_dca_without_any_live_action():
    result = build_native_order_shadow(
        positions=[position()],
        managed_positions=state(),
        settings=settings(),
        account_equity=250,
    )
    assert result["mode"] == "SHADOW_ONLY"
    assert result["ordersSent"] == 0
    assert result["ordersCancelled"] == 0
    assert result["ordersReplaced"] == 0
    assert result["exchangeCalls"] == 0
    row = result["rows"][0]
    assert row["tp"]["targetPrice"] == pytest.approx(101.5)
    assert row["tp"]["desiredOrder"]["reduceOnly"] is True
    assert row["dca"]["targetPrice"] == pytest.approx(90.0)
    assert row["dca"]["targetParity"] is True
    assert row["tp"]["canPreplaceNow"] is False
    assert row["dca"]["canPreplaceNow"] is False


def test_dca_fill_would_cancel_replace_both_tp_and_next_dca():
    before = build_native_order_shadow(
        positions=[position(entry=100, mark=95, qty=2)],
        managed_positions=state(),
        settings=settings(),
    )
    previous = {
        "AAAUSDT|LONG": {
            "tp": {"fingerprint": before["rows"][0]["tp"]["lifecycle"]["fingerprint"]},
            "dca": {"fingerprint": before["rows"][0]["dca"]["lifecycle"]["fingerprint"]},
        }
    }
    after = build_native_order_shadow(
        positions=[position(entry=95, mark=94, qty=3)],
        managed_positions={"AAAUSDT|LONG": {
            "dcaCount": 1,
            "lastBotFillPrice": 90,
            "nextDcaPrice": 81,
            "policyConfigVersion": 7,
        }},
        settings=settings(),
        previous_shadow=previous,
    )
    row = after["rows"][0]
    assert row["tp"]["lifecycle"]["action"] == "WOULD_CANCEL_REPLACE"
    assert row["dca"]["lifecycle"]["action"] == "WOULD_CANCEL_REPLACE"
    assert after["ordersSent"] == 0


def test_settings_change_blocks_stale_dca_until_recalculated_runtime_state_matches():
    result = build_native_order_shadow(
        positions=[position(mark=95)],
        managed_positions=state(next_dca=90),
        settings=settings(version=8),
    )
    row = result["rows"][0]
    assert "CONFIG_VERSION_CHANGED" in row["dca"]["blockers"]
    assert row["dca"]["lifecycle"]["action"] == "HOLD"
    assert row["dca"]["shadowEligible"] is False


def test_manual_position_change_would_replace_tp_quantity():
    before = build_native_order_shadow(
        positions=[position(qty=2)],
        managed_positions=state(),
        settings=settings(),
    )
    previous = {
        "AAAUSDT|LONG": {
            "tp": {"fingerprint": before["rows"][0]["tp"]["lifecycle"]["fingerprint"]},
            "dca": {"fingerprint": before["rows"][0]["dca"]["lifecycle"]["fingerprint"]},
        }
    }
    after = build_native_order_shadow(
        positions=[position(qty=3)],
        managed_positions=state(),
        settings=settings(),
        previous_shadow=previous,
    )
    assert after["rows"][0]["tp"]["lifecycle"]["action"] == "WOULD_CANCEL_REPLACE"


def test_auto_hedge_forces_tp_hold_instead_of_native_close():
    result = build_native_order_shadow(
        positions=[position()],
        managed_positions=state(),
        settings=settings(),
        auto_hedge_symbols={"AAAUSDT"},
    )
    row = result["rows"][0]
    assert "AUTO_HEDGE_CLOSE_GUARD" in row["tp"]["blockers"]
    assert row["tp"]["lifecycle"]["action"] == "HOLD"
    assert row["tp"]["shadowEligible"] is False


def test_runtime_target_drift_is_visible_and_fail_closed():
    result = build_native_order_shadow(
        positions=[position(mark=95)],
        managed_positions=state(next_dca=97),
        settings=settings(),
    )
    row = result["rows"][0]
    assert row["dca"]["targetPrice"] == pytest.approx(90.0)
    assert row["dca"]["targetParity"] is False
    assert "RUNTIME_TARGET_DRIFT" in row["dca"]["blockers"]
    assert result["allDcaTargetsMatchRuntimeState"] is False


def test_shadow_endpoint_has_no_exchange_client_order_submit_or_state_write():
    source = Path(__file__).with_name("main.py").read_text()
    route = source.split('@app.get("/v1/me/aster/native-order-shadow")', 1)[1].split(
        '@app.get("/v1/me/aster/portfolio-chart/events")', 1
    )[0]
    assert "STORED_CANONICAL_ASTER_SNAPSHOT" in route
    assert "AsterV3Client" not in route
    assert "execute_" not in route
    assert ".set(" not in route
    assert "ordersSent" in route
