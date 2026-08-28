import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const component = await readFile(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../components/aster-trade-center.module.css", import.meta.url), "utf8");

test("Aster Tradecentrum replaces the four standalone trade cards with eight interactive filters", () => {
  assert.match(component, />Tradecentrum</);
  for (const label of ["Live", "Ingestapt", "Gesloten", "TP", "DCA", "Hoogste winst", "Hoogste verlies", "Botacties"]) assert.match(component, new RegExp(`label: "${label}"`));
  assert.match(component, /useState<FilterKey>\("live"\)/);
  assert.match(component, /aria-pressed=\{active === filter\.key\}/);
  assert.match(component, /onClick=\{\(\) => selectFilter\(filter\.key\)\}/);
  assert.doesNotMatch(component, /Top 5 hoogste profit|Laatste 15 scan acties|Laatste 5 uitgestapte trades|Laatste 5 ingestapte trades/);
});

test("Tradecentrum derives every view from the existing confirmed Aster snapshot sources", () => {
  assert.match(component, /recentTradeActivity/);
  assert.match(component, /snapshot\.data\?\.positions/);
  assert.match(component, /orderQueue\.lastScanActions/);
  assert.match(component, /topProfitPositions\(allPositions\)/);
  assert.match(component, /TP_KINDS/);
  assert.match(component, /DCA_KINDS/);
  assert.doesNotMatch(component, /dummy|mockTrade|fakeTrade/i);
});

test("Tradecentrum keeps detail, close, show-all and pagination interactions functional", () => {
  assert.match(component, /authenticatedRequest\(`\/api\/exchanges\/aster\/positions\/\$\{encodeURIComponent/);
  assert.match(component, /<SafeTradingChart/);
  assert.match(component, /"Toon alles"/);
  assert.match(component, /Laad nog 100/);
  assert.match(component, /setPages\(value => value \+ 1\)/);
  assert.match(component, /onOpenDetail\(row\)/);
  assert.match(component, /Geen bevestigde gegevens voor dit filter/);
  assert.match(component, /Tradegegevens tijdelijk niet beschikbaar/);
});

test("Tradecentrum is compact and mobile-safe", () => {
  assert.match(styles, /\.filters\{[^}]*overflow-x:auto/);
  assert.match(styles, /\.filter\.active/);
  assert.match(styles, /@media\(max-width:700px\)/);
  assert.match(styles, /grid-template-columns:minmax\(112px,1\.35fr\)/);
  assert.match(styles, /\.long,.profit\{color:#58f0ae\}/);
  assert.match(styles, /\.short,.loss\{color:#ff617d\}/);
});
