import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Build 488 Snapshot uses verified full-position close summary, not raw REALIZED_PNL events", async () => {
  const [page, cache, version, history] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/aster-snapshot-cache.mjs", import.meta.url), "utf8"),
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/release-history.ts", import.meta.url), "utf8"),
  ]);

  assert.match(version, /WEBAPP_BUILD_NUMBER = "489"/);
  assert.match(page, /closedTradeSummaryToday/);
  assert.match(page, /summary\?\.reliable === true/);
  assert.match(page, /adjustmentRealizedPnlUsd/);
  assert.match(page, /Hedge\/partial correcties apart/);
  assert.match(page, /Alleen volledig flat bevestigde posities/);
  assert.match(cache, /closedTradeSummaryToday/);
  assert.match(history, /EXCHANGE_PROVEN_FULL_POSITION_CYCLES/);
});

test("Build 488 keeps total realized adjustments visible instead of relabeling them as closed trades", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /GESLOTEN RESULTAAT VANDAAG/);
  assert.match(page, /TRADES GESLOTEN/);
  assert.doesNotMatch(page, /closedAvailable \? today\.trades/);
  assert.doesNotMatch(page, /closedAvailable \? formatSignedUsd\(today\.total\)/);
});
