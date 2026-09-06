from pathlib import Path

path = Path('cloud_api/main.py')
text = path.read_text(encoding='utf-8')
old = '''    uid=str(user["uid"]); ref=aster_strategy2_reference(uid); existing=ref.get().to_dict() or {}; old=existing.get("settings") if isinstance(existing.get("settings"),dict) else {}
    try: candidate=MultiBbConfig.from_mapping(request.settings)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
'''
new = '''    uid=str(user["uid"]); ref=aster_strategy2_reference(uid); existing=ref.get().to_dict() or {}; old=existing.get("settings") if isinstance(existing.get("settings"),dict) else {}
    # Settings updates are patch-like for established Multi BB accounts. Legacy/main
    # forms may still submit only shared fields; never erase already-persisted
    # side-specific LONG/SHORT values just because they are absent from that request.
    merged_settings = {**old, **request.settings}
    try: candidate=MultiBbConfig.from_mapping(merged_settings)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
'''
if old not in text:
    raise SystemExit('target settings route block not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')

# Add a regression contract test next to the existing portfolio tests.
test = Path('cloud_api/test_aster_side_settings_persistence.py')
test.write_text('''from pathlib import Path\n\n\ndef test_strategy2_settings_save_merges_existing_side_specific_values():\n    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")\n    start = source.index('@app.put("/v1/me/aster/strategy2/settings")')\n    block = source[start: source.index("\\n@app.", start + 8)]\n    assert "merged_settings = {**old, **request.settings}" in block\n    assert "MultiBbConfig.from_mapping(merged_settings)" in block\n    assert "MultiBbConfig.from_mapping(request.settings)" not in block\n\n\ndef test_short_dca_is_explicitly_public_and_not_legacy_alias_only():\n    source = Path(__file__).with_name("aster_multi_bb.py").read_text(encoding="utf-8")\n    assert '"shortDcaDistance":self.short_dca_distance' in source\n    assert '_positive_ratio(source,("shortDcaDistance",),base.dca_distance)' in source\n''', encoding='utf-8')
