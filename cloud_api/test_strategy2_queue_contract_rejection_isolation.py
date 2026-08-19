from pathlib import Path


def test_definite_contract_rejection_is_account_safe_and_not_data_hold():
    source=(Path(__file__).parent/'main.py').read_text()
    start=source.index('def _run_aster_strategy2_queue_scan')
    end=source.index('@app.post("/internal/mexc-automation/tick")',start)
    block=source[start:end]
    assert 'except Exception as exc:' in block
    assert 'if not is_definite_contract_rejection(exc):' in block
    assert '"currentIntent":{},"haltedUncertain":False' in block
    assert '"event":"QUEUE_CONTRACT_REJECTION_ISOLATED"' in block
    assert '"phase":"WAITING"' in block
    assert 'results.append({"status":"contract-skipped"' in block
