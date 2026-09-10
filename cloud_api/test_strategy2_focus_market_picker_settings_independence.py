from pathlib import Path


def test_focus_market_picker_does_not_parse_strategy_settings():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    start = source.index('def strategy2_focus_markets(')
    end = source.index('\n@app.get("/v1/me/aster/strategy2/leverage-tiers")', start)
    handler = source[start:end]

    assert "Strategy2Config.from_mapping" not in handler
    assert "aster_strategy2_reference" not in handler
    assert "public_exchange_info()" in handler
    assert '"ranking":rows' in handler
