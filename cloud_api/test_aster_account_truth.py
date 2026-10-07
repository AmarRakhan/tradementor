from pathlib import Path

from aster_account_truth import (
    ASTER_ACCOUNT_TRUTH_CONTRACT,
    ASTER_ACCOUNT_TRUTH_SCHEMA_VERSION,
    build_aster_account_truth,
)
from aster_portfolio_chart import daily_equity_range


def test_account_truth_contract_is_read_only_and_provenanced():
    status = {
        "configured": True,
        "equity": 321.45,
        "walletBalance": 300.0,
        "availableBalance": 180.0,
        "activeTradeCapital": 141.45,
        "unrealizedPnl": 21.45,
        "liquidationRiskPct": 12.0,
        "snapshotAt": 1_700_000_000_000,
        "positions": [
            {"symbol": "BTCUSDT", "side": "LONG", "dcaCount": 2},
            {"symbol": "ETHUSDT", "side": "SHORT", "dcaCount": 1},
        ],
        "strategy2": {
            "enabled": True,
            "monitor": False,
            "displayPhase": "RUNNING",
            "settings": {"longSlots": 4, "shortSlots": 3},
            "runtimeTruth": {"source": "SERVER_RUNTIME"},
        },
        "realizedPnlToday": 4.2,
        "tradesClosedToday": 3,
        "closedTodayReliable": True,
        "todayGrowthPercentage": 1.2,
        "averageDailyGrowthPercentage": 0.8,
        "growthReliable": True,
    }
    truth = build_aster_account_truth(
        status,
        day_high=330.0,
        day_low=315.0,
        now_ms=1_700_000_030_000,
    )
    assert truth["contract"] == ASTER_ACCOUNT_TRUTH_CONTRACT
    assert truth["schemaVersion"] == ASTER_ACCOUNT_TRUTH_SCHEMA_VERSION == 1
    assert truth["readOnly"] is True
    assert truth["ordersSent"] == 0
    assert truth["stale"] is False
    assert truth["account"]["equity"] == 321.45
    assert truth["positions"]["count"] == 2
    assert truth["positions"]["longCount"] == 1
    assert truth["positions"]["shortCount"] == 1
    assert truth["strategy"]["summary"]["dcaCount"] == 3
    assert truth["performance"]["dayHigh"] == 330.0
    assert truth["performance"]["dayLow"] == 315.0
    assert truth["performance"]["realizedPnlToday"] == 4.2
    assert truth["provenance"]["account"]["owner"] == "cloud_api.aster_status"


def test_account_truth_missing_values_stay_missing_instead_of_becoming_zero():
    truth = build_aster_account_truth(
        {"configured": True, "positions": [], "strategy2": {}, "snapshotAt": None},
        day_high=None,
        day_low=None,
        now_ms=1_700_000_000_000,
    )
    assert truth["account"]["equity"] is None
    assert truth["performance"]["dayHigh"] is None
    assert truth["performance"]["dayLow"] is None
    assert truth["performance"]["realizedPnlToday"] is None
    assert truth["stale"] is True


def test_daily_equity_range_is_server_deterministic_and_day_scoped():
    rows = [
        {"atMs": 1_000, "high": 105, "low": 99},
        {"atMs": 2_000, "high": 110, "low": 101},
        {"atMs": 3_000, "high": 109, "low": 95},
        {"atMs": 9_000, "high": 999, "low": 1},
    ]
    assert daily_equity_range(rows, day_start_ms=500, day_end_ms=5_000) == {"high": 110, "low": 95}


def test_status_and_portfolio_chart_share_one_daily_range_helper():
    source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    assert "def _aster_account_daily_range(" in source
    status_start = source.index('@app.get("/v1/me/aster/status")')
    status_end = source.index("def _portfolio_chart_timestamp_ms", status_start)
    status_block = source[status_start:status_end]
    assert "build_aster_account_truth(" in status_block
    assert "_aster_account_daily_range(" in status_block
    chart_start = source.index('@app.get("/v1/me/aster/portfolio-chart")')
    chart_end = source.index('@app.get("/v1/me/aster/trade-events")', chart_start)
    chart_block = source[chart_start:chart_end]
    assert "_aster_account_daily_range(" in chart_block
    assert '"dayHigh": daily_range.get("high")' in chart_block
    assert '"dayLow": daily_range.get("low")' in chart_block
    assert "place_order" not in status_block
