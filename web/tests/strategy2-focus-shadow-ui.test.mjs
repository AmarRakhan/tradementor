import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
const panel=fs.readFileSync(new URL("../components/aster-strategy2-focus-shadow.tsx",import.meta.url),"utf8");
const proxy=fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/focus/shadow/route.ts",import.meta.url),"utf8");

test("Focus Shadow UI stays order-free and routed through Strategy 2 auth",()=>{
  assert.match(maker,/AsterStrategy2FocusShadow enabled=/);
  assert.match(maker,/Focus blijft Shadow-only/);
  assert.match(panel,/ordersSent = \{String\(report\.ordersSent\?\?0\)\}/);
  assert.match(panel,/Pair \| 24h % \| huidige prijs/);
  assert.match(proxy,/proxyStrategy2Live/);
  assert.match(proxy,/\/v1\/me\/aster\/strategy2\/focus\/shadow/);
});
