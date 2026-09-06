from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"Expected snippet not found in {path}: {old[:220]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


core = "cloud_api/aster_multi_bb_core.py"

replace_once(
    core,
    '        maximum_capacity = 200 if self.manual_symbol_selection_enabled else (self.universe_top_n * 2 if self.asymmetric_hedge_enabled else self.universe_top_n)',
    '        maximum_capacity = 200 if self.manual_symbol_selection_enabled else self.universe_top_n * 2',
)

replace_once(
    core,
    '        if symbol in active_symbols or symbol not in info_map or prices.get(symbol, 0) <= 0: continue',
    '        if (settings.asymmetric_hedge_enabled and symbol in active_symbols) or symbol not in info_map or prices.get(symbol, 0) <= 0: continue',
)

old_side = '''        else:\n            side = _next_entry_side(long_count=long_count,short_count=short_count,long_slots=settings.long_slots,short_slots=settings.short_slots)\n            if not side: break\n'''
new_side = '''        else:\n            side = _next_entry_side(long_count=long_count,short_count=short_count,long_slots=settings.long_slots,short_slots=settings.short_slots)\n            if not side: break\n\n        # In normal Multi-DCA mode LONG and SHORT are independent seats.\n        # An open BTCUSDT|LONG must never block BTCUSDT|SHORT (or vice versa).\n        # Manual selection keeps its explicitly chosen side; automatic mode may\n        # fall back to the missing opposite side when the preferred side is\n        # already open on the same symbol.\n        if not settings.asymmetric_hedge_enabled:\n            selected_key = f"{symbol}|{side}"\n            if selected_key in active:\n                if settings.manual_symbol_selection_enabled:\n                    continue\n                opposite = "SHORT" if side == "LONG" else "LONG"\n                opposite_need = short_need if opposite == "SHORT" else long_need\n                if opposite_need > 0 and f"{symbol}|{opposite}" not in active:\n                    side = opposite\n                else:\n                    continue\n'''
replace_once(core, old_side, new_side)

# The old capacity regression encoded one-position-per-symbol. Normal Multi-DCA
# now intentionally supports one LONG plus one SHORT per symbol, so Top-N 1 has
# capacity 2. Keep a failing case at 3 to protect the 2x universe ceiling.
replace_once(
    "cloud_api/test_aster_multi_bb.py",
    '    with pytest.raises(ValueError): cfg(universeTopN=1,maximumPositions=2,longSlots=1,shortSlots=1)',
    '    cfg(universeTopN=1,maximumPositions=2,longSlots=1,shortSlots=1)\n    with pytest.raises(ValueError): cfg(universeTopN=1,maximumPositions=3,longSlots=2,shortSlots=1)',
)


test_path = Path("cloud_api/test_same_symbol_dual_side_20260906.py")
if not test_path.exists():
    test_path.write_text(r'''from pathlib import Path

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
''', encoding="utf-8")
