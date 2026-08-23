import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { pageActivity, reliableReturnPct, sortedActivity } from "../lib/recent-trades.mjs";

const component = await readFile(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("top profit, closed and opened sections render in the required order", () => {
  const top = component.indexOf('<TopProfitCard rows={positions}');
  const closed = component.indexOf('title="Laatste 20 uitgestapte trades" rows={exits}');
  const opened = component.indexOf('title="Laatste 5 ingestapte trades" rows={entries}');
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

test("missing exchange return falls back to trade notional without leverage ROE", () => {
  assert.equal(reliableReturnPct({ realizedPnlUsd: 0 }), null);
  assert.equal(reliableReturnPct({ roePct: -1.25 }), -1.25);
  assert.equal(reliableReturnPct({ returnPct: 0 }), 0);
  assert.equal(reliableReturnPct({ side: "LONG", unrealizedPnlUsd: 0.39, executedNotionalUsd: 24 }), 1.625);
  assert.equal(reliableReturnPct({ side: "SHORT", realizedPnlUsd: 5, closedValueUsd: 45 }), 10);
});

test("trade rows expose only percent and P&L value columns", () => {
  assert.match(component, /<span>%<\/span><span>P&amp;L<\/span>/);
  assert.doesNotMatch(component, /INGEKOCHT|INGESTAPT \(\$\)|VERKOCHT|NU WAARD|Perp ·|Niet aan strategie gekoppeld/);
  assert.match(component, /Toon alle/);
  assert.match(component, /Terug naar laatste \{compactLimit\}/);
  assert.match(component, /compactLimit=\{5\}/);
  assert.match(component, /Laad nog 100/);
});

test("mobile layout has two bounded value columns and reduced-motion fallback", () => {
  assert.match(css, /repeat\(2,minmax\(/);
  assert.match(css, /prefers-reduced-motion:reduce/);
  assert.doesNotMatch(css, /content:"IN"|content:"NU"/);
});

test("manual Aster close is confirmed, idempotent in the browser and refreshes exchange truth", () => {
  assert.match(component, /Weet je zeker dat je deze volledige positie market wilt sluiten\?/);
  assert.match(component, /if \(busy\) return/);
  assert.match(component, /crypto\.randomUUID\(\)/);
  assert.match(component, /expected_quantity/);
  assert.match(component, /await onClosed\(\)/);
  assert.match(component, />Annuleren</);
});
