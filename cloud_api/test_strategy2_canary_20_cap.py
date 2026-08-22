from pathlib import Path


ROOT = Path(__file__).parent


def test_strategy2_canary_has_its_own_twenty_dollar_cap():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "class AsterStrategy2CanaryRequest" in source
    assert "notional_usd: float = Field(default=20.0, ge=5.0, le=20.0)" in source
    assert "def run_aster_strategy2_canary(request:AsterStrategy2CanaryRequest" in source
    assert "def run_aster_strategy3_canary" not in source


def test_mobile_confirmation_sends_exactly_twenty_dollars():
    maker = (ROOT.parent / "web" / "components" / "aster-strategy2-maker.tsx").read_text(encoding="utf-8")
    assert "JSON.stringify({confirm:true,notional_usd:20})" in maker
    assert "maximaal US$ 20 · direct sluiten" in maker
