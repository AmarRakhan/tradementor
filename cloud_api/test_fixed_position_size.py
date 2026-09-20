from pathlib import Path

import pytest

from aster_leverage_tiers import resolve_entry
from aster_multi_bb import MultiBbConfig, effective_pair_settings


def payload(maximum: int):
    return [{"symbol": "TESTUSDT", "brackets": [{"notionalFloor": "0", "notionalCap": "1000000",
        "initialLeverage": maximum, "maintMarginRatio": "0.004"}]}]


def resolved(maximum: int, mode: str, margin: float = .30, notional: float = 6.0):
    return resolve_entry(payload(maximum), "TESTUSDT", configured_minimum=1, configured_maximum=maximum,
        entry_margin_usd=margin, entry_notional_usd=notional, entry_sizing_mode=mode)


def test_fixed_position_size_keeps_six_usdt_notional_across_leverage():
    at20 = resolved(20, "notional"); at50 = resolved(50, "notional"); at100 = resolved(100, "notional")
    assert at20["orderNotional"] == pytest.approx(6.0)
    assert at50["orderNotional"] == pytest.approx(6.0)
    assert at100["orderNotional"] == pytest.approx(6.0)
    assert at20["orderNotional"] / at20["leverage"] == pytest.approx(.30)
    assert at50["orderNotional"] / at50["leverage"] == pytest.approx(.12)
    assert at100["orderNotional"] / at100["leverage"] == pytest.approx(.06)


def test_margin_mode_retains_existing_variable_notional_behavior():
    assert resolved(20, "margin")["orderNotional"] == pytest.approx(6.0)
    assert resolved(50, "margin")["orderNotional"] == pytest.approx(15.0)


def test_side_specific_notional_roundtrips_without_collapsing_long_and_short():
    cfg = MultiBbConfig.from_mapping({"engine": "multi_bb_v1", "universeTopN": 50, "maximumPositions": 20,
        "longSlots": 10, "shortSlots": 10, "minimumLeverage": 20, "maximumLeverage": 50,
        "entrySizingMode": "notional", "entryMarginUsd": .30, "entryMarginLongUsd": .30,
        "entryMarginShortUsd": .30, "entryNotionalUsd": 6, "entryNotionalLongUsd": 6,
        "entryNotionalShortUsd": 9, "dcaMarginUsd": 2, "takeProfit": .015})
    public = cfg.public_dict(); effective = effective_pair_settings(cfg, "TESTUSDT")
    assert public["entrySizingMode"] == "notional"
    assert public["entryNotionalLongUsd"] == pytest.approx(6)
    assert public["entryNotionalShortUsd"] == pytest.approx(9)
    assert effective["entryNotionalLongUsd"] == pytest.approx(6)
    assert effective["entryNotionalShortUsd"] == pytest.approx(9)
    assert public["maximumLeverage"] == 50


def test_smart_rescue_notional_mode_derives_start_margin_from_actual_leverage():
    source = Path(__file__).with_name("aster_multi_bb.py").read_text(encoding="utf-8")
    assert "settings.entry_notional_long_usd/leverage" in source
    assert 'if settings.entry_sizing_mode=="notional" else settings.entry_margin_long_usd' in source
