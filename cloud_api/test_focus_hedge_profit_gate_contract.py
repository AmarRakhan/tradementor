from pathlib import Path


def test_multi_focus_hedge_close_is_net_profit_gated():
    src=Path("cloud_api/aster_strategy2_focus_multi.py").read_text()
    assert "FOCUS_HEDGE_CLOSE_BLOCKED" in src
    assert "hedge_evidence.expected_net<=0" in src
    assert "FOCUS_HEDGE_CLOSE_SAFETY_OVERRIDE" in src
    assert "oversized hedge even when that hedge leg itself is negative" not in src


def test_single_focus_parked_short_close_is_net_profit_gated():
    src=Path("cloud_api/aster_strategy2_focus_live.py").read_text()
    assert "FOCUS_HEDGE_CLOSE_BLOCKED" in src
    assert "evidence.expected_net<=0" in src
    assert "bewezen hedge ownership ontbreekt" in src
    assert "str(x.get(\"positionSide\",\"\")).upper()==leg.side" in src
