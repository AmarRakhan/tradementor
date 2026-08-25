import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { pageActivity, reliableReturnPct, sortedActivity } from "../lib/recent-trades.mjs";

const component = await readFile(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/aster-tables.css", import.meta.url), "utf8");

test("top profit, latest entries and latest exits render in the approved order", () => {
  const top = component.indexOf('<TopProfitCard rows={positions}');
  const closed = component.indexOf('title="Laatste 5 uitgestapte trades" rows={exits}');
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

test("recent trade freshness window remains above the 60 second exchange refresh cadence", () => {
  assert.match(component, /Date\.now\(\) - snapshot\.updatedAt < 90_000/);
  assert.doesNotMatch(component, /Date\.now\(\) - snapshot\.updatedAt < 45_000/);
});

test("all compact trade tables expose the exact six approved columns", () => {
  assert.match(component, /<span>PAIR<\/span><span>LEV<\/span><span>CLOSE<\/span><span>MARGIN<\/span><span>%<\/span><span>P&amp;L<\/span>/);
  assert.match(component, />\s*Close\s*<\/button>/);
  assert.match(component, /function money\(value: unknown\)/);
  assert.match(component, /`\$\$\{amount\(n\)\}`/);
  assert.equal((component.match(/compactLimit=\{5\}/g) || []).length, 2);
  assert.doesNotMatch(component, /Laatste 20 (?:in|uit)gestapte trades/);
  assert.doesNotMatch(component, /INGEKOCHT|INGESTAPT \(\$\)|VERKOCHT|NU WAARD|Perp ·|Niet aan strategie gekoppeld/);
});

test("top profit entry timestamp is reconstructed from confirmed activity, never a poll timestamp", () => {
  assert.match(component, /function currentCycleOpenedAt/);
  assert.match(component, /activityTime\(a\) - activityTime\(b\)/);
  assert.match(component, /openedAt=\{currentCycleOpenedAt\(position, entries, exits\)\}/);
  assert.doesNotMatch(component, /Date\.now\(\).*openedAt|updatedAt.*openedAt/);
});

test("top profit renders Firestore and exchange timestamp shapes instead of a dash", () => {
  assert.match(component, /function exchangeTimestampMs/);
  assert.match(component, /row\.seconds/);
  assert.match(component, /row\.nanoseconds/);
  assert.match(component, /new Date\(exchangeTimestampMs\(openedAt\)\)\.toISOString\(\)/);
});

test("margin prefers positive Aster initial margin and falls back to live position size divided by proven leverage", () => {
  assert.match(component, /function openPositionMargin/);
  assert.match(component, /direct !== null && direct > 0/);
  assert.match(component, /notional \/ leverage/);
  assert.match(component, /trade\.marginUsd, trade\.initialMarginUsd/);
  assert.match(component, /basis \/ leverage/);
  assert.match(component, /money\(openPositionMargin\(position\)\)/);
});

test("compact trade cards size to the visible face and align numeric columns cleanly", () => {
  assert.match(css, /recent-flip-inner\{display:block!important;transform:none!important/);
  assert.match(css, /recent-flip-back\{display:none!important/);
  assert.match(css, /is-flipped \.recent-flip-back\{display:block!important/);
  assert.match(css, /recent-close-cell\{justify-content:center!important/);
  assert.match(css, /recent-leverage\{text-align:center!important/);
  assert.match(css, /font-size:9px!important/);
});

test("mobile six-column grid is bounded and keeps headers and Close position stable", () => {
  assert.match(css, /\.aster-six-column-head,\.aster-six-column-row\{display:grid!important/);
  assert.match(css, /grid-template-columns:minmax\(0,1fr\) 28px 46px 58px 40px 42px!important/);
  assert.match(css, /\.recent-trades-head\.aster-six-column-head|\.aster-six-column-head\{display:grid!important/);
  assert.match(css, /overflow-x:hidden/);
  assert.match(css, /width:44px;min-width:44px;max-width:44px/);
  assert.match(css, /contain:layout/);
});

test("manual Aster close is confirmed, idempotent in the browser and refreshes exchange truth", () => {
  assert.match(component, /Weet je zeker dat je deze volledige positie market wilt sluiten\?/);
  assert.match(component, /if \(busy\) return/);
  assert.match(component, /crypto\.randomUUID\(\)/);
  assert.match(component, /expected_quantity/);
  assert.match(component, /await onClosed\(\)/);
  assert.match(component, />Annuleren</);
});


test("percent heading aligns with percent values", () => {
  assert.match(css, /span:nth-child\(5\).*strong:first-of-type/);
});


test("closed trade rows keep the Close column empty instead of rendering a disabled button", () => {
  assert.match(component, /recent-close-cell[^\n]*\{closed \? null : <ClosePositionControl/);
});


test("Aster close confirmation is portalled to document.body so table containment cannot distort it", () => {
  assert.match(component, /import \{ createPortal \} from "react-dom"/);
  assert.match(component, /typeof document !== "undefined" && createPortal\(/);
  assert.match(component, /document\.body/);
  assert.match(component, /aria-labelledby="aster-close-title"/);
});
