import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Build 430 binds Auto Hedge to the approved Snapshot references and exact slot", async () => {
  const [layout, row, component, css, route, applyRoute] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/position-loss-auto-hedge.css", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/position-loss-auto-hedge/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/position-loss-auto-hedge/apply/route.ts", import.meta.url), "utf8"),
  ]);

  assert.match(layout, /AsterPositionLossAutoHedgeBridge/);
  assert.match(layout, /position-loss-auto-hedge\.css/);
  assert.match(row, /aster-profit-sweep-settings-host[\s\S]*aster-position-loss-auto-hedge-host[\s\S]*PortfolioCycleCard/);
  assert.match(component, /file_00000000340881f4b05212f7cfd82727/);
  assert.match(component, /file_00000000ee58820abf41140132367883/);
  assert.match(component, /AUTO HEDGE/);
  assert.match(component, /ACTIEF/);
  assert.match(component, /VOLLEDIG DICHTHEDGEN/);
  assert.match(component, /Pas de ingestelde verliesgrens direct toe op alle open posities/);
  assert.match(component, /onDoubleClick=\{openFromCard\}/);
  assert.match(component, /now - lastTap\.current < 340/);
  assert.match(component, /type="range"/);
  assert.match(component, /type="number"/);
  assert.match(component, /event\.stopPropagation\(\)/);
  assert.match(css, /grid-template-columns:minmax\(0,1\.75fr\) minmax\(0,1fr\) minmax\(0,1\.22fr\) minmax\(0,1\.75fr\)/);
  assert.match(css, /\.aps-portfolio-cycle-card\{grid-column:4\}/);
  assert.match(css, /transform:rotateY\(180deg\)/);
  assert.match(css, /backface-visibility:hidden/);
  assert.match(route, /position-loss-auto-hedge/);
  assert.match(route, /"GET"/);
  assert.match(route, /"PUT"/);
  assert.match(applyRoute, /position-loss-auto-hedge\/apply/);
  assert.match(applyRoute, /"POST"/);
});

test("Auto Hedge copy states coin quantity rather than USD notional matching", async () => {
  const component = await readFile(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8");
  assert.match(component, /exact 1:1 coin quantity/);
  assert.match(component, /alleen de ontbrekende tegen-quantity/);
  assert.doesNotMatch(component, /gelijke USD-notional/);
});
