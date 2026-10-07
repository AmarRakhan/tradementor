import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Build 571 Snapshot uses canonical server closed-today accounting with reliability gating", async () => {
  const [snapshot, truth, backend] = await Promise.all([
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/aster-account-truth.ts", import.meta.url), "utf8"),
    readFile(new URL("../../cloud_api/main.py", import.meta.url), "utf8"),
  ]);
  assert.match(snapshot, /truth\.performance\.closedTodayReliable/);
  assert.match(snapshot, /truth\.performance\.realizedPnlToday/);
  assert.match(snapshot, /truth\.performance\.tradesClosedToday/);
  assert.match(truth, /closedTodayReliable/);
  assert.match(backend, /public_response\["closedTodayReliable"\]/);
  assert.match(backend, /public_response\["realizedPnlToday"\]/);
  assert.match(backend, /public_response\["tradesClosedToday"\]/);
  assert.doesNotMatch(snapshot, /REALIZED_PNL/);
});

test("Build 488 keeps total realized adjustments visible instead of relabeling them as closed trades", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /GESLOTEN RESULTAAT VANDAAG/);
  assert.match(page, /TRADES GESLOTEN/);
  assert.doesNotMatch(page, /closedAvailable \? today\.trades/);
  assert.doesNotMatch(page, /closedAvailable \? formatSignedUsd\(today\.total\)/);
});
