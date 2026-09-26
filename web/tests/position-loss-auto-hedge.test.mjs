import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const REFERENCE = "file_00000000ecd08246bd1b15532fb478d6";

test("Build 432+ keeps the dedicated Auto Hedge screen while simplifying the Snapshot tile", async () => {
  const [layout, row, component, css, route, applyRoute, rehedgeRoute, version] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/position-loss-auto-hedge.css", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/position-loss-auto-hedge/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/position-loss-auto-hedge/apply/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/position-loss-auto-hedge/pairs/[symbol]/rehedge/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
  ]);

  assert.match(layout, /AsterPositionLossAutoHedgeBridge/);
  assert.match(layout, /position-loss-auto-hedge\.css/);
  assert.match(row, /aster-profit-sweep-settings-host[\s\S]*aster-position-loss-auto-hedge-host[\s\S]*PortfolioCycleCard/);
  assert.ok(component.includes(REFERENCE));
  assert.ok(css.includes(REFERENCE));
  assert.match(component, /document\.body\.appendChild\(host\)/);
  assert.match(css, /#aster-position-loss-auto-hedge-back-host\{position:fixed;inset:0;z-index:950/);
  assert.match(component, /Gehedgde posities/);
  assert.match(component, /Alleen coins die \(in het verleden\) door Auto Hedge zijn gehedged/);
  assert.match(component, /Opnieuw hedgen/);
  assert.match(component, /Hedge-lock/);
  assert.match(component, /RECOVERY/);
  assert.match(component, /REHEDGE_ARMED/);
  assert.match(component, /PairLeg/);
  assert.match(component, /Netto pair resultaat/);
  assert.match(component, /Hedge ratio/);
  assert.match(component, /Elke 3 seconden/);
  assert.match(component, /open \? 3000 : 10000/);
  assert.match(component, /TESTMODUS/);
  assert.match(component, /exact 1:1 coin quantity/);
  assert.match(component, /nexora_tradecentrum_actieve_posities\.png/);
  assert.match(component, /plah-tc-auto-hedge/);
  assert.match(css, /\.plah-tc-auto-hedge/);
  assert.match(route, /position-loss-auto-hedge/);
  assert.match(route, /"GET"/);
  assert.match(route, /"PUT"/);
  assert.match(applyRoute, /position-loss-auto-hedge\/apply/);
  assert.match(applyRoute, /"POST"/);
  assert.match(rehedgeRoute, /pairs\/\$\{encodeURIComponent\(symbol\)\}\/rehedge/);
  assert.match(rehedgeRoute, /"PUT"/);
  assert.match(version, /WEBAPP_BUILD_NUMBER = "433"/);
});

test("Auto Hedge screen never reuses the HOME bull-bear/chart/Tradecentrum surface", async () => {
  const [component, css] = await Promise.all([
    readFile(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/position-loss-auto-hedge.css", import.meta.url), "utf8"),
  ]);
  assert.match(component, /SCREEN_HOST_ID/);
  assert.match(component, /document\.body\.appendChild\(host\)/);
  assert.match(css, /background:[\s\S]*linear-gradient/);
  assert.doesNotMatch(component, /aster-portfolio-snapshot.*appendChild\(host\)/);
  assert.doesNotMatch(component, /Portfolio Impact/);
  assert.doesNotMatch(component, /SHORTS DRUKKEN HARDER/);
});

test("Recovery is explicitly user-controlled instead of automatically rehedged in UI", async () => {
  const component = await readFile(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8");
  assert.match(component, /rehedgeEnabled/);
  assert.match(component, /setRehedge/);
  assert.match(component, /positie weer onder Auto Hedge-bescherming/);
  assert.match(component, /Opnieuw hedgen voor/);
});

test("Auto Hedge copy is coin-quantity based and exposes no fake live pair data", async () => {
  const component = await readFile(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8");
  assert.match(component, /exact 1:1 coin quantity/);
  assert.match(component, /pairs: \[\]/);
  assert.match(component, /Nog geen historische Auto Hedge-pairs/);
  assert.match(component, /Shadow-resultaten worden niet als echte hedge opgeslagen/);
  assert.doesNotMatch(component, /921 DOGE/);
  assert.doesNotMatch(component, /18\.271/);
});


test("Build 432 Snapshot Auto Hedge tile shows status only, not the configured dollar trigger",async()=>{
  const component=await readFile(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx",import.meta.url),"utf8");
  const tile=component.slice(component.indexOf("const tile ="),component.indexOf("const screen ="));
  assert.match(tile,/AUTO HEDGE/);
  assert.match(tile,/tileStatus/);
  assert.doesNotMatch(tile,/vanaf -/);
  assert.doesNotMatch(tile,/thresholdMoney/);
  assert.match(tile,/Auto Hedge \$\{tileStatus\}/);
});
