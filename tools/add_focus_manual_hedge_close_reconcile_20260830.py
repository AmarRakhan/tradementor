from pathlib import Path

engine_path = Path('cloud_api/aster_strategy2_focus_trailing.py')
text = engine_path.read_text(encoding='utf-8')

insert_before = '''    # v7 equity protection may repair missing protection below the cycle baseline, but\n'''
block = '''    # Manual Aster hedge-close reconciliation: exchange truth wins. If the hedge\n    # was present in Focus ownership/state but Aster now confirms it flat, treat\n    # that as an intentional manual hedge release. Keep the LONG cycle alive and\n    # arm the exact same last-DCA re-hedge anchor used after a bot-managed release.\n    # Start/DCA sync states are intentionally excluded so a missing required hedge\n    # is never misclassified as a manual close.\n    manual_hedge_closed = bool(\n        simple_flow and state.get("cycleId") and primary_qty > 1e-12 and hedge_qty <= 1e-12 and\n        _finite(state.get("lastDcaFillPrice")) > 0 and not bool(state.get("reHedgeArmed")) and\n        str(state.get("hedgeState", "")) == HEDGE_ACTIVE and\n        str(state.get("cycleStatus", "")) not in {\n            "START_HEDGE_SYNC_PENDING", "DCA_HEDGE_SYNC_PENDING",\n            "EMERGENCY_EQUITY_LOCK_WAIT_BUDGET", "PORTFOLIO_EXIT_EXECUTING",\n        } and\n        _leg(owned, hedge_role) is not None\n    )\n    if manual_hedge_closed:\n        last_dca_manual = _finite(state.get("lastDcaFillPrice"))\n        stale_owned_hedge = _leg(owned, hedge_role)\n        if stale_owned_hedge is not None:\n            owned = _reduce_owned(owned, hedge_role, stale_owned_hedge.quantity, timestamp_ms)\n        state.update({\n            "dcaMode": DCA_TRAILING, "hedgeState": HEDGE_OFF, "hedgeTargetQty": 0.0,\n            "hedgeCycleId": "", "hedgeReleasePrice": 0.0,\n            "shortReleasePriceReady": False, "shortReleaseNetGreenReady": False,\n            "expectedNetShortClosePnl": 0.0, "shortNetGreenReleasePrice": 0.0,\n            "reHedgeArmed": True, "reHedgePrice": last_dca_manual,\n            "cycleStatus": "LONG_ONLY", "lastAction": "MANUAL_HEDGE_CLOSE_RECONCILED",\n            "lastReason": "Aster bevestigt handmatig gesloten SHORT; LONG-cycle blijft actief en re-hedge is gewapend op laatste DCA-fill",\n        })\n        _persist(ref, state, owned)\n        _audit(ref, "FOCUS_MANUAL_HEDGE_CLOSE_RECONCILED", cycleId=state.get("cycleId"), symbol=symbol,\n            lastDcaFill=last_dca_manual, reHedgePrice=last_dca_manual)\n\n'''
if 'FOCUS_MANUAL_HEDGE_CLOSE_RECONCILED' not in text:
    if insert_before not in text:
        raise SystemExit('manual-close insertion point not found')
    text = text.replace(insert_before, block + insert_before, 1)

old_lock = '''    equity_lock_active = bool(\n        simple_flow and cycle_start_equity > 0 and current_equity > 0 and\n        current_equity + 1e-9 < cycle_start_equity\n    )\n'''
new_lock = '''    equity_lock_active = bool(\n        simple_flow and cycle_start_equity > 0 and current_equity > 0 and\n        current_equity + 1e-9 < cycle_start_equity and\n        not bool(state.get("reHedgeArmed"))\n    )\n'''
if old_lock in text:
    text = text.replace(old_lock, new_lock, 1)
elif 'not bool(state.get("reHedgeArmed"))' not in text:
    raise SystemExit('equity-lock guard point not found')

engine_path.write_text(text, encoding='utf-8')

test_path = Path('cloud_api/test_focus_manual_hedge_close_reconcile.py')
test_path.write_text('''from pathlib import Path\n\n\ndef test_manual_hedge_close_reconciles_to_same_rehedge_anchor_without_strategy_changes():\n    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")\n    assert "manual_hedge_closed = bool(" in src\n    assert "FOCUS_MANUAL_HEDGE_CLOSE_RECONCILED" in src\n    assert '\"reHedgeArmed\": True, \"reHedgePrice\": last_dca_manual' in src\n    assert '\"cycleStatus\": \"LONG_ONLY\"' in src\n    assert 'not bool(state.get("reHedgeArmed"))' in src\n    assert 'focus_v2_hedge_release_recovery_pct' in src\n    assert 'FOCUS_PORTFOLIO_TARGET_CLOSED' in src\n    assert 'next_dca_from_anchor' in src\n''', encoding='utf-8')

marker_path = Path('.deploy/focus-portfolio-v7-20260830')
marker = marker_path.read_text(encoding='utf-8')
line = '\nManual hedge-close reconciliation: if Aster confirms the Focus hedge was manually flattened while LONG remains open, reconcile stale ownership, keep the cycle alive, arm re-hedge at the last confirmed DCA, and do not let emergency equity repair override an intentionally armed re-hedge. No DCA distance, release distance, fee model, or portfolio target changes.\n'
if line.strip() not in marker:
    marker += line
marker_path.write_text(marker, encoding='utf-8')

print('Applied manual hedge-close reconciliation without changing Strategy-2 distances or targets.')
