from pathlib import Path


def test_readiness_history_probe_is_bounded_for_large_accounts():
    source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    start = source.index("def aster_strategy3_readiness(")
    end = source.index('@app.post("/v1/me/aster/strategy3/canary")', start)
    readiness = source[start:end]
    assert "for symbol in active_symbols" not in readiness
    assert "client.all_orders(probe_symbol,limit=1)" in readiness
    assert "client.user_trades(probe_symbol,limit=5)" in readiness
    assert "client.income_history(limit=50)" in readiness
    assert '"mode":"bounded-single-symbol"' in readiness
