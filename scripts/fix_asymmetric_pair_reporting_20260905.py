from pathlib import Path

p = Path('cloud_api/aster_multi_bb.py')
s = p.read_text()

old = '''    active_pair_count = sum(1 for key, row in state.items() if key.endswith("|LONG") and row.get("asymmetricHedge") and key in active and (row.get("pairedShortPending") or str(row.get("pairedShortKey") or "") in active))
    if settings.asymmetric_hedge_enabled:
'''
new = '''    active_pair_count = sum(1 for key, row in state.items() if key.endswith("|LONG") and row.get("asymmetricHedge") and key in active and (row.get("pairedShortPending") or str(row.get("pairedShortKey") or "") in active))
    legacy_position_count = max(0, len(strategy_active_keys) - active_pair_count * 2) if settings.asymmetric_hedge_enabled else 0
    if settings.asymmetric_hedge_enabled:
'''
assert old in s, 'active pair block not found'
s = s.replace(old, new, 1)

old = '''              "legacyPositionsDuringAsymmetric": max(0, len(strategy_active_keys) - active_pair_count * 2) if settings.asymmetric_hedge_enabled else 0,
'''
new = '''              "legacyPositionsDuringAsymmetric": legacy_position_count,
'''
assert old in s, 'legacy report field not found'
s = s.replace(old, new, 1)

p.write_text(s)
