import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { pageActivity, reliableReturnPct, sortedActivity } from "../lib/recent-trades.mjs";

const component = await readFile(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/aster-tables.css", import.meta.url), "utf8");

test("Tradecentrum keeps the approved eight filters in one compact overview", () => {
  const labels = ["Live", "Ingestapt", "Gesloten", "TP", "DCA", "Hoogste winst", "Hoogste verlies", "Botacties"];
  let previous = -1;
  for (const label of labels) {
    const index = component.indexOf(`label: "${label}"`);
    assert.ok(index > previous, `${label} must follow the previous filter`);
    previous = index;
  }
  assert.doesNotMatch(component, /TopProfitCard|ScanActionsCard/);
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

test("recent trade freshness window remains above the 60 second exchange refresh cadence", () => {
  assert.match(component, /Date\.now\(\) - snapshot\.updatedAt < 90_000/);
  assert.doesNotMatch(component, /Date\.now\(\) - snapshot\.updatedAt < 45_000/);
});

test("Tradecentrum exposes the compact approved columns and real close control", () => {
  assert.match(component, /<span>PAIR<\/span><span>SIDE<\/span><span>LEV<\/span><span>MARGIN<\/span><span>PNL<\/span><span>PNL %<\/span><span>#<\/span><span>STATUS<\/span>/);
  assert.match(component, /function money\(value: unknown, signed = false\)/);
  assert.match(component, /<ClosePositionControl position=\{row\.position\}/);
  assert.match(component, /"Toon alles"/);
  assert.match(component, /Laad nog 100/);
});

test("trade timestamps come from confirmed exchange or persisted position time, never a poll timestamp", () => {
  assert.match(component, /function exchangeTimestampMs/);
  assert.match(component, /row\.seconds/);
  assert.match(component, /row\.nanoseconds/);
  assert.match(component, /timestamp: position\.openedAt/);
  assert.match(component, /exchangeTimestampMs\(row\.timestamp\)/);
  assert.doesNotMatch(component, /Date\.now\(\).*openedAt|updatedAt.*openedAt/);
});

test("margin prefers positive Aster initial margin and falls back to notional divided by proven leverage", () => {
  assert.match(component, /function openPositionMargin/);
  assert.match(component, /direct !== null && direct > 0/);
  assert.match(component, /notional \/ leverage/);
  assert.match(component, /trade\.marginUsd, trade\.initialMarginUsd/);
  assert.match(component, /basis \/ leverage/);
  assert.match(component, /margin: openPositionMargin\(position\)/);
  assert.match(component, /money\(row\.margin\)/);
});

test("manual Aster close is confirmed, idempotent and refreshes exchange truth", () => {
  assert.match(component, /Weet je zeker dat je deze volledige positie market wilt sluiten\?/);
  assert.match(component, /if \(busy \|\| !position\?\.symbol/);
  assert.match(component, /crypto\.randomUUID\(\)/);
  assert.match(component, /expected_quantity/);
  assert.match(component, /idempotency_key/);
  assert.match(component, /await onClosed\(\)/);
  assert.match(component, />Annuleren<\/button>/);
});

test("scan actions and closed rows use real status labels in the shared Tradecentrum table", () => {
  assert.match(component, /function scanActionLabel/);
  assert.match(component, /TP_KINDS/);
  assert.match(component, /DCA_KINDS/);
  assert.match(component, /closed \? \(matching && TP_KINDS/);
  assert.match(component, /\? "TP" : "Gesloten"/);
  assert.match(component, /className=\{styles\.statusText\}>\{row\.status\}/);
});

test("Aster close confirmation is portalled to document.body so table containment cannot distort it", () => {
  assert.match(component, /import \{ createPortal \} from "react-dom"/);
  assert.match(component, /typeof document !== "undefined" && createPortal\(/);
  assert.match(component, /document\.body/);
  assert.match(component, /role="dialog" aria-modal="true"/);
});
