from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
AUTO = (ROOT / "aster_position_loss_auto_hedge_extension.py").read_text(encoding="utf-8")
LEGACY = (ROOT / "aster_legacy_hedge_scale_extension.py").read_text(encoding="utf-8")


def test_build443_has_one_central_release_contract_for_product_features():
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
    assert "_OWNER_ONLY_RELEASE_FEATURES" not in MAIN
    assert '"legacy_hedge_recovery": ("auto_hedge_v2",)' in MAIN
    assert '"ownerOnly": False' in MAIN
    assert '"dependencies": list(_RELEASE_FEATURE_DEPENDENCIES.get(key, ()))' in MAIN


def test_settings_and_strategy_runtime_are_entitlement_driven_not_stored_beta_channel():
    assert "_require_release_gated_settings(user, request.settings)" in MAIN
    assert 'return _strip_unreleased_beta_settings(settings, _release_user_for_uid(str(uid)))' in MAIN
    assert '_release_feature_enabled_for_uid(uid, "zone_soldiers")' in MAIN
    public_start = MAIN.index("def aster_strategy2_public")
    public_end = MAIN.index("def ", public_start + 10)
    public = MAIN[public_start:public_end]
    assert 'releaseChannel") or "").upper() == "BETA"' not in public


def test_auto_hedge_routes_and_worker_are_release_entitled_and_multi_user():
    assert 'main.require_release_feature(user, "auto_hedge_v2")' in AUTO
    assert "main.require_continuity_owner(user)" not in AUTO
    assert 'main._release_feature_enabled_for_uid(uid, "auto_hedge_v2")' in AUTO
    assert 'main.db.collection("asterPositionLossAutoHedge").stream()' in AUTO
    assert "allow_rehedge=entitled" in AUTO
    assert 'settings = {**settings, "enabled": False}' in AUTO
    assert '"ownerOnly": False' in AUTO


def test_legacy_recovery_requires_release_entitlement_but_restart_recovery_remains_safe():
    assert 'main.require_release_feature(user, "legacy_hedge_recovery")' in LEGACY
    assert "main.require_continuity_owner(user)" not in LEGACY
    assert 'main.db.collection("asterPositionLossAutoHedge").stream()' in LEGACY
    assert "userConfirmed" in LEGACY
    assert "RECOVERABLE_OPERATION_STATUSES" in LEGACY


def test_continuity_and_admin_remain_private():
    assert "def require_continuity_owner" in MAIN
    assert 'require_continuity_owner(user)' in MAIN
    assert "def require_admin" in MAIN
    assert '@app.put("/v1/admin/releases/{feature_key}")' in MAIN
    admin_section = MAIN[MAIN.index('def update_release_feature'):MAIN.index('@app.get("/v1/me/preferences/interface")')]
    assert "require_admin(user)" in admin_section


def test_no_release_default_is_stable_enabled():
    defaults = MAIN[MAIN.index("_RELEASE_FEATURE_DEFAULTS"):MAIN.index("_RELEASE_FEATURE_DEPENDENCIES")]
    assert '"stable": True' not in defaults
