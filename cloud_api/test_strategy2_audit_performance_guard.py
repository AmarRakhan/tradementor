from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cloud_api" / "main.py").read_text(encoding="utf-8")


def _tick_block() -> str:
    start = SOURCE.index("def _run_aster_strategy2_tick")
    end = SOURCE.index("def _aster_brackets", start)
    return SOURCE[start:end]


def test_audit_recovery_is_scoped_to_missing_active_symbols():
    block = _tick_block()
    missing = 'missing_symbols={symbol for symbol,side in active_keys if (symbol,side) not in known_keys}'
    query = 'ref.collection("audit").where("symbol","==",recovery_symbol)'
    assert missing in block
    assert query in block
    assert 'ref.collection("audit").stream()' not in block
    assert block.index(missing) < block.index(query)


def test_recovery_still_receives_the_same_audit_evidence_when_needed():
    block = _tick_block()
    assert "audited_symbols=" in block
    assert "recovery_symbols=changed_symbols|(audited_symbols&missing_symbols)" in block
    assert "audit_events=audit_events,fills=fills" in block


def test_normal_tick_does_not_fabricate_recovery_evidence():
    block = _tick_block()
    assert 'audit_events=[]' in block
    assert 'for recovery_symbol in sorted(missing_symbols)' in block
    assert 'audit_events.extend(x.to_dict() or {} for x in rows)' in block


def test_known_firestore_stream_transport_bug_gets_one_read_only_retry():
    block = _tick_block()
    assert 'except AttributeError as exc:' in block
    assert '"_UnaryStreamMultiCallable" not in str(exc)' in block
    assert '"_retry" not in str(exc)' in block
    assert block.count('rows=list(query.stream())') == 2
