from pathlib import Path

# Backend: patch-like settings save, preserving side-specific values omitted by legacy forms.
main = Path('cloud_api/main.py')
text = main.read_text(encoding='utf-8')
old = '''    uid=str(user["uid"]); ref=aster_strategy2_reference(uid); existing=ref.get().to_dict() or {}; old=existing.get("settings") if isinstance(existing.get("settings"),dict) else {}
    try: candidate=MultiBbConfig.from_mapping(request.settings)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
'''
new = '''    uid=str(user["uid"]); ref=aster_strategy2_reference(uid); existing=ref.get().to_dict() or {}; old=existing.get("settings") if isinstance(existing.get("settings"),dict) else {}
    # Established Multi BB settings updates are patch-like. Older/main forms still
    # submit shared fields only; absent LONG/SHORT fields must retain their stored values.
    merged_settings = {**old, **request.settings}
    try: candidate=MultiBbConfig.from_mapping(merged_settings)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
'''
if old not in text:
    raise SystemExit('backend settings block not found')
main.write_text(text.replace(old, new, 1), encoding='utf-8')

# Frontend: every normal save/start carries forward persisted side-specific settings.
maker = Path('web/components/aster-strategy2-maker.tsx')
text = maker.read_text(encoding='utf-8')
old = '''  const settings = useMemo(() => {
    const pairSlots = clampInt(n(v.pairSlots), 1, 25);
    const longSlots = v.asymmetricHedgeEnabled ? pairSlots : clampInt(n(v.longSlots), 0, 25);
    const shortSlots = v.asymmetricHedgeEnabled ? pairSlots : clampInt(n(v.shortSlots), 0, 25);
    return {
      engine: "multi_bb_v1", strategyKind: "multi_bb_v1", name: v.name, mode: v.mode,
'''
new = '''  const settings = useMemo(() => {
    const pairSlots = clampInt(n(v.pairSlots), 1, 25);
    const longSlots = v.asymmetricHedgeEnabled ? pairSlots : clampInt(n(v.longSlots), 0, 25);
    const shortSlots = v.asymmetricHedgeEnabled ? pairSlots : clampInt(n(v.shortSlots), 0, 25);
    const persisted = state.settings && typeof state.settings === "object" ? state.settings as Record<string, unknown> : {};
    return {
      ...persisted,
      engine: "multi_bb_v1", strategyKind: "multi_bb_v1", name: v.name, mode: v.mode,
'''
if old not in text:
    raise SystemExit('frontend settings block not found')
maker.write_text(text.replace(old, new, 1), encoding='utf-8')

# Regression contracts.
Path('cloud_api/test_aster_side_settings_persistence.py').write_text('''from pathlib import Path\n\n\ndef test_settings_route_merges_old_side_specific_values():\n    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")\n    start = source.index('@app.put("/v1/me/aster/strategy2/settings")')\n    block = source[start: source.index("\\n@app.", start + 8)]\n    assert "merged_settings = {**old, **request.settings}" in block\n    assert "MultiBbConfig.from_mapping(merged_settings)" in block\n\ndef test_short_distance_is_separate_public_config():\n    source = Path(__file__).with_name("aster_multi_bb.py").read_text(encoding="utf-8")\n    assert '\"shortDcaDistance\":self.short_dca_distance' in source\n''', encoding='utf-8')
Path('web/tests/aster-strategy2-side-persistence.test.mjs').write_text('''import assert from "node:assert/strict";\nimport { readFileSync } from "node:fs";\nconst source = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");\nassert.match(source, /const persisted = state\\.settings/);\nassert.match(source, /return \\{\\s*\\.\\.\\.persisted,/);\nconsole.log("Strategy 2 side persistence contract OK");\n''', encoding='utf-8')
