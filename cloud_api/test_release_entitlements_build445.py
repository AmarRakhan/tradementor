from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
AUTO = (ROOT / "aster_position_loss_auto_hedge_extension.py").read_text(encoding="utf-8")
LEGACY = (ROOT / "aster_legacy_hedge_scale_extension.py").read_text(encoding="utf-8")


def _slice(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    finish = source.index(end, begin)
    return source[begin:finish]


def test_build445_registers_every_requested_release_block_fail_closed():
    for key in (
        "bot_configurator_v2",
        "directional_bollinger",
        "exposure_refill",
        "margin_summary",
        "price_zones",
        "zone_soldiers",
        "zone_command_center",
        "auto_hedge_v2",
        "legacy_hedge_recovery",
    ):
        assert f'"{key}"' in MAIN
    assert '"legacy_hedge_recovery": ("auto_hedge_v2",)' in MAIN
    assert "_OWNER_ONLY_RELEASE_FEATURES" not in MAIN
    assert 'detail=f"FEATURE_NOT_RELEASED: {key}"' in MAIN


def test_price_zones_stays_in_build_and_has_no_stable_default():
    assert '"price_zones": {"status": "IN_BOUW", "beta": False, "stable": False}' in MAIN
    admin = _slice(MAIN, 'def update_release_feature(', '@app.get("/v1/me/preferences/interface")')
    assert 'feature_key == "price_zones"' in admin
    assert "Price zones blijft IN_BOUW" in admin


def test_fake_beta_profile_never_grants_beta_entitlement_without_identity_verification():
    gate = _slice(MAIN, "def _release_feature_enabled_for_uid(", "def require_release_feature(")
    assert 'profile.get("betaOwner") is True' in gate
    assert 'str(profile.get("releaseChannel") or "").upper() == "BETA"' in gate
    assert "_is_beta_owner_uid(uid)" in gate
    assert "beta_owner = bool(beta_candidate and _is_beta_owner_uid(uid))" in gate


def test_release_admin_changes_entitlement_only_never_runtime_or_trading_state():
    admin = _slice(MAIN, 'def update_release_feature(', '@app.get("/v1/me/preferences/interface")')
    assert 'db.collection("releaseFeatures").document(feature_key).set' in admin
    for forbidden in (
        "strategy2/settings",
        "asterPositionLossAutoHedge",
        "_run_uid(",
        "submit_order",
        "place_order",
        "zoneSoldiersEnabled",
        "enabled": True",
    ):
        assert forbidden not in admin


def test_settings_filter_is_copy_only_and_entitlement_driven():
    start = MAIN.index("def _strip_unreleased_beta_settings_for_uid(")
    end = MAIN.index("def _admin_device_reference(", start)
    block = MAIN[start:end]
    assert "out = dict(settings)" in block
    assert '_release_feature_enabled_for_uid(uid, "directional_bollinger")' in block
    assert '_release_feature_enabled_for_uid(uid, "exposure_refill")' in block
    assert '_release_feature_enabled_for_uid(uid, "zone_soldiers")' in block
    assert '_release_feature_enabled_for_uid(uid, "price_zones")' in block
    assert ".set(" not in block


def test_auto_hedge_and_legacy_routes_are_backend_authoritative():
    assert 'main.require_release_feature(user, "auto_hedge_v2")' in AUTO
    assert 'main.require_release_feature(user, "legacy_hedge_recovery")' in LEGACY
    assert "main.require_continuity_owner(user)" not in AUTO
    assert "main.require_continuity_owner(user)" not in LEGACY
    assert '"requires": ["auto_hedge_v2"]' in LEGACY


def test_auto_hedge_rollout_rollback_never_abandons_existing_locks():
    assert "if not entitled and not has_existing_lock" in AUTO
    assert "allow_new_triggers=entitled" in AUTO
    assert 'settings.get("enabled") is True and allow_new_triggers' in AUTO
    assert 'state.get("rehedgeEnabled") is True and allow_new_triggers' in AUTO
    assert 'collection("asterPositionLossAutoHedge").stream()' in AUTO


def test_legacy_restart_recovery_only_resumes_already_user_confirmed_operations():
    recovery = _slice(LEGACY, "def _recover_user_confirmed_operations(", "@main.app.on_event")
    assert 'row.get("userConfirmed") is not True' in recovery
    assert "RECOVERABLE_OPERATION_STATUSES" in recovery
    assert "_resume_operation(uid, snapshot.id)" in recovery


def test_continuity_and_admin_security_remain_owner_admin_only():
    assert "def require_continuity_owner(" in MAIN
    assert "def require_admin(" in MAIN
    assert 'require_continuity_owner(user)' in MAIN
    assert 'require_admin(user)' in MAIN
    continuity = _slice(MAIN, "def require_continuity_owner(", "def continuity_settings_reference(")
    assert "uid != owner_uid" in continuity
    assert "_is_beta_owner(user)" in continuity
