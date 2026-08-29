from pathlib import Path

ROOT=Path(__file__).resolve().parent
ENGINE=(ROOT/"aster_strategy2_focus_v2.py").read_text()
MAKER=(ROOT.parent/"web/components/aster-strategy2-maker.tsx").read_text()
COCKPIT=(ROOT.parent/"web/components/aster-focus-cockpit.tsx").read_text()

# The legacy Focus V2 engine remains covered for migration/backward compatibility.
def test_29_existing_stop_is_reused_without_duplicate():
    assert 'new_backup_cid=""' in ENGINE

def test_30_model2_branch_remains_separate():
    assert "elif state.recovery_model_version==RECOVERY_MODEL_FAST" in ENGINE and "recovery_remaining_ratio" in ENGINE

def test_31_model1_branch_remains_separate():
    assert "if state.recovery_model_version < RECOVERY_MODEL_FAST" in ENGINE

def test_32_wizard_has_exactly_five_focus_steps():
    block=MAKER[MAKER.index(" const focusSteps=["):MAKER.index(" const steps=",MAKER.index(" const focusSteps=["))]
    assert sum(block.count(f'title:"{n} ·') for n in range(1,6))==5

def test_33_step4_core_fields_match_trailing_hedge_release_contract():
    # v4 replaces heuristic recovery/re-hedge controls with one hard release threshold.
    assert 'label="Maximale hedge (%)"' in MAKER
    assert 'label="Hedge release-afstand (%)"' in MAKER
    assert 'label="Re-hedge terugval (%)"' not in MAKER
    assert 'label="Herstel vanaf recente low (%)"' not in MAKER

def test_34_step4_advanced_is_collapsed_by_default():
    assert 'advanced:false' in MAKER and 'label="Geavanceerde protection-instellingen"' in MAKER

def test_35_step5_is_profit_harvest_not_take_profit():
    assert 'title:"5 · Winst afromen & controle"' in MAKER and 'label="Winsttrigger (USDT)"' in MAKER and 'label="Winst afromen (USDT)"' in MAKER

def test_36_simple_summary_says_cycle_stays_active():
    assert "cycle blijft actief" in MAKER and "LONG sluiten bij netto winst" not in MAKER

def test_37_cockpit_exposes_harvest_progress_for_simple_mode():
    for token in ("Winst sinds harvest","Nog tot afromen","Laatste / totaal afgeroomd"): assert token in COCKPIT

def test_38_cockpit_has_no_simple_long_take_profit_label():
    assert 'simple?"Winsttrigger"' in COCKPIT and 'simple?"LONG Take Profit"' not in COCKPIT
