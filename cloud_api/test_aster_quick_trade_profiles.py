from aster_multi_bb import MultiBbConfig, position_action_preview


def test_profiles_and_pair_overrides_round_trip():
    cfg = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1", "maximumPositions": 2, "longSlots": 1, "shortSlots": 1,
        "standardLong": {"minimumLeverage": 100, "maxDca": 3, "takeProfit": .015},
        "standardShort": {"minimumLeverage": 50, "maxDca": 2, "takeProfit": .01},
        "pairOverrides": {"btcusdt": {"maxDca": 5}},
    })
    saved = cfg.public_dict()
    assert saved["standardLong"]["minimumLeverage"] == 100
    assert saved["standardShort"]["maxDca"] == 2
    assert saved["pairOverrides"]["BTCUSDT"]["maxDca"] == 5
    assert cfg.effective_profile("BTCUSDT", "LONG")["maxDca"] == 5
    assert cfg.effective_profile("ETHUSDT", "LONG")["maxDca"] == 3


def test_pair_override_extends_existing_dca_without_reset():
    cfg = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1", "maximumPositions": 2, "longSlots": 1, "shortSlots": 1,
        "maxDca": 3, "pairOverrides": {"BTCUSDT": {"maxDca": 5}},
    })
    row = {"symbol": "BTCUSDT", "positionSide": "LONG", "entryPrice": 100, "markPrice": 100, "positionAmt": 1}
    preview = position_action_preview(row=row, state={"dcaCount": 3, "lastBotFillPrice": 100}, settings=cfg, account_equity=1000)
    assert preview["maxDca"] == 5
    assert preview["nextDcaNumber"] == 4
    assert preview["customSettings"] is True
