import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
const selector=fs.readFileSync(new URL("../components/aster-strategy2-focus-pair-selector.tsx",import.meta.url),"utf8");
const proxy=fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/focus/markets/route.ts",import.meta.url),"utf8");

test("Focus live can be explicitly started after readiness instead of being hard-disabled",()=>{
  assert.ok(!maker.includes("Focus blijft Shadow-only"));
  assert.ok(maker.includes("Start Focus Live"));
  assert.ok(maker.includes('aria-checked={enabled}'));
  assert.ok(maker.includes("Controleer live-gereedheid"));
});

test("manual Focus selection is a scrollable searchable tap list backed by read-only Aster data",()=>{
  assert.ok(maker.includes("AsterStrategy2FocusPairSelector"));
  assert.ok(selector.includes('maxHeight:280'));
  assert.ok(selector.includes('overflowY:"auto"'));
  assert.ok(selector.includes("Zoek pair"));
  assert.ok(selector.includes("/api/exchanges/aster/strategy2/focus/markets"));
  assert.ok(proxy.includes('proxyStrategy2Live(request, "/v1/me/aster/strategy2/focus/markets", "GET")'));
});
