import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const modal = readFileSync(new URL("../components/closed-trades-history-modal.tsx", import.meta.url), "utf8");
const endpoint = readFileSync(new URL("../app/api/exchanges/aster/closed-trades/history/route.ts", import.meta.url), "utf8");
const snapshot = readFileSync(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");

test("both snapshot metrics share exactly one historical modal", () => {
  assert.match(snapshot, /onOpenHistory\("all"\)/);
  assert.match(snapshot, /onOpenHistory\("today"\)/);
  assert.match(snapshot, /<ClosedTradesHistoryModal/);
});
test("closed-history route forwards scope and cursor to existing authenticated cloud proxy", () => {
  assert.match(endpoint, /proxyCloud\(/);
  assert.match(endpoint, /incoming\.has\("scope"\)/);
  assert.match(endpoint, /incoming\.has\("cursor"\)/);
});
test("history does not claim older backfill is complete without backend proof", () => {
  assert.match(modal, /page\.historicalBackfillComplete === true/);
  assert.match(modal, /volledigheid van oudere historie is nog niet bevestigd/);
});
test("daily card checks its counter only after all pages, not after the first page", () => {
  assert.match(modal, /mode === "today" && !hasMore && !loading && !error/);
});
