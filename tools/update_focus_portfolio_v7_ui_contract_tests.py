from pathlib import Path

A = Path('cloud_api/test_aster_strategy2_focus_v2.py')
B = Path('cloud_api/test_focus_v2_simple_recovery.py')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f'{label}: expected one match, got {text.count(old)}')
    return text.replace(old, new, 1)


a = A.read_text(encoding='utf-8')
a = replace_once(a, '''def test_wizard_has_simplified_focus_v2_opt_in():
    ui=(HERE.parent/"web/components/aster-strategy2-maker.tsx").read_text()
    assert 'title:"1 · Pair & leverage"' in ui
    assert 'label="Focus 2.0 gebruiken"' in ui
    assert "Focus 2.0 · beschermde cycle" in ui
''', '''def test_wizard_has_simplified_focus_v2_opt_in():
    ui=(HERE.parent/"web/components/aster-strategy2-maker.tsx").read_text()
    assert 'title:"1 · Pair & leverage"' in ui
    assert 'label="Focus 2.0 gebruiken"' in ui
    assert "Strategy-2 · portfolio-cyclus" in ui
''', 'wizard opt-in summary')

a = replace_once(a, '''def test_simple_wizard_exposes_configurable_full_tp_and_start_hedge_controls():
    ui=(HERE.parent/"web/components/aster-strategy2-maker.tsx").read_text()
    block=ui[ui.index(" const focusSteps=["):ui.index(" const steps=",ui.index(" const focusSteps=["))]
    assert 'label="Starthedge (%)"' in block
    assert 'label="Take Profit modus"' in block
    assert 'label={v.focusTpMode==="percent"?"Take Profit (%)":"Take Profit ($ / USDT)"}' in block
    assert 'label="Na Take Profit direct opnieuw starten"' in block
    assert "focusV2TakeProfitValue" in ui and "focusV2StartHedgeRatio" in ui
''', '''def test_simple_wizard_exposes_fixed_1to1_hedge_and_portfolio_target_controls():
    ui=(HERE.parent/"web/components/aster-strategy2-maker.tsx").read_text()
    block=ui[ui.index(" const focusSteps=["):ui.index(" const steps=",ui.index(" const focusSteps=["))]
    assert 'title:"2 · Start LONG + SHORT 1:1"' in block
    assert 'label="Startinzet / margin per zijde (USDT)"' in block
    assert 'label="Starthedge (%)"' not in block
    assert 'label="Hedge target (% van totale LONG)"' not in block
    assert 'title:"5 · Alles sluiten bij portfoliogroei"' in block
    assert 'label="Portfolio-doel modus"' in block
    assert 'label={v.focusTpMode==="percent"?"Alles sluiten bij groei (%)":"Alles sluiten bij groei ($ / USDT)"}' in block
    assert 'label="Na volledige cyclus direct opnieuw starten"' in block
    assert 'focusV2StartHedge:"100"' in block and 'focusV2MaxHedge:"100"' in block
''', 'wizard target controls')
A.write_text(a, encoding='utf-8')

b = B.read_text(encoding='utf-8')
b = replace_once(b, '''def test_33_step4_core_fields_match_trailing_hedge_release_contract():
    assert 'label="Hedge target (% van totale LONG)"' in MAKER
    assert 'label="SHORT volledig los na herstel (%)"' in MAKER
    assert 'label="Re-hedge terugval (%)"' not in MAKER
''', '''def test_33_step4_core_fields_match_trailing_hedge_release_contract():
    assert 'title:"4 · 100% hedge → release → re-hedge"' in MAKER
    assert 'label="Hedge target (% van totale LONG)"' not in MAKER
    assert 'label="SHORT volledig los na herstel (%)"' in MAKER
    assert 'Geen PnL- of break-even-gate' in MAKER
''', 'step4 contract')

b = replace_once(b, '''def test_34_wizard_exposes_start_hedge_and_margin_semantics():
    assert 'label="Starthedge (%)"' in MAKER
    assert 'Start LONG inzet / margin (USDT)' in MAKER
    assert 'focusV2AmountsAreMargin:v.focusV2Enabled' in MAKER
''', '''def test_34_wizard_exposes_fixed_start_hedge_and_margin_semantics():
    assert 'title:"2 · Start LONG + SHORT 1:1"' in MAKER
    assert 'label="Starthedge (%)"' not in MAKER
    assert 'Startinzet / margin per zijde (USDT)' in MAKER
    assert 'focusV2StartHedge:"100"' in MAKER
    assert 'focusV2AmountsAreMargin:v.focusV2Enabled' in MAKER
''', 'step2 fixed hedge')

b = replace_once(b, '''def test_35_step5_is_full_take_profit_with_auto_restart():
    assert 'title:"5 · Full Take Profit & auto-herstart"' in MAKER
    assert 'label="Take Profit modus"' in MAKER
    assert 'label="Na Take Profit direct opnieuw starten"' in MAKER
''', '''def test_35_step5_is_portfolio_growth_target_with_auto_restart():
    assert 'title:"5 · Alles sluiten bij portfoliogroei"' in MAKER
    assert 'label="Portfolio-doel modus"' in MAKER
    assert 'Alles sluiten bij groei ($ / USDT)' in MAKER
    assert 'label="Na volledige cyclus direct opnieuw starten"' in MAKER
''', 'step5 portfolio target')

b = replace_once(b, '''def test_36_simple_summary_describes_full_close_cycle():
    assert "full close" in MAKER and "auto-herstart" in MAKER
''', '''def test_36_simple_summary_describes_portfolio_close_cycle():
    assert "Strategy-2 · portfolio-cyclus" in MAKER
    assert "Portfolio-doel:" in MAKER and "auto-herstart" in MAKER
''', 'summary portfolio cycle')
B.write_text(b, encoding='utf-8')
print('Focus portfolio-cycle v7 UI contract tests updated')
