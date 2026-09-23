import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const gate = fs.readFileSync(new URL("../components/aster-bot-configurator-gate.tsx", import.meta.url), "utf8");
const v2 = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const legacy = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("Botconfigurator V2 is lazy-loaded behind server release entitlement", () => {
  assert.match(gate, /authenticatedRequest\("\/api\/releases"\)/);
  assert.match(gate, /feature\?\.enabled === true/);
  assert.match(gate, /import\("@\/components\/aster-bot-configurator-v2"\)/);
  assert.match(gate, /setMode\("stable"\)/);
});

test("Stable legacy component remains present and beta wraps it", () => {
  assert.match(legacy, /LegacyAsterStrategy2Maker/);
  assert.match(legacy, /legacy={<LegacyAsterStrategy2Maker/);
});

test("V2 sends directional Bollinger and exposure-refill settings explicitly", () => {
  assert.match(v2, /directionalBollingerEnabled:draft\.directionalEnabled/);
  assert.match(v2, /bollingerLongTimeframe:draft\.longTf/);
  assert.match(v2, /bollingerShortTimeframe:draft\.shortTf/);
  assert.match(v2, /exposureRefillEnabled:draft\.exposureRefill/);
  assert.match(v2, /exposureRefillTriggerPercent:trigger/);
  assert.match(v2, /exposureRefillReleasePercent:release/);
});

test("V2 keeps DCA and TP independent from exposure refill controls", () => {
  assert.match(v2, /longDcaDistance:num\(draft\.longDcaDistance\)\/100/);
  assert.match(v2, /shortDcaDistance:num\(draft\.shortDcaDistance\)\/100/);
  assert.match(v2, /longTakeProfitValue:num\(draft\.longTp\)\/100/);
  assert.match(v2, /shortTakeProfitValue:num\(draft\.shortTp\)\/100/);
});
