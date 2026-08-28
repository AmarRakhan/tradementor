from pathlib import Path


def test_focus_trade_detail_dca_uses_persisted_runtime_trigger():
    source=Path("main.py").read_text()
    assert "strategy2_focus_slot_by_key" in source
    assert 'focus_slot.get("nextDcaTrigger")' in source
    assert '"source":"focus-runtime-state"' in source
    assert '"levels":[{"number":filled+1,"price":next_focus_dca}]' in source
