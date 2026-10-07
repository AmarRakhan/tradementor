from aster_multi_bb_core import MultiBbConfig
from aster_order_shadow import shadow_exchange_orders


def _settings(**overrides):
    raw = {
        "engine": "MULTI_BB_V1",
        "maximumPositions": 2,
        "longSlots": 1,
        "shortSlots": 1,
        "minimumLeverage": 50,
        "entryMarginUsd": 5,
        "entryNotionalUsd": 250,
        "dcaMarginUsd": 2,
        "dcaDistance": 0.10,
        "maxDca": 3,
        "takeProfit": 0.015,
        "takeProfitEnabled": True,
    }
    raw.update(overrides)
    return MultiBbConfig.from_mapping(raw)


def test_shadow_long_projects_one_tp_and_one_next_dca():
    result = shadow_exchange_orders(
        row={"symbol": "BTCUSDT", "positionSide": "LONG", "entryPrice": "100", "markPrice": "100", "positionAmt": "2"},
        state={"dcaCount": 0, "lastBotFillPrice": 100},
        settings=_settings(),
    )
    assert result["shadowOnly"] is True
    assert result["executionChanged"] is False
    assert [order["kind"] for order in result["orders"]] == ["TAKE_PROFIT", "NEXT_DCA"]
    tp, dca = result["orders"]
    assert round(tp["price"], 8) == 101.5
    assert tp["reduceOnly"] is True
    assert round(dca["price"], 8) == 90.0
    assert dca["dcaNumber"] == 1
    assert dca["placeOnlyOneNextDca"] is True


def test_shadow_recomputes_next_dca_from_last_confirmed_fill():
    result = shadow_exchange_orders(
        row={"symbol": "ETHUSDT", "positionSide": "LONG", "entryPrice": "95", "markPrice": "94", "positionAmt": "3"},
        state={"dcaCount": 1, "lastBotFillPrice": 90},
        settings=_settings(),
    )
    dca = next(order for order in result["orders"] if order["kind"] == "NEXT_DCA")
    assert round(dca["price"], 8) == 81.0
    assert dca["dcaNumber"] == 2
    assert dca["recomputeAfterFill"] is True


def test_shadow_short_projects_correct_exchange_sides():
    result = shadow_exchange_orders(
        row={"symbol": "SOLUSDT", "positionSide": "SHORT", "entryPrice": "100", "markPrice": "100", "positionAmt": "4"},
        state={"dcaCount": 0, "lastBotFillPrice": 100},
        settings=_settings(),
    )
    tp, dca = result["orders"]
    assert round(tp["price"], 8) == 98.5
    assert tp["exchangeSide"] == "BUY"
    assert round(dca["price"], 8) == 110.0
    assert dca["exchangeSide"] == "SELL"


def test_shadow_fails_closed_for_auto_hedge_and_tp_recovery():
    result = shadow_exchange_orders(
        row={"symbol": "XRPUSDT", "positionSide": "LONG", "entryPrice": "1", "markPrice": "1", "positionAmt": "100"},
        state={"dcaCount": 0, "lastBotFillPrice": 1, "tpRecoveryOnly": True},
        settings=_settings(),
        auto_hedge_managed=True,
    )
    tp, dca = result["orders"]
    assert tp["candidateStatus"] == "BLOCKED"
    assert "AUTO_HEDGE_MANAGED" in tp["blockers"]
    assert dca["candidateStatus"] == "BLOCKED"
    assert "TP_RECOVERY_ONLY" in dca["blockers"]
    assert "AUTO_HEDGE_REVALIDATION_REQUIRED" in dca["blockers"]
