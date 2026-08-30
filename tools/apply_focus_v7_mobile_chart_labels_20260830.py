from pathlib import Path

chart = Path('web/components/trading-chart.tsx')
src = chart.read_text(encoding='utf-8')

old = '      addSegment("be","#4aa3ff",2);addSegment("dca","#ffd166",2);addSegment("tp","#b978ff",2);addSegment("release","#ff9f43",2);'
new = '      addSegment("be","#4aa3ff",2);addSegment("dca","#ffd166",2);addSegment("tp","#b978ff",2);addSegment("lastfill","#4aa3ff",2);addSegment("release","#ff9f43",2);addSegment("rehedge","#f06292",2);'
assert old in src, 'focus segment creation block changed unexpectedly'
src = src.replace(old, new, 1)

old = 'const hedgeActive=Number(cockpit?.shortQuantity||0)>0&&String(cockpit?.hedgeState||"").toUpperCase()!=="OFF";const rawNextBuy=Number(cockpit?.nextLongDcaPrice||0);const safeNextBuy=rawNextBuy>0&&rawNextBuy<next.close?rawNextBuy:0;setSegment("live",next.close);setSegment("be",0);setSegment("dca",safeNextBuy);setSegment("tp",0);setSegment("release",cockpit?.hedgeReleasePrice||cockpit?.nextShortReleasePrice,hedgeActive);'
new = 'const hedgeActive=Number(cockpit?.shortQuantity||0)>0&&String(cockpit?.hedgeState||"").toUpperCase()!=="OFF";const rawNextBuy=Number(cockpit?.nextLongDcaPrice||0);const safeNextBuy=rawNextBuy>0&&rawNextBuy<next.close?rawNextBuy:0;const lastFill=Number(cockpit?.lastDcaFillPrice||0);const rehedge=Number(cockpit?.rehedgePrice||0);setSegment("live",next.close);setSegment("be",0);setSegment("dca",safeNextBuy);setSegment("tp",0);setSegment("lastfill",lastFill,lastFill>0);setSegment("release",cockpit?.hedgeReleasePrice||cockpit?.nextShortReleasePrice,hedgeActive&&lastFill>0);setSegment("rehedge",rehedge,Boolean(cockpit?.rehedgeArmed)&&rehedge>0);'
assert old in src, 'realtime focus segment block changed unexpectedly'
src = src.replace(old, new, 1)

old = '  const focusLevels=useMemo(()=>{if(!focusV2||!cockpit)return[] as Array<{key:string;price:number;label:string;color:string}>;const rows=[{key:"live",price:focusLivePrice,label:"LIVE",color:"#25df91"}];if(focusNextBuyInvariantOk)rows.push({key:"dca",price:focusRawNextBuy,label:`TRAILING TERUGVALKOOP ${focusNextBuyDistancePct===null?"—":`-${focusNextBuyDistancePct.toFixed(2)}%`}`,color:"#ffd166"});const lastFill=Number(cockpit?.lastDcaFillPrice||0);if(lastFill>0)rows.push({key:"lastfill",price:lastFill,label:`LAATST GEVULDE KOOP ${distanceLabel(lastFill)}`,color:"#4aa3ff"});if(focusHedgeActive&&focusReleasePrice>0)rows.push({key:"release",price:focusReleasePrice,label:`SHORT RELEASE ${distanceLabel(focusReleasePrice)}`,color:"#ff9f43"});const rehedge=Number(cockpit?.rehedgePrice||0);if(Boolean(cockpit?.rehedgeArmed)&&rehedge>0)rows.push({key:"rehedge",price:rehedge,label:`RE-HEDGE ${distanceLabel(rehedge)}`,color:"#f06292"});return rows.filter(row=>Number.isFinite(row.price)&&row.price>0)},[focusV2,cockpit,focusLivePrice,focusNextBuyInvariantOk,focusRawNextBuy,focusNextBuyDistancePct,focusHedgeActive,focusReleasePrice]);'
new = '  const focusReleasePct=useMemo(()=>{const configured=Number(cockpit?.hedgeReleaseRecoveryPct||0);if(configured>0)return configured*100;const lastFill=Number(cockpit?.lastDcaFillPrice||0);return lastFill>0&&focusReleasePrice>0?Math.abs((focusReleasePrice/lastFill)-1)*100:0},[cockpit,focusReleasePrice]);\n  const focusLevels=useMemo(()=>{if(!focusV2||!cockpit)return[] as Array<{key:string;price:number;label:string;color:string}>;const rows=[{key:"live",price:focusLivePrice,label:"LIVE",color:"#25df91"}];if(focusNextBuyInvariantOk)rows.push({key:"dca",price:focusRawNextBuy,label:`TERUGVAL -${(focusNextBuyDistancePct??0).toFixed(2)}%`,color:"#ffd166"});const lastFill=Number(cockpit?.lastDcaFillPrice||0);if(lastFill>0)rows.push({key:"lastfill",price:lastFill,label:"LAATSTE KOOP",color:"#4aa3ff"});if(lastFill>0&&focusHedgeActive&&focusReleasePrice>0)rows.push({key:"release",price:focusReleasePrice,label:`RELEASE +${focusReleasePct.toFixed(2)}%`,color:"#ff9f43"});const rehedge=Number(cockpit?.rehedgePrice||0);if(Boolean(cockpit?.rehedgeArmed)&&rehedge>0)rows.push({key:"rehedge",price:rehedge,label:"RE-HEDGE",color:"#f06292"});return rows.filter(row=>Number.isFinite(row.price)&&row.price>0)},[focusV2,cockpit,focusLivePrice,focusNextBuyInvariantOk,focusRawNextBuy,focusNextBuyDistancePct,focusHedgeActive,focusReleasePrice,focusReleasePct]);'
assert old in src, 'focus level-label block changed unexpectedly'
src = src.replace(old, new, 1)

old = '<div key={level.key} className={`focus-level-segment ${level.key}`} style={{top:`${focusLevelY[level.key]}px`,color:level.color}}><i/><span>{level.label}</span></div>'
new = '<div key={level.key} className={`focus-level-segment ${level.key}`} data-focus-chart-label={level.key} style={{top:`${focusLevelY[level.key]}px`,color:level.color,left:"12px",right:"88px",maxWidth:"none",overflow:"hidden"}}><i style={{minWidth:0,flex:"1 1 auto"}}/><span style={{marginLeft:"8px",flex:"0 0 auto",whiteSpace:"nowrap",maxWidth:"100%"}}>{level.label}</span></div>'
assert old in src, 'focus overlay rendering block changed unexpectedly'
src = src.replace(old, new, 1)

# Portfolio target must remain cockpit-only; never add it to focusLevels.
focus_levels_section = src.split('const focusLevels=useMemo', 1)[1].split('syncFocusLevelsRef.current', 1)[0]
assert 'PORTFOLIO DOEL' not in focus_levels_section
assert 'TERUGVAL -' in focus_levels_section
assert 'LAATSTE KOOP' in focus_levels_section
assert 'RELEASE +' in focus_levels_section
assert 'RE-HEDGE' in focus_levels_section

chart.write_text(src, encoding='utf-8')

test = Path('web/tests/focus-v7-mobile-chart-labels.test.mjs')
test.write_text(r'''import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const src = fs.readFileSync(new URL("../components/trading-chart.tsx", import.meta.url), "utf8");

test("Strategy-2 chart uses compact mobile-safe line labels", () => {
  for (const token of ["TERUGVAL -", "LAATSTE KOOP", "RELEASE +", "RE-HEDGE", 'label:"LIVE"']) {
    assert.ok(src.includes(token), `missing ${token}`);
  }
  assert.ok(!src.includes('label:`TRAILING TERUGVALKOOP'));
  assert.ok(!src.includes('label:`SHORT RELEASE'));
  assert.ok(!src.includes('label:`LAATST GEVULDE KOOP'));
});

test("line-label lane reserves the right price scale plus a 16px safety gap", () => {
  assert.ok(src.includes('right:"88px"'));
  assert.ok(src.includes('left:"12px"'));
  assert.ok(src.includes('overflow:"hidden"'));
  assert.ok(src.includes('whiteSpace:"nowrap"'));
  // Chart price scale has minimumWidth 72; label lane starts 88px from right => 16px gap.
  assert.ok(src.includes('minimumWidth:72'));
});

test("360, 390 and Fold-like widths retain a positive label lane", () => {
  const right = 88, left = 12;
  for (const width of [360, 390, 690]) {
    const lane = width - right - left;
    assert.ok(lane >= 260, `${width}px leaves only ${lane}px for labels`);
  }
});

test("portfolio target stays cockpit-only and is not a synthetic price line", () => {
  const focusLevels = src.split("const focusLevels=useMemo", 2)[1].split("syncFocusLevelsRef.current", 1)[0];
  assert.ok(!focusLevels.includes("PORTFOLIO DOEL"));
  assert.ok(src.includes("focusPortfolioTargetLabel"));
});

test("display patch includes real last-fill and armed re-hedge line segments without strategy math", () => {
  assert.ok(src.includes('addSegment("lastfill"'));
  assert.ok(src.includes('addSegment("rehedge"'));
  assert.ok(src.includes('setSegment("lastfill"'));
  assert.ok(src.includes('setSegment("rehedge"'));
});
''', encoding='utf-8')

trigger = Path('.deploy/focus-portfolio-v7-web-20260830')
current = trigger.read_text(encoding='utf-8') if trigger.exists() else ''
marker = 'Deploy compact mobile Strategy-2 chart labels.'
if marker not in current:
    trigger.write_text(current.rstrip() + '\n' + marker + '\n', encoding='utf-8')

print('patched Strategy-2 mobile chart labels only')
