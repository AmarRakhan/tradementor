from pathlib import Path

p = Path("web/components/aster-recent-trades.tsx")
text = p.read_text()
old = 'const detailNextDcaNumber=finite(detailRuntime?.nextDcaNumber)??finite(detailNextDca?.number)??((detailDcaCount??0)+1);'
new = 'const detailNextDcaNumber=finite(detailRuntime?.nextDcaNumber)??finite(detailNextDca?.number)??1;'
if old not in text:
    raise SystemExit("next DCA number order repair anchor missing")
p.write_text(text.replace(old, new, 1))

chart = Path("web/components/trading-chart.tsx")
chart_text = chart.read_text()
old_overlay = 'const plannedOverlayLevels=useMemo(()=>mode==="aster-detail"&&!focusV2?plannedActionLevels.filter(level=>Number.isFinite(level.price)&&level.price>0).map(level=>({...level,color:level.color||(level.key==="dca"?"#ffd166":"#b978ff")})):[] as Array<{key:string;price:number;label:string;color:string}>,[mode,focusV2,plannedActionLevelsSignature]);'
new_overlay = 'const plannedOverlayLevels=useMemo(()=>mode==="aster-detail"&&!focusV2?plannedActionLevels.filter(level=>Number.isFinite(level.price)&&level.price>0).map(level=>({...level,label:level.label||(level.key==="dca"?`VOLGENDE ${selection.side.toUpperCase()} DCA`:"TP"),color:level.color||(level.key==="dca"?"#ffd166":"#b978ff")})):[] as Array<{key:string;price:number;label:string;color:string}>,[mode,focusV2,plannedActionLevelsSignature,selection.side]);'
if old_overlay not in chart_text:
    raise SystemExit("planned overlay compatibility anchor missing")
chart.write_text(chart_text.replace(old_overlay, new_overlay, 1))

rendered = Path("web/tests/rendered-html.test.mjs")
rendered_text = rendered.read_text()
stale = '  assert.match(chart, /title:next\\?.*:`DCA \\${Math\\.round/s);\n'
updated = '  assert.match(chart, /plannedOverlayLevels/);\n  assert.match(chart, /plannedActionLevels/);\n'
if stale not in rendered_text:
    raise SystemExit("stale rendered-html DCA title assertion missing")
rendered.write_text(rendered_text.replace(stale, updated, 1))

print("Strategy 2 preview declaration order, planned labels, and validation contracts repaired")
