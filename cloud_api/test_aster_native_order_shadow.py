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
