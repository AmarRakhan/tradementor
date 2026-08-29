import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");

test("Focus exposure preview uses the persisted selected pair market price",()=>{
  assert.match(maker,/const focusCurrentPrice=/);
  assert.match(maker,/entryPrice:focusCurrentPrice>0\?focusCurrentPrice:100/);
  assert.match(maker,/focusStatus\.report/);
  assert.match(maker,/AsterStrategy2FocusPairSelector rows=\{focusRanking\}/);
  assert.match(maker,/focusSelectedPair/);
});
