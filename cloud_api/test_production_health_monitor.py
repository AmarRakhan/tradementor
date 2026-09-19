from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / ".github" / "workflows" / "production-health-monitor.yml"


def test_external_monitor_is_scheduled_and_read_only():
    text = MONITOR.read_text(encoding="utf-8")
    assert 'cron: "*/15 * * * *"' in text
    assert "id-token: write" in text
    assert "google-github-actions/auth@v2" in text
    assert "gcloud beta billing projects describe" in text
    assert "gcloud run services describe" in text
    assert 'gcloud firestore databases describe --database="(default)"' in text
    assert "gcloud scheduler jobs describe" in text
    assert 'httpRequest.requestUrl:"/internal/aster-automation/tick"' in text
    assert "https://fapi.asterdex.com/fapi/v3/exchangeInfo" in text
    assert "order" not in "\n".join(
        line.lower() for line in text.splitlines()
        if "never submits exchange orders" not in line.lower()
    ) or "order" in "scheduler"
