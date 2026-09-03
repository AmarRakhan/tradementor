from pathlib import Path
from aster_multi_bb import MultiBbConfig, ENGINE

HERE=Path(__file__).resolve().parent


def test_new_engine_replaces_focus_configuration_contract():
    cfg=MultiBbConfig.from_mapping({"engine":ENGINE,"universeTopN":30,"maximumPositions":30,"longSlots":20,"shortSlots":10,
        "minimumLeverage":50,"entryMarginUsd":5,"dcaDistance":.003,"dcaMarginUsd":2,"maxDca":3,"takeProfit":.015})
    assert cfg.long_slots==20 and cfg.short_slots==10 and cfg.take_profit==.015


def test_direct_panel_contains_only_multi_bb_strategy_controls():
    ui=(HERE.parent/"web/components/aster-strategy2-maker.tsx").read_text()
    for token in ("Botinstellingen","Top-N volume","LONG slots","SHORT slots","Minimum leverage","DCA margin","Globale DCA-limiet"):
        assert token in ui
    assert "Geen wizard" in ui
    assert "1-minuut Bollinger-entry" not in ui
    for retired in ("Focus 2.0 gebruiken","Start LONG + SHORT 1:1","Portfolio-doel modus","PORTFOLIO AIRBAG","Money Grabber"):
        assert retired not in ui


def test_direct_panel_is_cross_and_manual_selection_is_exchange_truth_aware():
    ui=(HERE.parent/"web/components/aster-strategy2-maker.tsx").read_text()
    assert "CROSS" in ui
    assert "Zelf munten kiezen" in ui
    assert "leverage-tiers" in ui
    assert "entryOrderValid" in ui
