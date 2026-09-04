import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const component = fs.readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const styles = fs.readFileSync(new URL("../components/aster-trade-center.module.css", import.meta.url), "utf8");

test("Tradecentrum derives Covered and Covering only from confirmed asymmetric runtime pairing", () => {
  assert.match(component, /function asymmetricPairStatus/);
  assert.match(component, /runtime\.asymmetricHedge !== true/);
  assert.match(component, /runtime\.botManaged !== true/);
  assert.match(component, /runtime\.pairedShortPending === true/);
  assert.match(component, /runtime\.pairedShortOpened !== true/);
  assert.match(component, /shortRuntime\.pairedLongKey/);
  assert.match(component, /longRuntime\.pairedShortKey/);
  assert.match(component, /cycleId/);
  assert.match(component, /activeKeys\.has\(pairedShortKey\)/);
  assert.match(component, /activeKeys\.has\(pairedLongKey\)/);
});

test("status is rendered only inside the pair cell between symbol and side", () => {
  const pairStart = component.indexOf('<button className={styles.pair}');
  const sideStart = component.indexOf('<strong role="cell" className={`${styles.side}', pairStart);
  const local = component.slice(pairStart, sideStart);
  assert.match(local, /pairLinkStatus/);
  assert.match(local, />Covered</);
  assert.match(local, />Covering</);
  assert.doesNotMatch(component.slice(sideStart, sideStart + 1000), /pairLinkStatus/);
});

test("Covered is LONG green, Covering is blue, and labels stay compact without pills", () => {
  assert.match(styles, /\.pairLinkStatus\{display:inline-flex;align-items:center;gap:4px;flex:0 0 auto;font-size:8px;font-weight:850;white-space:nowrap\}/);
  assert.match(styles, /\.pairLinkStatus i\{width:5px;height:5px;border-radius:50%;background:currentColor/);
  assert.match(styles, /\.covered\{color:#58f0ae\}/);
  assert.match(styles, /\.covering\{color:#48a7ff\}/);
  assert.doesNotMatch(styles, /\.pairLinkStatus\{[^}]*background:/);
  assert.doesNotMatch(styles, /\.pairLinkStatus\{[^}]*border:/);
});

test("mobile layout and Close button contract remain untouched", () => {
  assert.match(styles, /grid-template-columns:minmax\(64px,1fr\) 38px 30px 45px 45px 40px 19px 57px/);
  assert.match(styles, /\.close\{width:100%;min-width:0/);
  assert.match(styles, /\.pairLinkStatus\{gap:2px;font-size:6px\}/);
});
