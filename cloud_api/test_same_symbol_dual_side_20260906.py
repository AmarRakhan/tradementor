from pathlib import Path

from aster_multi_bb_core import MultiBbConfig


def test_normal_multi_dca_capacity_counts_symbol_side_seats():
    cfg = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1",
        "universeTopN": 25,
        "maximumPositions": 50,
        "longSlots": 25,
        "shortSlots": 25,
        "minimumLeverage": 50,
        "entryMarginUsd": .3,
        "entryNotionalUsd": 15,
        "entrySizingMode": "margin",
        "dcaDistance": .003,
        "dcaMarginUsd": .3,
        "maxDca": 10,
        "takeProfit": .015,
        "takeProfitEnabled": True,
    })
    assert cfg.maximum_positions == 50
    assert cfg.long_slots == 25
    assert cfg.short_slots == 25


def test_scanner_blocks_only_same_side_in_normal_mode():
    source = Path("aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert '(settings.asymmetric_hedge_enabled and symbol in active_symbols)' in source
    assert 'selected_key = f"{symbol}|{side}"' in source
    assert 'opposite = "SHORT" if side == "LONG" else "LONG"' in source
    assert 'f"{symbol}|{opposite}" not in active' in source
    assert 'if symbol in active_symbols or symbol not in info_map' not in source
