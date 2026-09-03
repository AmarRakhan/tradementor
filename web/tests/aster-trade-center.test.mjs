import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const component = await readFile(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../components/aster-trade-center.module.css", import.meta.url), "utf8");

test("Aster Tradecentrum replaces the four standalone trade cards with nine interactive filters", () => {
  assert.match(component, />Tradecentrum</);
  for (const label of ["Live", "Meeste DCA", "Ingestapt", "Gesloten", "TP", "DCA", "Hoogste winst", "Hoogste verlies", "Botacties"]) assert.match(component, new RegExp(`label: "${label}"`));
  assert.match(component, /useState<FilterKey>\("live"\)/);
  assert.match(component, /aria-pressed=\{active === filter\.key\}/);
  assert.match(component, /onClick=\{\(\) => selectFilter\(filter\.key\)\}/);
  assert.doesNotMatch(component, /Top 5 hoogste profit|Laatste 15 scan acties|Laatste 5 uitgestapte trades|Laatste 5 ingestapte trades/);
});

test("Tradecentrum derives every view from the existing confirmed Aster snapshot sources", () => {
  assert.match(component, /recentTradeActivity/);
  assert.match(component, /snapshot\.data\?\.positions/);
  assert.match(component, /orderQueue\.lastScanActions/);
  assert.match(component, /topProfitPositions\(mainPositions\)/);
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
  assert.match(styles, /grid-template-columns:minmax\(90px,1\.2fr\)/);
  assert.match(styles, /\.long,.profit\{color:#58f0ae\}/);
  assert.match(styles, /\.short,.loss\{color:#ff617d\}/);
});


test("Live includes Airbag hedge as a clearly managed leg", () => {
  assert.match(component, /livePositions = useMemo\(\(\) => \[\.\.\.positionsWithMultiDcaCounts\]/);
  assert.match(component, /AIRBAG \/ HEDGE/);
  assert.match(component, /HOOFDPOSITIE/);
  assert.match(component, /BOT BEHEERT/);
  assert.match(component, /focusAirbagHedge === true/);
});


test("Tradecentrum adds compact PnL percent and entry-count columns without removing existing columns", () => {
  for (const label of ["PAIR", "SIDE", "LEV", "MARGIN", "PNL", "PNL %", "STATUS"]) assert.match(component, new RegExp(`<span>${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}</span>`));
  assert.match(component, /positionPricePnlPct/);
  assert.match(component, /positionEntryCount/);
  assert.match(component, /Math\.round\(dca\) \+ 1/);
  assert.match(component, /multiBbPositions/);
  assert.match(component, /dcaCountReliable/);
  assert.match(component, /dcaCountReliable !== true && position\.strategy2DcaLadder\?\.available !== true/);
});

test("Live opens by default with highest dollar profit first", () => {
  assert.match(component, /useState<FilterKey>\("live"\)/);
  assert.match(component, /finite\(b\.unrealizedPnl\).*finite\(a\.unrealizedPnl\)/);
});

test("Live opens by default with highest dollar profit first", () => {
  assert.match(component, /useState<FilterKey>\("live"\)/);
  assert.match(component, /finite\(b\.unrealizedPnl\).*finite\(a\.unrealizedPnl\)/);
});

test("Meeste DCA is the second tab and sorts live trades by confirmed DCA count", () => {
  assert.match(component, /key: "live", label: "Live" \}, \{ key: "mostDca", label: "Meeste DCA" \}, \{ key: "entered", label: "Ingestapt"/);
  assert.match(component, /const mostDcaPositions = useMemo/);
  assert.match(component, /positionEntryCount\(a\)/);
  assert.match(component, /positionEntryCount\(b\)/);
  assert.match(component, /showDcaCount=\{active === "mostDca"\}/);
  assert.match(component, /showDcaCount \? "DCA" : "#"/);
  assert.match(component, /Math\.max\(0, row\.entries - 1\)/);
});
