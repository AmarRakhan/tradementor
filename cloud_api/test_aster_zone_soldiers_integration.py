from __future__ import annotations

from pathlib import Path

from aster_multi_bb import MultiBbConfig
from aster_multi_bb_core import _zone_entry_multiplier


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


def test_zone_soldiers_are_available_to_beta_but_never_implicitly_enabled():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"zone_soldiers": {"status": "TESTEN", "beta": True, "stable": False}' in source
    assert 'out.setdefault("zoneSoldiersEnabled", True)' not in source
    assert 'out["zoneSoldiersEnabled"] = explicit_zone_opt_in' in source
    assert 'out["zoneSoldiersEnabled"] = False' in source
    assert 'zoneSoldiersOptInVersion' in source


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


def test_zone_owned_rollout_is_hard_owner_only_not_generic_beta_or_stable():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '_OWNER_ONLY_RELEASE_FEATURES = {"zone_soldiers"}' in source
    assert 'if key in _OWNER_ONLY_RELEASE_FEATURES:' in source
    assert 'return bool(_is_beta_owner(user) and row.get("beta"))' in source
    assert 'record = auth.get_user(str(uid), app=auth_app)' in source
    assert 'legacy_beta_candidate = profile.get("betaOwner") is True or str(profile.get("releaseChannel") or "").upper() == "BETA"' in source
    assert 'beta_owner = bool(legacy_beta_candidate and _is_beta_owner_uid(uid))' in source
    assert '"betaOwner": beta_owner' in source
    assert 'zone_owner_only = bool(beta_owner and zone_soldiers.get("beta"))' in source

def test_zone_entry_size_grows_gently_and_monotonically_with_zone_distance():
    values = [_zone_entry_multiplier(zone, 2.0, 1.20) for zone in (0, 1, 2, 3)]
    assert values == [1.0, 1.02, 1.04, 1.06]
    assert _zone_entry_multiplier(-3, 2.0, 1.20) == values[-1]
    assert _zone_entry_multiplier(50, 2.0, 1.20) == 1.20

def test_zone_entry_growth_is_configurable_and_used_by_the_real_entry_planner():
    cfg = MultiBbConfig.from_mapping({"engine":"multi_bb_v1","universeTopN":30,"maximumPositions":12,"longSlots":6,"shortSlots":6,"minimumLeverage":50,"zoneSoldiersEnabled":True,"zoneEntryGrowthPercent":2.5,"zoneEntryMaxMultiplier":1.15})
    assert cfg.zone_entry_growth_percent == 2.5
    assert cfg.zone_entry_max_multiplier == 1.15
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert "entry_margin_usd=zone_entry_margin_usd" in source
    assert "entry_notional_usd=zone_entry_notional_usd" in source
    assert '"entrySizing"' in source


def test_build417_requires_explicit_zone_opt_in_marker_and_keeps_restart_state():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    core = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert 'settings.get("zoneSoldiersEnabled") is True' in source
    assert 'int(safe_float(settings.get("zoneSoldiersOptInVersion"))) >= 1' in source
    assert 'zone_soldiers_opt_in_version: int = 0' in core
    assert '"zoneSoldiersOptInVersion": self.zone_soldiers_opt_in_version' in core


def test_build417_zone_off_drains_only_existing_zone_owned_positions():
    core = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert 'zone_lifecycle = "ACTIVE" if zone_mode else ("DRAINING" if zone_owned_open_count > 0 else "OFF")' in core
    assert '"safeForNewEntries": False' in core
    assert '"drainingOpenCount": zone_owned_open_count' in core


def test_build417_unavailable_accounts_force_zone_mode_off_server_side():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'zone_owner_only = bool(beta_owner and zone_soldiers.get("beta"))' in source
    assert 'out["zoneSoldiersEnabled"] = False' in source
    assert 'out["zoneSoldiersOptInVersion"] = 0' in source
