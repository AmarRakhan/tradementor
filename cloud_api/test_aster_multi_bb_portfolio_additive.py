from types import SimpleNamespace

import pytest

from aster_multi_bb import ENGINE, MultiBbConfig, effective_pair_settings, position_action_preview
from aster_multi_bb_portfolio import PortfolioCycleOrderBlocked, assert_order_allowed


def settings_for(mode: str) -> MultiBbConfig:
    return MultiBbConfig.from_mapping({
        "engine": ENGINE,
        "universeTopN": 10,
        "maximumPositions": 2,
        "longSlots": 1,
        "shortSlots": 1,
        "minimumLeverage": 20,
        "entryMarginUsd": 1,
        "entryNotionalUsd": 20,
        "entrySizingMode": "notional",
        "dcaDistance": 0.003,
        "dcaMarginUsd": 1,
        "maxDca": 3,
        "takeProfit": 0.01,
        "longTakeProfitValue": 0.01,
        "shortTakeProfitValue": 0.02,
        "takeProfitMode": mode,
        # Reproduce the stale value older Portfolio saves persisted.
        "takeProfitEnabled": False,
        "portfolioTpInputMode": "USD",
        "portfolioTpValue": 10,
    })


class Snapshot:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


class Ref:
    def __init__(self, value):
        self.value = value

    def get(self):
        return Snapshot(self.value)


def test_portfolio_mode_keeps_pair_take_profit_active():
    settings = settings_for("PORTFOLIO")
    assert settings.take_profit_enabled is True

    pair = effective_pair_settings(settings, "BTCUSDT")
    assert pair["individualTpActive"] is True

    preview = position_action_preview(
        row={"symbol": "BTCUSDT", "positionSide": "LONG", "entryPrice": "100", "markPrice": "100.5", "positionAmt": "1"},
        state={"dcaCount": 0, "lastBotFillPrice": 100},
        settings=settings,
        account_equity=100,
    )
    assert preview["takeProfitEnabled"] is True
    assert preview["takeProfitPct"] == pytest.approx(1.0)
    assert preview["tpPrice"] == pytest.approx(101.0)


def test_portfolio_mode_allows_individual_tp_close_order():
    ref = Ref({
        "settings": {"takeProfitMode": "PORTFOLIO"},
        "multiBbCycle": {"cycleStatus": "RUNNING"},
    })
    assert_order_allowed(ref, SimpleNamespace(action="CLOSE", intent_id="mbb-tp-test"))


def test_off_mode_blocks_individual_tp_close_order():
    ref = Ref({
        "settings": {"takeProfitMode": "OFF"},
        "multiBbCycle": {"cycleStatus": "RUNNING"},
    })
    with pytest.raises(PortfolioCycleOrderBlocked, match="OFF"):
        assert_order_allowed(ref, SimpleNamespace(action="CLOSE", intent_id="mbb-tp-test"))
