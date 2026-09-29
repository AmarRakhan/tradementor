from __future__ import annotations

from pathlib import Path

from aster_multi_bb import MultiBbConfig, run_multi_bb_step
from aster_multi_bb_core import _remaining_strategy_capacity, _zone_entry_multiplier
from aster_zone_soldiers import ROLE_ZONE_BASE, claim_soldier, prepare_zone_runtime
from test_aster_multi_bb import Client, Ref


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


def test_zone_mode_uses_per_zone_free_seats_and_hard_global_maximum_positions():
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert "if zone_mode:" in source
    assert "long_need = len(available_soldiers" in source
    assert "short_need = len(available_soldiers" in source
    assert "_remaining_strategy_capacity(settings.maximum_positions, seat_capacity_position_count)" in source
    assert "zone_platform_ceiling" not in source
    assert "if not paired and not zone_mode:" in source


def test_build457_live_equity_selects_active_zone_without_current_candle_close_gate():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'portfolio_chart_latest_contiguous_candles(candles, "15m")' in source
    assert "history_ready = len(contiguous) >= 14" in source
    assert "history_fresh = bool(history_ready and latest_bucket >= current_bucket)" in source
    assert "equity = multi_bb_exchange_equity(account)" in source
    assert "active = confirmed_zone_from_display_zones(zones, equity)" in source
    assert "zone_ready = bool(active is not None)" in source
    assert '"zoneActivationRequiresCandleClose": False' in source
    assert '"zoneActivationSource": "LIVE_PORTFOLIO_EQUITY"' in source
    assert '"LIVE_EQUITY_ZONE_ACTIVE" if zone_ready' in source
    assert "zone_context=zone_context" in source


def test_build457_confirmed_active_zone_exposes_empty_seats_even_if_legacy_freshness_flag_is_false():
    zone_source = (ROOT / "aster_zone_soldiers.py").read_text(encoding="utf-8")
    assert "if confirmed_zone is not None:" in zone_source
    assert "active_zone=active_zone," in zone_source
    assert "active_zone=active_zone if zone_safe else None" not in zone_source
    assert '"safeForNewEntries": bool(active_zone is not None)' in zone_source
    assert '"entrySafe": bool(active_zone is not None)' in zone_source


def test_build457_global_130_cap_allows_exactly_one_more_strategy_position_at_129():
    assert _remaining_strategy_capacity(130, 129) == 1
    assert _remaining_strategy_capacity(130, 130) == 0
    assert _remaining_strategy_capacity(130, 131) == 0


def test_build470_zone_warriors_global_cap_counts_only_zone_owned_seats_not_legacy_strategy2_positions():
    now = 10_000
    zone_state, _, _ = prepare_zone_runtime(
        raw_zone_state={},
        managed_state={},
        positions=[],
        confirmed_zone=8,
        zone_safe=True,
        base_long=2,
        base_short=1,
        balancer_enabled=False,
        trigger_percent=20.0,
        release_percent=8.0,
        fallback_unit_notional=100.0,
        timestamp_ms=now,
    )
    long_soldier = claim_soldier(
        zone_state, "LONG", trade_key="ZONELOUSDT|LONG", symbol="ZONELOUSDT",
        entry_price=100.0, entry_portfolio_equity=300.0, timestamp_ms=now + 1,
    )
    short_soldier = claim_soldier(
        zone_state, "SHORT", trade_key="ZONESHUSDT|SHORT", symbol="ZONESHUSDT",
        entry_price=100.0, entry_portfolio_equity=300.0, timestamp_ms=now + 2,
    )
    assert long_soldier is not None and short_soldier is not None

    managed = {
        "ZONELOUSDT|LONG": {
            "cycleId": "zone-long", "cycleStartedAtMs": now + 1, "botManaged": True,
            "originZone": 8, "originZoneCycleId": long_soldier["originZoneCycleId"],
            "soldierId": long_soldier["soldierId"], "soldierRole": ROLE_ZONE_BASE,
        },
        "ZONESHUSDT|SHORT": {
            "cycleId": "zone-short", "cycleStartedAtMs": now + 2, "botManaged": True,
            "originZone": 8, "originZoneCycleId": short_soldier["originZoneCycleId"],
            "soldierId": short_soldier["soldierId"], "soldierRole": ROLE_ZONE_BASE,
        },
    }
    # These are older Strategy-2 positions from before Zone Warriors ownership.
    # They must still be managed, but they must not consume the 3-seat Zone
    # Warriors global cap.
    for index in range(4):
        managed[f"LEG{index}USDT|LONG"] = {
            "cycleId": f"legacy-{index}",
            "cycleStartedAtMs": 1_000 + index,
            "botManaged": True,
        }

    positions = [
        {"symbol": "ZONELOUSDT", "positionSide": "LONG", "positionAmt": "1", "entryPrice": "100", "markPrice": "100", "leverage": "100"},
        {"symbol": "ZONESHUSDT", "positionSide": "SHORT", "positionAmt": "1", "entryPrice": "100", "markPrice": "100", "leverage": "100"},
        *[
            {"symbol": f"LEG{index}USDT", "positionSide": "LONG", "positionAmt": "1", "entryPrice": "100", "markPrice": "100", "leverage": "100"}
            for index in range(4)
        ],
    ]
    client = Client(
        positions=positions,
        tickers=[{"symbol": "NEWUSDT", "quoteVolume": "9999"}],
        prices={**{row["symbol"]: 100 for row in positions}, "NEWUSDT": 100},
        leverage=100,
    )
    settings = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1",
        "universeTopN": 10,
        "maximumPositions": 3,
        "longSlots": 3,
        "shortSlots": 0,
        "minimumLeverage": 50,
        "entryMarginUsd": 5,
        "entryNotionalUsd": 250,
        "entrySizingMode": "notional",
        "dcaDistance": .003,
        "dcaMarginUsd": 2,
        "maxDca": 3,
        "takeProfit": .015,
        "zoneSoldiersEnabled": True,
        "zoneSoldiersOptInVersion": 1,
        "zoneBaseLongSoldiers": 2,
        "zoneBaseShortSoldiers": 1,
        "bollingerEntryFilter15mEnabled": False,
        "directionalBollingerEnabled": False,
    })

    result = run_multi_bb_step(
        client=client,
        ref=Ref(),
        raw_state={"multiBbPositions": managed, "zoneSoldierState": zone_state},
        settings=settings,
        uid="u",
        account={"availableBalance": "1000"},
        positions=positions,
        open_orders=[],
        timestamp_ms=now + 5_000,
        dry_run=True,
        order_budget=5,
        zone_context={"activeZone": 8, "safeForEntries": True},
    )

    assert result["accountPositionCount"] == 6
    assert result["strategyPositionCount"] == 6
    assert result["seatCapacityPositionCount"] == 2
    assert result["accountRemainingCapacity"] == 0  # one dry-run entry consumes the last Zone Warriors seat
    assert result["scannedCandidateCount"] >= 1
    assert any(row.get("kind") == "ENTRY" and row.get("symbol") == "NEWUSDT" and row.get("side") == "LONG" for row in result["actions"])
    assert result["entryStatus"] in {"ENTRY_PLANNED", "PARTIAL_FILL_PLANNED"}


def test_build457_zone_activation_does_not_bypass_existing_bollinger_entry_checks():
    source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    candidate_guard = source.index("def candidate_bb_pass(candidate_side: str) -> bool:")
    candidate_check = source.index("require_bollinger_entry(", candidate_guard)
    order = source.index("execute_leg_once(client, plan", candidate_check)
    assert candidate_guard < candidate_check < order
    assert "WAITING_BOLLINGER_ENTRY" in source

def test_build457_realtime_registry_includes_multi_bb_positions_for_intracandle_zone_reaction():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    start = source.index("def _aster_realtime_subscription_mapping()")
    end = source.index("def _aster_realtime_force_evaluate", start)
    block = source[start:end]
    assert 'multi_positions=raw.get("multiBbPositions")' in block
    assert "for key,row in multi_positions.items():" in block
    assert 'symbol=str(key).split("|",1)[0].upper().strip()' in block
    assert "if is_multi_bb:" in block



def test_build455_public_contract_exposes_price_zone_seat_alias():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"strategyMode":"PRICE_ZONE_SEATS"' in source
    assert '"priceZoneSeats":zone_report' in source


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


def test_zone_owned_rollout_uses_central_beta_stable_entitlement_not_owner_only_gate():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"zone_soldiers": {"status": "TESTEN", "beta": True, "stable": False}' in source
    assert "_OWNER_ONLY_RELEASE_FEATURES" not in source
    assert 'record = auth.get_user(str(uid), app=auth_app)' in source
    assert 'profile.get("betaOwner") is True' in source
    assert 'str(profile.get("releaseChannel") or "").upper() == "BETA"' in source
    assert 'beta_owner = bool(beta_candidate and _is_beta_owner_uid(uid))' in source
    assert 'return _release_channel_enabled(beta_owner, key)' in source
    assert '_release_feature_enabled_for_uid(uid, "zone_soldiers")' in source

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


def test_build445_unentitled_accounts_force_zone_mode_off_server_side_without_deleting_persisted_settings():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    start = source.index("def _strip_unreleased_beta_settings_for_uid(")
    end = source.index("def _admin_device_reference(", start)
    block = source[start:end]
    assert 'if _release_feature_enabled_for_uid(uid, "zone_soldiers"):' in block
    assert 'out["zoneSoldiersEnabled"] = False' in block
    assert 'out["zoneSoldiersOptInVersion"] = 0' in block
    assert "out = dict(settings)" in block
    assert ".set(" not in block


def test_build423_balancer_is_priority_only_and_fixed_formation_is_the_only_new_entry_capacity():
    zone_source = (ROOT / "aster_zone_soldiers.py").read_text(encoding="utf-8")
    core_source = (ROOT / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    assert '"mode": "PRIORITY_ONLY"' in zone_source
    assert '"desiredCount": 0' in zone_source
    assert 'soldier.get("role") == ROLE_ZONE_BASE' in zone_source
    assert '\n        _ensure_balancers(' not in zone_source
    assert 'priority = str(zone_report.get("entryPriority")' in core_source
    assert 'PRIORITY_ONLY changes ordering, never fixed-formation capacity.' in core_source
    assert 'merely because the priority side\'s fixed formation is full.' not in core_source


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



def test_live_zone_seat_sync_precedes_dynamic_hedge_branch():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tick_start = source.index("def _run_aster_strategy2_tick(")
    tick = source[tick_start:]
    zone_context_index = tick.index("zone_context = _strategy2_zone_runtime_context")
    seat_sync_index = tick.index("raw = _sync_price_zone_seat_runtime", zone_context_index)
    dynamic_index = tick.index("dynamic_ref=user_reference", seat_sync_index)
    assert zone_context_index < seat_sync_index < dynamic_index


def test_live_zone_seat_sync_does_not_persist_managed_positions():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    helper_start = source.index("def _sync_price_zone_seat_runtime(")
    helper_end = source.index("def _run_aster_strategy2_tick(", helper_start)
    helper = source[helper_start:helper_end]
    assert "prepare_zone_runtime(" in helper
    assert '"zoneSoldierState": zone_state' in helper
    assert '"zoneSoldierReport": zone_report' in helper
    assert '"multiBbPositions":' not in helper


def test_price_zone_public_snapshot_exposes_read_only_entry_blocker_diagnostics():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"entryDiagnostics":entry_diagnostics' in source
    assert '"dynamicHedge":{' in source
    assert '"blocking":dynamic_blocking' in source
    assert '"entryStatus":str(report.get("entryStatus") or "")' in source
    assert '"entrySkipReasons"' in source
    assert '"haltedUncertain"' in source


def test_live_zone_seat_presync_explicitly_skips_legacy_migration():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    helper_start = source.index("def _sync_price_zone_seat_runtime(")
    helper_end = source.index("def _run_aster_strategy2_tick(", helper_start)
    helper = source[helper_start:helper_end]
    assert "migrate_legacy=False" in helper

    zone_source = (ROOT / "aster_zone_soldiers.py").read_text(encoding="utf-8")
    assert "migrate_legacy: bool = True" in zone_source
    assert "if migrate_legacy:" in zone_source
