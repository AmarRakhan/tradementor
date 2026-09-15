import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Portfolio Noodhedge AAN draft is not reset by open-panel refresh", async () => {
  const source = await readFile(new URL("../components/aster-portfolio-emergency-hedge.tsx", import.meta.url), "utf8");
  assert.match(source, /if \(!open\) return;[\s\S]*refresh\(false\)/);
  assert.doesNotMatch(source, /if \(!open\) return;[\s\S]{0,220}refresh\(true\)/);
  assert.match(source, /setDraftEnabled\(true\); setDirty\(true\)/);
});
