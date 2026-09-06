from aster_multi_bb_core import MultiBbConfig


def test_manual_selection_keeps_total_seat_cap_and_allows_hybrid_candidates():
    cfg = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1",
        "universeTopN": 50,
        "maximumPositions": 50,
        "longSlots": 25,
        "shortSlots": 25,
        "manualSymbolSelectionEnabled": True,
        "manualSymbols": [
            {"symbol": f"M{i}USDT", "side": "LONG" if i % 2 == 0 else "SHORT"}
            for i in range(8)
        ],
    })
    assert cfg.maximum_positions == 50
    assert len(cfg.manual_symbols) == 8
    assert cfg.long_slots + cfg.short_slots == 50


def test_manual_positions_still_use_normal_management_capacity_contract():
    cfg = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1",
        "universeTopN": 30,
        "maximumPositions": 10,
        "longSlots": 5,
        "shortSlots": 5,
        "manualSymbolSelectionEnabled": True,
        "manualSymbols": [{"symbol": "BTCUSDT", "side": "LONG"}],
    })
    assert cfg.manual_symbol_selection_enabled is True
    assert cfg.manual_symbols == (("BTCUSDT", "LONG"),)
