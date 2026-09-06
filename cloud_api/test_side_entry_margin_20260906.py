from aster_multi_bb import MultiBbConfig, _side_value


def base(**overrides):
    raw = {
        "engine": "multi_bb_v1",
        "universeTopN": 30,
        "maximumPositions": 2,
        "longSlots": 1,
        "shortSlots": 1,
        "minimumLeverage": 50,
        "entrySizingMode": "margin",
        "entryMarginUsd": 0.30,
        "dcaDistance": 0.003,
        "dcaMarginUsd": 0.20,
        "maxDca": 3,
        "takeProfit": 0.015,
        "takeProfitEnabled": True,
    }
    raw.update(overrides)
    return raw


def test_legacy_shared_entry_margin_falls_back_to_both_sides():
    cfg = MultiBbConfig.from_mapping(base(entryMarginUsd=0.35))
    assert cfg.entry_margin_long_usd == 0.35
    assert cfg.entry_margin_short_usd == 0.35
    saved = cfg.public_dict()
    assert saved["entryMarginLongUsd"] == 0.35
    assert saved["entryMarginShortUsd"] == 0.35
    assert saved["entryMarginUsd"] == 0.35


def test_explicit_long_short_entry_margins_are_independent():
    cfg = MultiBbConfig.from_mapping(base(entryMarginLongUsd=0.35, entryMarginShortUsd=0.30))
    assert cfg.entry_margin_long_usd == 0.35
    assert cfg.entry_margin_short_usd == 0.30
    assert _side_value(cfg, {}, "LONG", "entry_margin_usd") == 0.35
    assert _side_value(cfg, {}, "SHORT", "entry_margin_usd") == 0.30
    saved = cfg.public_dict()
    assert saved["entryMarginLongUsd"] == 0.35
    assert saved["entryMarginShortUsd"] == 0.30


def test_changing_long_does_not_change_short_and_reverse():
    cfg = MultiBbConfig.from_mapping(base(entryMarginLongUsd=0.40, entryMarginShortUsd=0.25))
    cfg2 = MultiBbConfig.from_mapping({**cfg.public_dict(), "entryMarginLongUsd": 0.55})
    assert cfg2.entry_margin_long_usd == 0.55
    assert cfg2.entry_margin_short_usd == 0.25
    cfg3 = MultiBbConfig.from_mapping({**cfg2.public_dict(), "entryMarginShortUsd": 0.45})
    assert cfg3.entry_margin_long_usd == 0.55
    assert cfg3.entry_margin_short_usd == 0.45


def test_short_dca_three_percent_stays_three_percent():
    cfg = MultiBbConfig.from_mapping(base(longDcaDistance=0.003, shortDcaDistance=0.03))
    assert cfg.long_dca_distance == 0.003
    assert cfg.short_dca_distance == 0.03
    saved = cfg.public_dict()
    assert saved["longDcaDistance"] == 0.003
    assert saved["shortDcaDistance"] == 0.03


def test_pair_override_shared_entry_margin_still_wins_for_that_pair():
    cfg = MultiBbConfig.from_mapping(base(
        entryMarginLongUsd=0.35,
        entryMarginShortUsd=0.30,
        pairOverrides={"BTCUSDT": {"enabled": True, "entryMarginUsd": 0.50}},
    ))
    override = cfg.pair_overrides["BTCUSDT"]
    assert _side_value(cfg, override, "LONG", "entry_margin_usd") == 0.50
    assert _side_value(cfg, override, "SHORT", "entry_margin_usd") == 0.50
