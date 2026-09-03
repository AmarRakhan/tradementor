from aster_multi_bb import MultiBbConfig, position_action_preview


def test_take_profit_accepts_free_positive_values_and_persists_toggle():
    for pct in (0.1, 0.25, 0.5, 1, 3.75, 19, 19.5, 23.75, 50):
        cfg = MultiBbConfig.from_mapping({"takeProfit": pct / 100, "takeProfitEnabled": True})
        assert cfg.take_profit == pct / 100
        assert cfg.public_dict()["takeProfitEnabled"] is True


def test_take_profit_disabled_suppresses_preview_target_but_keeps_value():
    cfg = MultiBbConfig.from_mapping({"takeProfit": 0.2375, "takeProfitEnabled": False})
    assert cfg.take_profit == 0.2375
    preview = position_action_preview(row={"positionSide":"LONG","entryPrice":100,"markPrice":130,"positionAmt":1}, state={}, settings=cfg, account_equity=1000)
    assert preview["takeProfitEnabled"] is False
    assert preview["takeProfitPct"] is None
    assert preview["tpPrice"] is None


def test_take_profit_rejects_non_positive_values_even_when_disabled():
    import pytest
    with pytest.raises(ValueError):
        MultiBbConfig.from_mapping({"takeProfit": 0, "takeProfitEnabled": False})
