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

test("editing one side preserves the other side above the retired 100-seat ceiling", () => {
  assert.deepEqual(applyLongSlots("30", "90"), { total: 120, long: 90, short: 30 });
  assert.deepEqual(applyShortSlots("45", "90"), { total: 135, long: 45, short: 90 });
});

test("400 positions are accepted and values above the platform limit are clamped", () => {
  assert.equal(MAX_TOTAL_POSITIONS, 400);
  assert.deepEqual(splitTotalPositions("400"), { total: 400, long: 200, short: 200 });
  assert.deepEqual(splitTotalPositions("401"), { total: 400, long: 200, short: 200 });
});
