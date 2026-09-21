import test from "node:test";
import assert from "node:assert/strict";
import { MAX_TOTAL_POSITIONS, applyLongSlots, applyShortSlots, splitTotalPositions } from "../lib/position-slot-input.ts";

test("total 70 defaults to a stable 35/35 split", () => {
  assert.deepEqual(splitTotalPositions("70"), { total: 70, long: 35, short: 35 });
});

test("odd totals use LONG first and still preserve the exact total", () => {
  assert.deepEqual(splitTotalPositions("71"), { total: 71, long: 36, short: 35 });
});

test("editing LONG preserves SHORT and recalculates total", () => {
  assert.deepEqual(applyLongSlots("30", "45"), { total: 75, long: 45, short: 30 });
});

test("editing SHORT preserves LONG and recalculates total", () => {
  assert.deepEqual(applyShortSlots("45", "20"), { total: 65, long: 45, short: 20 });
});

test("editing one side never pushes the combined total above the hard limit", () => {
  assert.deepEqual(applyLongSlots("30", "90"), { total: 100, long: 70, short: 30 });
  assert.deepEqual(applyShortSlots("45", "90"), { total: 100, long: 45, short: 55 });
});

test("100 positions are accepted and values above the limit are clamped", () => {
  assert.equal(MAX_TOTAL_POSITIONS, 100);
  assert.deepEqual(splitTotalPositions("100"), { total: 100, long: 50, short: 50 });
  assert.deepEqual(splitTotalPositions("101"), { total: 100, long: 50, short: 50 });
});
