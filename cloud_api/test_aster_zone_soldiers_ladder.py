from __future__ import annotations

from pathlib import Path

from aster_zone_soldiers import confirmed_zone_from_display_zones


ROOT = Path(__file__).resolve().parent


def test_backend_signed_zone_matches_extrapolated_display_ladder():
    zones = [
        {"index": -1, "center": 144.0, "atr": 0.5},
        {"index": 0, "center": 146.0, "atr": 0.5},
    ]
    assert confirmed_zone_from_display_zones(zones, 143.2) == -1
    assert confirmed_zone_from_display_zones(zones, 145.8) == 0
    assert confirmed_zone_from_display_zones(zones, 147.2) == 1
    assert confirmed_zone_from_display_zones(zones, 151.5) == 3

def test_backend_extends_same_ladder_beyond_original_plus_three_window():
    zones = [
        {"index": -1, "center": 144.0, "atr": 0.5},
        {"index": 0, "center": 146.0, "atr": 0.5},
    ]
    assert confirmed_zone_from_display_zones(zones, 153.9) == 4
    assert confirmed_zone_from_display_zones(zones, 155.9) == 5


def test_backend_extends_same_ladder_beyond_original_minus_three_window():
    zones = [
        {"index": 0, "center": 146.0, "atr": 0.5},
        {"index": 1, "center": 148.0, "atr": 0.5},
    ]
    assert confirmed_zone_from_display_zones(zones, 138.1) == -4
    assert confirmed_zone_from_display_zones(zones, 136.1) == -5



def test_first_legacy_migration_tick_is_explicitly_held_before_new_zone_entries():
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert 'zone_migration_hold = bool(_i((zone_report or {}).get("legacyMigratedThisTick")) > 0)' in source
    assert 'long_need = 0 if zone_migration_hold' in source
    assert 'short_need = 0 if zone_migration_hold' in source
    assert '"zoneMigrationHold": zone_migration_hold' in source


def test_server_zone_context_uses_the_same_extrapolated_signed_ladder():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "confirmed_zone_from_display_zones(zones, equity)" in source
    assert 'portfolio_chart_latest_contiguous_candles(candles, "15m")' in source
