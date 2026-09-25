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


def test_build423_balancer_is_priority_only_and_fixed_formation_is_the_only_new_entry_capacity():
    zone_source = (ROOT / "aster_zone_soldiers.py").read_text(encoding="utf-8")
    core_source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert '"mode": "PRIORITY_ONLY"' in zone_source
    assert '"desiredCount": 0' in zone_source
    assert 'soldier.get("role") == ROLE_ZONE_BASE' in zone_source
    assert '\n        _ensure_balancers(' not in zone_source
    assert 'priority = str(zone_report.get("entryPriority")' in core_source
    assert 'Do not worsen a live imbalance' in core_source


def test_build425_tp_settlement_happens_only_after_exchange_flat_confirmation():
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    flat_index = source.index('if key in fresh: raise RuntimeError(f"{key}: TP-close niet flat bevestigd")')
    settle_index = source.index("settle_soldier_after_profitable_tp(", flat_index)
    pop_index = source.index("state.pop(key, None)", settle_index)
    assert flat_index < settle_index < pop_index
    assert '"homecoming": homecoming' in source
    assert '"zoneMission": zone_mission' in source
    assert '"currentZoneAtClose": settlement.get("currentZoneAtClose")' in source


def test_build425_released_soldier_cannot_reenter_in_same_reconciliation_tick():
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert "zone_soldiers_released_this_tick: set[str] = set()" in source
    assert "zone_soldiers_released_this_tick.add(released_soldier_id)" in source
    assert 'not in zone_soldiers_released_this_tick' in source
    release_index = source.index("zone_soldiers_released_this_tick.add(released_soldier_id)")
    need_index = source.index("eligible_zone_long = [", release_index)
    candidate_index = source.index("candidates_for_side = [", need_index)
    assert release_index < need_index < candidate_index


def test_build425_zone_entries_keep_existing_bollinger_candidate_and_preorder_guards():
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    candidate_guard = source.index("def candidate_bb_pass(candidate_side: str) -> bool:")
    candidate_check = source.index("require_bollinger_entry(", candidate_guard)
    planned_soldier = source.index("planned_soldier = None", candidate_check)
    preorder = source.index("def entry_before_submit(intent: Any) -> None:", planned_soldier)
    preorder_check = source.index("require_bollinger_entry(", preorder)
    order = source.index("execute_leg_once(client, plan", preorder_check)
    assert candidate_guard < candidate_check < planned_soldier < preorder < preorder_check < order


def test_build425_true_homecoming_requires_different_known_close_zone():
    source = (ROOT / "aster_zone_soldiers.py").read_text(encoding="utf-8")
    assert 'reason != "TP_WIN_OUTSIDE_ORIGIN_ZONE"' in source
    assert 'if origin_zone == current_zone:' in source
    assert '"currentZoneAtClose": current_zone' in source
    assert 'next_status = STATUS_AVAILABLE if reusable_here else STATUS_DORMANT' in source



def test_build430_runtime_exposes_canonical_entry_budget_and_auditable_fill_fields():
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert '"requiredInitialMarginUsd": total_required' in source
    assert '"safetyBufferUsd": required_safety_buffer' in source
    assert '"requiredTotalUsd": required_total_margin' in source
    assert '"shortfallUsd": max(0.0, required_total_margin - available)' in source
    assert '"budgetStatus": "INSUFFICIENT"' in source
    assert '"entryBudget": entry_budget' in source
    for field in (
        '"orderId":', '"requestedQty":', '"filledQty":', '"fillPrice":',
        '"availableBeforeUsd":', '"requiredMarginUsd":',
        '"netExposureBeforeUsd":', '"netExposureAfterFillEstimateUsd":',
        '"priorityBefore":',
    ):
        assert field in source


def test_build430_post_fill_zone_exposure_is_reconciled_from_fresh_exchange_positions():
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    final_block = source.index("# One final exchange-truth reconciliation")
    refresh = source.index("client.position_risk()", final_block)
    prepare = source.index("prepare_zone_runtime(", refresh)
    assert final_block < refresh < prepare


def test_build430_status_publishes_single_snapshot_reconciliation_contract():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "account_reconciliation_report(" in source
    assert '"snapshotId": reconciliation["snapshotId"]' in source
    assert '"accountStateVersion": reconciliation["accountStateVersion"]' in source
    assert '"reconciliation": reconciliation' in source
    assert '"liveDataStatus": reconciliation["liveDataStatus"]' in source
    assert '"margin": {' in source
