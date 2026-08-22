import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { pageActivity, reliableReturnPct, sortedActivity } from "../lib/recent-trades.mjs";

const component = await readFile(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("top profit, closed and opened sections render in the required order", () => {
  const top = component.indexOf('<TopProfitCard rows={positions}');
  const closed = component.indexOf('title="Laatste 20 uitgestapte trades" rows={exits}');
  const opened = component.indexOf('title="Laatste 20 ingestapte trades" rows={entries}');
  assert.ok(top >= 0 && closed > top && opened > closed);
});

test("real exchange time wins over a newer import/update time", () => {
  const rows = sortedActivity([
    { id: "old-imported-late", timestampMs: 1000, updatedAt: 999999 },
    { id: "actually-new", timestampMs: 2000, updatedAt: 1 },
  ]);
  assert.equal(rows[0].id, "actually-new");
});

test("equal timestamps use a stable immutable id tie-break", () => {
  const rows = [{ id: "a", timestampMs: 1000 }, { id: "b", timestampMs: 1000 }];
  assert.deepEqual(sortedActivity(rows).map((row) => row.id), ["b", "a"]);
  assert.deepEqual(sortedActivity(rows.reverse()).map((row) => row.id), ["b", "a"]);
});

test("history grows in exact batches of 100 without duplicates", () => {
  const rows = Array.from({ length: 215 }, (_, index) => ({ id: String(index), timestampMs: index }));
  assert.equal(pageActivity(rows, 1).length, 100);
  assert.equal(pageActivity(rows, 2).length, 200);
  assert.equal(pageActivity(rows, 3).length, 215);
  assert.equal(new Set(pageActivity(rows, 3).map((row) => row.id)).size, 215);
});

test("missing return information stays unavailable instead of becoming zero", () => {
  assert.equal(reliableReturnPct({ realizedPnlUsd: 0 }), null);
  assert.equal(reliableReturnPct({ roePct: -1.25 }), -1.25);
  assert.equal(reliableReturnPct({ returnPct: 0 }), 0);
});

test("trade rows preserve IN, NU/UIT, percent and P&L columns", () => {
  assert.match(component, /<span>IN<\/span><span>\{closed \? "UIT" : "NU"\}<\/span><span>%<\/span><span>P&amp;L<\/span>/);
  assert.match(component, /trade\.costBasisUsd/);
  assert.match(component, /trade\.closedValueUsd/);
  assert.match(component, /trade\.executedNotionalUsd/);
  assert.match(component, /trade\.currentValueUsd/);
  assert.match(component, /Toon alle/);
  assert.match(component, /Terug naar laatste 20/);
  assert.match(component, /Laad nog 100/);
});

test("mobile layout keeps four bounded value columns and reduced-motion fallback", () => {
  assert.match(css, /repeat\(4,minmax\(/);
  assert.match(css, /prefers-reduced-motion:reduce/);
  assert.match(css, /content:"IN"/);
  assert.match(css, /content:"NU\/UIT"/);
  assert.match(css, /content:"%"/);
  assert.match(css, /content:"P&L"/);
});

test("manual Aster close is confirmed, idempotent in the browser and refreshes exchange truth", () => {
  assert.match(component, /Weet je zeker dat je deze volledige positie market wilt sluiten\?/);
  assert.match(component, /if \(busy\) return/);
  assert.match(component, /crypto\.randomUUID\(\)/);
  assert.match(component, /expected_quantity/);
  assert.match(component, /await onClosed\(\)/);
  assert.match(component, />Annuleren</);
});
