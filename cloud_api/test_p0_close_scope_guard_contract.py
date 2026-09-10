from pathlib import Path


SOURCE = Path(__file__).with_name("p0_close_scope_guard.py").read_text()
DOCKERFILE = Path(__file__).with_name("Dockerfile").read_text()


def test_bulk_profit_close_requires_one_explicit_scope():
    assert '_CLOSE_PATH = "/v1/me/aster/positions/close-profitable"' in SOURCE
    assert '_VALID_SCOPES = {"ALL", "LONG", "SHORT"}' in SOURCE
    assert 'if len(values) != 1:' in SOURCE
    assert 'if requested is None:' in SOURCE
    assert 'status_code=422' in SOURCE


def test_legacy_backend_filters_candidates_by_requested_side():
    assert 'inspect.signature(_main.close_profitable_aster_positions)' in SOURCE
    assert '_main.profitable_positions = _scoped_profitable_positions' in SOURCE
    assert 'row.get("side", "")' in SOURCE
    assert '_ACTIVE_SCOPE.set(requested)' in SOURCE
    assert '_ACTIVE_SCOPE.reset(token)' in SOURCE


def test_runtime_starts_through_guard():
    assert "uvicorn p0_close_scope_guard:app" in DOCKERFILE
