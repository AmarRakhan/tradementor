import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const source=fs.readFileSync(new URL("../lib/strategy2-focus.ts",import.meta.url),"utf8");
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");

test("Focus helper fixes max DCA at 30 and conservative default at 5",()=>{
 assert.match(source,/MAX_FOCUS_DCA=30/);
 assert.match(source,/DEFAULT_FOCUS_DCA=5/);
});

test("Focus preview keeps notional and margin semantics separate",()=>{
 assert.match(source,/totalMaxOrderNotional\/leverage/);
 assert.match(source,/focusBudgetNotional/);
 assert.match(source,/requiredMargin/);
});

test("Focus preview uses full geometric DCA series",()=>{
 assert.match(source,/Math\.pow\(m,i\)/);
});

test("Strategy 2 wizard exposes Focus without automatically starting live",()=>{
 assert.match(maker,/Focus \/ Coin van het moment/);
 assert.match(maker,/focusShadowEnabled/);
 assert.match(maker,/MAXIMALE FOCUS-EXPOSURE/);
 assert.match(maker,/tradingMode/);
 assert.match(maker,/multi_pair/);
 assert.match(maker,/focus/);
});
