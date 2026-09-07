import test from "node:test";
import assert from "node:assert/strict";
import { MAX_TOTAL_POSITIONS, applyLongSlots, applyShortSlots, splitTotalPositions } from "../lib/position-slot-input.ts";

test("total 70 defaults to a stable 35/35 split", () => {
  assert.deepEqual(splitTotalPositions("70"), { total: 70, long: 35, short: 35 });
});

test("odd totals use LONG first and still preserve the exact total", () => {
  assert.deepEqual(splitTotalPositions("71"), { total: 71, long: 36, short: 35 });
});

test("editing LONG keeps total fixed and derives SHORT", () => {
  assert.deepEqual(applyLongSlots("70", "40"), { total: 70, long: 40, short: 30 });
});

test("editing SHORT keeps total fixed and derives LONG", () => {
  assert.deepEqual(applyShortSlots("70", "22"), { total: 70, long: 48, short: 22 });
});

test("100 positions are accepted and values above the limit are clamped", () => {
  assert.equal(MAX_TOTAL_POSITIONS, 100);
  assert.deepEqual(splitTotalPositions("100"), { total: 100, long: 50, short: 50 });
  assert.deepEqual(splitTotalPositions("101"), { total: 100, long: 50, short: 50 });
});
