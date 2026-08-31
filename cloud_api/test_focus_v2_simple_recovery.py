from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
MAIN=(HERE/"main.py").read_text()
MAKER=(ROOT/"web/components/aster-strategy2-maker.tsx").read_text()
ENGINE=(HERE/"aster_multi_bb.py").read_text()


def test_retired_focus_wizard_is_absent():
    assert "const focusSteps" not in MAKER
    assert "Focus 2.0" not in MAKER
    assert "re-hedge" not in MAKER.lower()


def test_new_engine_is_the_only_scheduler_dispatch_before_legacy_dead_code():
    dispatch=MAIN.index("return run_multi_bb_step(")
    legacy=MAIN.index("# Realtime Simple Mode",dispatch)
    assert dispatch < legacy


def test_new_engine_has_no_hedge_or_portfolio_take_profit_logic():
    lowered=ENGINE.lower()
    assert "rehedge" not in lowered and "airbag" not in lowered
    assert "portfolio take profit" not in lowered


def test_new_engine_immediately_fills_slots_and_keeps_capped_dca():
    assert 'entryMode": "immediate_fill"' in ENGINE
    assert 'bollinger_from_klines' not in ENGINE
    assert 'client.klines(symbol, "1m"' not in ENGINE
    assert 'dca_count >= settings.max_dca' in ENGINE
    assert 'lastBotFillPrice' in ENGINE


def test_new_engine_reconciles_real_exchange_entry_and_quantity():
    assert 'row.get("entryPrice")' in ENGINE
    assert 'row.get("positionAmt")' in ENGINE
    assert 'manualOrExchangeReconciledAtMs' in ENGINE


def test_existing_positions_are_only_adopted_after_explicit_start_flag():
    assert 'raw_state.get("multiBbAdoptionPending")' in ENGINE
    assert '"multiBbAdoptionPending":True' in MAIN
