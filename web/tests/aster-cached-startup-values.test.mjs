import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Build 571 never renders stale or unconfirmed browser-retained Aster financial values", async () => {
  const display = await readFile(new URL("../lib/aster-account-display.ts", import.meta.url), "utf8");
  const hook = await readFile(new URL("../lib/use-exchange-data.ts", import.meta.url), "utf8");
  assert.match(display, /const reliable = Boolean\(data\) && configured && serverConfirmed && !error && fresh/);
  assert.match(display, /const displayable = reliable/);
  assert.doesNotMatch(hook, /cachedAsterSnapshot|loadAsterSnapshot|saveAsterSnapshot/);
  assert.doesNotMatch(hook, /window\.localStorage/);
  assert.match(hook, /aster: emptySnapshot\(\)/);
});

test("Build 571 account switch starts empty and waits for the new UID server truth", async () => {
  const hook = await readFile(new URL("../lib/use-exchange-data.ts", import.meta.url), "utf8");
  assert.match(hook, /if \(state\.uid === uid\) return;/);
  assert.match(hook, /setState\(\{ uid, snapshots: \{ hyperliquid: emptySnapshot\(\), aster: emptySnapshot\(\) \} \}\)/);
  assert.doesNotMatch(hook, /source:\s*"cache"/);
});
