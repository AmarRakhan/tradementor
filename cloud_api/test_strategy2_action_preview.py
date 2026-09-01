from aster_multi_bb import MultiBbConfig, position_action_preview


def cfg(**overrides):
    base = dict(universeTopN=10, maximumPositions=2, longSlots=1, shortSlots=1, minimumLeverage=50, entryNotionalUsd=250, dcaDistance=.05, dcaMarginUsd=2, maxDca=3, takeProfit=.19)
    base.update(overrides)
    return MultiBbConfig.from_mapping(base)


def row(side, entry, mark, qty=2):
    return {"positionSide": side, "entryPrice": entry, "markPrice": mark, "positionAmt": qty}


def test_long_preview_uses_real_19_percent_tp_and_portfolio_delta():
    preview = position_action_preview(row=row("LONG",100,105), state={"dcaCount":0,"lastBotFillPrice":100}, settings=cfg(), account_equity=161.65)
    assert preview["takeProfitPct"] == 19
    assert preview["tpPrice"] == 119
    assert preview["nextDcaPrice"] == 95
    assert round(preview["expectedPnlAtTp"], 8) == 38
    assert round(preview["portfolioValueAtTp"], 8) == 189.65


def test_short_preview_reverses_dca_and_tp_direction():
    preview = position_action_preview(row=row("SHORT",100,95), state={"dcaCount":0,"lastBotFillPrice":100}, settings=cfg())
    assert preview["tpPrice"] == 81
    assert preview["nextDcaPrice"] == 105
    assert preview["tpDistanceUsd"] == 14
    assert preview["nextDcaDistanceUsd"] == 10


def test_normal_dca_cap_removes_next_level():
    preview = position_action_preview(row=row("LONG",100,100), state={"dcaCount":3,"lastBotFillPrice":90}, settings=cfg())
    assert preview["nextDcaPrice"] is None
    assert preview["nextDcaDistanceUsd"] is None


def test_unlimited_dca_keeps_next_level_after_many_fills():
    preview = position_action_preview(row=row("LONG",100,90), state={"dcaCount":99,"lastBotFillPrice":90}, settings=cfg(unlimitedDca=True))
    assert preview["nextDcaPrice"] == 85.5
    assert preview["nextDcaNumber"] == 100
