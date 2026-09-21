import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Portfolio TP is additive and keeps per-trade TP enabled", async () => {
  const component = await readFile(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

  assert.match(component, /takeProfitEnabled:\s*v\.tpMode\s*!==\s*"OFF"/);
  assert.doesNotMatch(component, /takeProfitEnabled:\s*v\.tpMode\s*===\s*"PER_TRADE"/);
  assert.match(component, /takeProfitMode:\s*v\.tpMode/);
});
