import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const component = await readFile(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../components/aster-trade-center.module.css", import.meta.url), "utf8");
const chart = await readFile(new URL("../components/trading-chart.tsx", import.meta.url), "utf8");

test("Tradecentrum uses the approved reference replacement while retaining all nine datasets", () => {
  assert.match(component, /data-reference="nexora_tradecentrum_actieve_posities\.png"/);
  assert.match(component, />Tradecentrum</);
  for (const label of ["Live", "Meeste DCA", "Ingestapt", "Gesloten", "TP", "DCA", "Hoogste winst", "Hoogste verlies", "Botacties"]) assert.match(component, new RegExp(`label: "${label}"`));
  assert.match(component, /useState<FilterKey>\("live"\)/);
  assert.match(component, /<select id="tradecentrum-filter" value=\{active\}/);
  assert.match(component, /selectFilter\(event\.target\.value as FilterKey\)/);
  assert.match(component, /filter\.key === "live" \? "Alle posities" : filter\.label/);
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

test("approved columns are exact and leverage is embedded in the coin cell", () => {
  for (const label of ["Munt", "Richting", "PnL", "Margin", "DCA", "Liq"]) assert.match(component, new RegExp(`<span>${label}</span>`));
  assert.doesNotMatch(component, /<span>LEV<\/span>/);
  assert.match(component, /className=\{styles\.coinMeta\}/);
  assert.match(component, /row\.leverage !== null \? <em>\{Math\.round\(row\.leverage\)\}x<\/em> : null/);
  assert.match(component, /className=\{styles\.marginCell\}/);
  assert.match(component, /Math\.max\(0, row\.entries - 1\)/);
});

test("liquidation column uses live exchange liquidation data and safe 100%+ semantics", () => {
  assert.match(component, /liquidationDistancePercent/);
  assert.match(component, /liquidationRiskTone/);
  assert.match(component, /side === "LONG".*rawLiq !== null && rawLiq <= 0/s);
  assert.match(component, /label: "100%\+"/);
  assert.match(component, /geen downside-liquidatie tot \$0 bij huidige portfolio-status/i);
  assert.match(component, /styles\[`liq_\$\{liq\.tone\}`\]/);
  assert.doesNotMatch(component, /label: "0,00%"/);
});

test("Tradecentrum keeps click-through detail, close controls, show-all and pagination functional", () => {
  assert.match(component, /onOpenDetail\(row\)/);
  assert.match(component, /function openDetail\(row: TradeCenterRow\)/);
  assert.match(component, /window\.setTimeout\(\(\) => \{/);
  assert.match(component, /void onRetry\(\)/);
  assert.match(component, /<SafeTradingChart selection=\{detailChartSelection \?\? detail\.selection\}/);
  assert.match(component, /authenticatedRequest\(`\/api\/exchanges\/aster\/positions\/\$\{encodeURIComponent/);
  assert.match(component, /"Toon alles"/);
  assert.match(component, /Laad nog 100/);
  assert.match(component, /setPages\(\(value\) => value \+ 1\)/);
});

test("liquidation line is only drawn for a positive directionally valid level", () => {
  assert.match(chart, /liquidationPrice\?: number/);
  assert.match(chart, /side === "LONG" \? liquidationPrice > 0 && liquidationPrice < markPrice/);
  assert.match(chart, /side === "SHORT" \? liquidationPrice > markPrice && markPrice > 0/);
  assert.match(chart, /title: "LIQUIDATIE"/);
  assert.match(chart, /color: "#ff4f73"/);
  assert.match(chart, /lineStyle: 2/);
});

test("reference layout stays compact and keeps headers, logos, margin and Liq visible on mobile", () => {
  assert.match(styles, /\.head,\.row\{display:grid;grid-template-columns:minmax\(150px,1\.55fr\).*minmax\(70px,\.68fr\)/);
  assert.match(styles, /@media\(max-width:700px\).*\.head\{display:grid!important/s);
  assert.match(styles, /\.coin\{display:grid!important/s);
  assert.match(styles, /\.marginCell,\.entries/);
  assert.match(styles, /\.liqBadge/);
  assert.match(styles, /@media\(max-width:380px\)/);
});

test("reference summary and close buttons forward to the existing safe portfolio close workflow", () => {
  for (const label of ["Totaal PnL", "Actieve posities", "Totale waarde", "Close Long", "Close Short", "Close All"]) assert.match(component, new RegExp(label));
  assert.match(component, /forwardSnapshotProfit\("LONG"\)/);
  assert.match(component, /forwardSnapshotProfit\("SHORT"\)/);
  assert.match(component, /forwardSnapshotProfit\("ALL"\)/);
  assert.match(component, /\.aps-profit-\$\{scope\.toLowerCase\(\)\}/);
  assert.match(component, /Close \$\{profitCandidates\.length\} profits/);
});

test("Live includes Airbag hedge as a managed leg and keeps existing role semantics", () => {
  assert.match(component, /livePositions = useMemo/);
  assert.match(component, /AIRBAG \/ HEDGE/);
  assert.match(component, /HOOFDPOSITIE/);
  assert.match(component, /BOT BEHEERT/);
  assert.match(component, /focusAirbagHedge === true/);
});

test("Live opens by default with highest dollar profit first", () => {
  assert.match(component, /useState<FilterKey>\("live"\)/);
  assert.match(component, /finite\(b\.unrealizedPnl\).*finite\(a\.unrealizedPnl\)/s);
});

test("Meeste DCA remains the second dataset and sorts by confirmed DCA count", () => {
  assert.match(component, /key: "live", label: "Live" \},\s*\{ key: "mostDca", label: "Meeste DCA" \}/);
  assert.match(component, /const mostDcaPositions = useMemo/);
  assert.match(component, /positionEntryCount\(a\)/);
  assert.match(component, /positionEntryCount\(b\)/);
});
