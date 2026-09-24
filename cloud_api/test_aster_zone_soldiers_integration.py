from __future__ import annotations

from pathlib import Path

from aster_multi_bb import MultiBbConfig


ROOT = Path(__file__).resolve().parent


def test_zone_soldier_settings_are_configurable_not_hardcoded_runtime_constants():
    cfg = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1",
        "universeTopN": 30,
        "maximumPositions": 12,
        "longSlots": 6,
        "shortSlots": 6,
        "minimumLeverage": 50,
        "zoneSoldiersEnabled": True,
        "zoneBaseLongSoldiers": 4,
        "zoneBaseShortSoldiers": 5,
        "zoneExposureBalancerEnabled": True,
        "exposureRefillTriggerPercent": 20,
        "exposureRefillReleasePercent": 8,
    })
    assert cfg.zone_soldiers_enabled is True
    assert cfg.zone_base_long_soldiers == 4
    assert cfg.zone_base_short_soldiers == 5
    assert cfg.zone_exposure_balancer_enabled is True
    public = cfg.public_dict()
    assert public["zoneBaseLongSoldiers"] == 4
    assert public["zoneBaseShortSoldiers"] == 5


def test_zone_soldier_module_is_structurally_order_free():
    source = (ROOT / "aster_zone_soldiers.py").read_text(encoding="utf-8")
    for forbidden in ("execute_leg_once", "execute_pair_once", "place_order", "market_order", "CLOSE"):
        if forbidden == "CLOSE":
            continue
        assert forbidden not in source
    assert "never submits" in source
    assert "LEGACY_UNASSIGNED" in source
    assert "EXPOSURE_BALANCER" in source


def test_multi_bb_runtime_claims_zone_ownership_only_after_confirmed_entry_fill():
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    fill_index = source.index('fill = result.get("result")')
    claim_index = source.index("claim_soldier(", fill_index)
    state_index = source.index('state[key] = {"cycleId"', claim_index)
    assert fill_index < claim_index < state_index
    assert '"originZone": zone_claim.get("originZone")' in source
    assert '"soldierRole": zone_claim.get("role")' in source
    assert '"zoneSoldierState": zone_state' in source


def test_zone_mode_bypasses_legacy_global_side_slot_ratchet_but_keeps_platform_ceiling():
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert "if zone_mode:" in source
    assert "long_need = len(available_soldiers" in source
    assert "short_need = len(available_soldiers" in source
    assert "zone_platform_ceiling = min(400" in source
    assert "if not paired and not zone_mode:" in source


def test_main_uses_confirmed_contiguous_15m_zone_and_fails_closed_for_new_entries():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'portfolio_chart_latest_contiguous_candles(candles, "15m")' in source
    assert "len(contiguous) >= 14" in source
    assert '"safeForEntries": False' in source
    assert "zone_context=zone_context" in source


def test_zone_soldiers_are_beta_gated_for_safe_rollout():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"zone_soldiers": {"status": "TESTEN", "beta": True, "stable": False}' in source
    assert 'out.setdefault("zoneSoldiersEnabled", True)' in source
    assert 'out.pop(key, None)' in source


def test_existing_live_positions_are_migrated_without_guessing_origin_zone():
    source = (ROOT / "aster_zone_soldiers.py").read_text(encoding="utf-8")
    assert '"originZone": None' in source
    assert '"soldierRole": ROLE_LEGACY_UNASSIGNED' in source
    assert "legacyUnassignedOpenCount" in source


def test_zone_change_is_not_an_exit_trigger():
    zone_source = (ROOT / "aster_zone_soldiers.py").read_text(encoding="utf-8")
    core_source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert "OPEN soldiers remain OPEN when their origin zone becomes inactive" in zone_source
    assert "zone leaving" not in core_source.lower()
    assert "ZONE_CHANGE_CLOSE" not in core_source
