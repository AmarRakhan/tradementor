from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_aster_secrets.sh"


def test_aster_secret_migration_is_pinned_and_never_prints_payloads():
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'SOURCE_PROJECT="tradementor-production"' in source
    assert 'TARGET_PROJECT="tradementor-amar-20260813"' in source
    assert 'PREFIX="tradementor-aster-"' in source
    assert '"${1:-}" != "--apply"' in source
    assert 'secrets versions access latest' in source
    assert '--data-file=-' in source
    assert 'mktemp' not in source
    assert 'echo "${payload}' not in source


def test_existing_destination_secret_versions_are_never_overwritten():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "secrets versions list" in source
    assert "Overslaan (bestaat al)" in source
    assert source.index("Overslaan (bestaat al)") < source.index("secrets versions access latest")
