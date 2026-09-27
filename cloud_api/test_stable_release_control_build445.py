from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish-stable-build445.yml"


def workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_build445_stable_release_is_owner_and_exact_request_gated() -> None:
    text = workflow()
    assert 'github.actor == \'AmarRakhan\'' in text
    assert 'test "$GITHUB_ACTOR" = "AmarRakhan"' in text
    assert '".github/release-requests/stable-build445.json"' in text
    assert 'request["confirmation"] != "PUBLISH_STABLE_RELEASE"' in text
    assert 'request["requestedBy"] != "AmarRakhan"' in text
    assert 'request["action"] != "publish-stable-release"' in text
    assert "environment: production" in text


def test_build445_stable_release_has_exact_approved_allowlist() -> None:
    text = workflow()
    approved = (
        "bot_configurator_v2",
        "directional_bollinger",
        "exposure_refill",
        "margin_summary",
        "zone_soldiers",
        "zone_command_center",
        "auto_hedge_v2",
        "legacy_hedge_recovery",
    )
    for key in approved:
        assert key in text
    assert 'request["features"] != allowed' in text
    assert '"status": "LIVE"' in text
    assert '"stable": True' in text


def test_price_zones_is_explicitly_kept_unreleased() -> None:
    text = workflow()
    assert 'document("price_zones")' in text
    assert '"status": "IN_BOUW"' in text
    assert '"beta": False' in text
    assert '"stable": False' in text


def test_release_control_waits_for_exact_backend_source_and_keeps_health() -> None:
    text = workflow()
    assert 'production source mismatch:' in text
    assert 'health.get("sourceCommit") or health.get("imageSourceCommit")' in text
    assert "Verify production backend remained healthy" in text
    assert "google-github-actions/auth@v2" in text


def test_release_control_only_mutates_release_feature_documents() -> None:
    text = workflow()
    assert 'db.collection("releaseFeatures")' in text
    for forbidden in (
        'db.collection("asterStrategy2")',
        'db.collection("asterAutomation")',
        'db.collection("asterPositionLossAutoHedge")',
        'db.collection("orders")',
        'db.collection("users")',
        "AsterV3Client",
        "submit_order",
        "place_order",
    ):
        assert forbidden not in text
