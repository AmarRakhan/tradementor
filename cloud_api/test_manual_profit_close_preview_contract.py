from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / "cloud_api/main.py").read_text()
WEB = (ROOT / "web/components/aster-recent-trades.tsx").read_text()
ROUTE = (ROOT / "web/app/api/exchanges/aster/positions/manual-profit-close-plan/route.ts").read_text()

def test_preview_never_sends_order():
    source = MAIN.split('@app.get("/v1/me/aster/positions/manual-profit-close-plan")', 1)[1].split('@app.post("/v1/me/aster/positions/close-profitable")', 1)[0]
    assert "position_risk()" in source
    assert "public_exchange_info()" in source
    assert "make_profit_close_snapshot" in source
    assert '"executionEnabled": False' in source
    assert "execute_aster_leg" not in source
    assert "live=True" not in source

def test_existing_upper_buttons_unchanged_and_green_uses_new_preview():
    assert 'onClick={() => forwardSnapshotProfit("LONG")}' in WEB
    assert 'onClick={() => forwardSnapshotProfit("SHORT")}' in WEB
    assert 'onClick={() => forwardSnapshotProfit("ALL")}' in WEB
    assert 'manual-profit-close-plan?percentage=${profitClosePercentage}' in WEB
    assert 'manual-profit-close-plan?percentage=${raw}' in ROUTE
    assert "link.download" in WEB
