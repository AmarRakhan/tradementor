import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const bridge = await readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/profit-pot-snapshot.css", import.meta.url), "utf8");
const layout = await readFile(new URL("../app/layout.tsx", import.meta.url), "utf8");
const snapshot = await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");

test("existing Profit Pot value is surfaced in HOME Portfolio Snapshot without a second API flow", () => {
  assert.match(bridge, /\.metric-strip \.metric/);
  assert.match(bridge, /PROFIT POT \/ SPOT/);
  assert.match(bridge, /:scope > \.aps-grid/);
  assert.match(bridge, /insertAdjacentElement\("afterend", mount\)/);
  assert.doesNotMatch(bridge, /authenticatedRequest|fetch\(|POST|PUT|DELETE|withdraw|transfer/i);
});

test("Profit Pot tile is read-only and uses the approved pixel reference", () => {
  assert.match(bridge, /file_00000000f5ec8210bf3f2c300b972c25/);
  assert.match(css, /file_00000000f5ec8210bf3f2c300b972c25/);
  assert.match(css, /border:1px solid rgba\(72,180,255,\.98\)/);
  assert.match(css, /pointer-events:none/);
  assert.doesNotMatch(bridge, /onClick=/);
});

test("bridge is mounted separately and existing Portfolio Snapshot controls stay untouched", () => {
  assert.match(layout, /AsterProfitPotSnapshotBridge/);
  assert.match(layout, /profit-pot-snapshot\.css/);
  assert.match(snapshot, /PORTFOLIOWAARDE/);
  assert.match(snapshot, /AVAILABLE TO TRADE/);
  assert.match(snapshot, /ACTIEF TRADE CAPITAL/);
  assert.match(snapshot, /ACTIEVE POSITIES/);
  assert.match(snapshot, /GESLOTEN RESULTAAT/);
  assert.match(snapshot, /TRADES GESLOTEN/);
  assert.match(snapshot, /<HedgeSummary preview=\{profitPreview\} onOpen=\{onOpenHedge\} \/>/);
  assert.match(snapshot, /Close Long/);
  assert.match(snapshot, /Close Short/);
  assert.match(snapshot, /Close All/);
});

test("Profit Pot row keeps the existing three-column mobile geometry without overflow", () => {
  assert.match(css, /grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(css, /grid-column:1/);
  assert.match(css, /min-width:0/);
  assert.match(css, /@media\(max-width:640px\)/);
  assert.match(css, /@media\(max-width:380px\)/);
});
