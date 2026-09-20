import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("slot overview prefers current Aster exchange positions over Strategy-2 ownership counters", () => {
  assert.match(maker, /const exchangeSlotRows = Array\.isArray\(snapshot\?\.positions\)/);
  assert.match(maker, /const exchangeSlotTruthAvailable = Array\.isArray\(snapshot\?\.positions\)/);
  assert.match(maker, /const activeLong = exchangeSlotTruthAvailable \? exchangeActiveLong : strategyActiveLong/);
  assert.match(maker, /const activeShort = exchangeSlotTruthAvailable \? exchangeActiveShort : strategyActiveShort/);
});

test("slot overview still falls back safely when no exchange position array is available", () => {
  assert.match(maker, /const strategyActiveLong = Number\(state\.longLegs \?\? rawReport\.activeLong \?\? 0\)/);
  assert.match(maker, /const strategyActiveShort = Number\(state\.shortLegs \?\? rawReport\.activeShort \?\? 0\)/);
});
