from pathlib import Path


def test_retired_strategy3_readiness_route_is_absent():
    source=(Path(__file__).parent/"main.py").read_text(encoding="utf-8")
    assert "def aster_strategy3_readiness(" not in source
    assert '/v1/me/aster/strategy3/readiness' not in source
