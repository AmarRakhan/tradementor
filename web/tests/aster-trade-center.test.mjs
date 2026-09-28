import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const component = await readFile(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../components/aster-trade-center.module.css", import.meta.url), "utf8");
const chart = await readFile(new URL("../components/trading-chart.tsx", import.meta.url), "utf8");

test("Tradecentrum binds the three supplied image IDs and retains all nine datasets", () => {
  for (const id of [
    "file_00000000035c8210978ce05d3eded847",
    "file_000000000cb881f48416e7d6470ae96e",
    "file_00000000b4448210b7ba77e95c90619b",
  ]) assert.ok(component.includes(id));
  assert.match(component, /data-reference="nexora_tradecentrum_actieve_posities\.png"/);
  assert.match(component, /data-source-reference-id=\{TRADE_CENTER_REFERENCE_IDS\.current\}/);
  assert.match(component, /data-reference-id=\{TRADE_CENTER_REFERENCE_IDS\.main\}/);
  assert.match(component, /data-reference-id=\{TRADE_CENTER_REFERENCE_IDS\.close\}/);
  assert.match(component, />Tradecentrum</);
  for (const label of ["Live", "Meeste DCA", "Ingestapt", "Gesloten", "TP", "DCA", "Hoogste winst", "Hoogste verlies", "Botacties"]) {
    assert.ok(component.includes('label: "' + label + '"'));
  }
  assert.match(component, /useState<FilterKey>\("live"\)/);
  assert.match(component, /<select id="tradecentrum-filter" value=\{active\}/);
  assert.match(component, /selectFilter\(event\.target\.value as FilterKey\)/);
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

test("overview columns replace only Liq with a per-position Close action", () => {
  for (const label of ["Munt", "Richting", "PnL", "Margin", "DCA", "Close"]) {
    assert.ok(component.includes("<span>" + label + "</span>"));
  }
  const tableStart = component.indexOf("function TradeCenterTable");
  const tableEnd = component.indexOf("function focusActionLabel", tableStart);
  const table = component.slice(tableStart, tableEnd);
  assert.doesNotMatch(table, /<span>Liq<\/span>/);
  assert.doesNotMatch(table, /styles\.liqBadge/);
  assert.match(table, /className=\{styles\.rowClose\}/);
  assert.match(table, /onOpenClose\(row\.position\)/);
  assert.match(table, /focusAirbagHedge !== true/);
  assert.doesNotMatch(component, /<span>LEV<\/span>/);
  assert.match(component, /className=\{styles\.coinMeta\}/);
  assert.match(component, /row\.leverage !== null \? <em>\{Math\.round\(row\.leverage\)\}x<\/em> : null/);
  assert.match(component, /Math\.max\(0, row\.entries - 1\)/);
});

test("liquidation math remains available for detail/chart while disappearing from overview", () => {
  assert.match(component, /function liquidationPresentation/);
  assert.match(component, /liquidationDistancePercent/);
  assert.match(component, /liquidationRiskTone/);
  assert.match(component, /side === "LONG".*rawLiq !== null && rawLiq <= 0/s);
  assert.match(component, /label: "100%\+"/);
  assert.match(component, /detailLiquidation/);
  assert.match(component, />AFSTAND TOT LIQ</);
  assert.match(component, />LIQUIDATIE</);
  assert.doesNotMatch(component, /label: "0,00%"/);
});

test("position close screen offers exact percentages, live preview and one position-bound request", () => {
  assert.match(component, /function PositionClosePanel/);
  assert.match(component, /useState\(50\)/);
  assert.match(component, /\[25, 50, 75, 100\]\.map/);
  for (const label of [
    "Te sluiten qty",
    "Te sluiten waarde",
    "Geschatte opbrengst",
    "Geschatte PnL",
    "Resterende positie na sluiten",
    "Resterende waarde",
  ]) assert.ok(component.includes(label));
  assert.match(component, /expected_quantity: quantity/);
  assert.match(component, /percentage,/);
  assert.match(component, /idempotency_key: requestKey\.current/);
  assert.match(component, /newCloseIdempotencyKey\(\)/);
  assert.match(component, /"Sluit " \+ percentage \+ "%"/);
  assert.match(component, /"Positie volledig sluiten"/);
  assert.match(component, /"Positie gedeeltelijk sluiten"/);
  assert.match(component, /Dit is een marktorder en wordt direct uitgevoerd/);
  assert.match(component, /marktslippage/);
});

test("position close surfaces progress and backend errors above the execute button", () => {
  const start = component.indexOf("function PositionClosePanel");
  const end = component.indexOf("function rowFromPosition", start);
  const panel = component.slice(start, end);
  assert.match(panel, /setMessage\("Sluitopdracht wordt gecontroleerd…"\)/);
  assert.match(panel, /aria-live="polite"/);
  assert.match(panel, /aria-atomic="true"/);
  const statusIndex = panel.indexOf("className={styles.closeMessage}");
  const primaryIndex = panel.indexOf("className={styles.closePrimary}");
  assert.ok(statusIndex >= 0 && primaryIndex >= 0 && statusIndex < primaryIndex);
  const tryIndex = panel.indexOf("try {");
  const keyIndex = panel.indexOf("newCloseIdempotencyKey()");
  assert.ok(tryIndex >= 0 && keyIndex > tryIndex);
});

test("close flow uses the existing 3D flip and returns to the preserved scroll position", () => {
  assert.match(component, /detail \|\| closeTarget \? styles\.detailOpen/);
  assert.match(component, /<PositionClosePanel position=\{liveClosePosition\}/);
  assert.match(component, /function openClosePosition\(position: OpenPosition\)/);
  assert.match(component, /setCloseTarget\(\{ symbol:/);
  assert.match(component, /function closeClosePanel\(\)/);
  assert.match(component, /window\.scrollTo\(\{ top: scrollYRef\.current, behavior: "auto" \}\)/);
  assert.match(styles, /\.detailInner\{display:grid;transform-style:preserve-3d;transition:transform/);
  assert.match(styles, /\.detailOpen \.detailInner\{transform:rotateY\(180deg\)\}/);
  assert.match(styles, /\.back\{transform:rotateY\(180deg\)/);
});

test("protected Airbag hedge remains unavailable to the normal close control", () => {
  assert.match(component, /const protectedHedge = position\?\.focusAirbagHedge === true/);
  assert.match(component, /Beschermde hedge/);
  assert.match(component, /bestaande hedge\/recovery-flow/);
  assert.match(component, /disabled=\{busy \|\| protectedHedge\}/);
});

test("Tradecentrum keeps click-through detail, show-all and pagination functional", () => {
  assert.match(component, /onOpenDetail\(row\)/);
  assert.match(component, /function openDetail\(row: TradeCenterRow\)/);
  assert.match(component, /window\.setTimeout\(\(\) => \{/);
  assert.match(component, /void onRetry\(\)/);
  assert.match(component, /<SafeTradingChart selection=\{detailChartSelection \?\? detail\.selection\}/);
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

test("reference layout stays compact and keeps headers, logos, margin and Close visible on mobile", () => {
  assert.match(styles, /\.head,\.row\{display:grid;grid-template-columns:minmax\(150px,1\.55fr\).*minmax\(70px,\.68fr\)/);
  assert.match(styles, /@media\(max-width:700px\).*\.head\{display:grid!important/s);
  assert.match(styles, /\.coin\{display:grid!important/s);
  assert.match(styles, /\.marginCell,\.entries/);
  assert.match(styles, /\.rowClose\{/);
  assert.match(styles, /\.closePanel\{/);
  assert.match(styles, /\.closeChoices\{display:grid;grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);
  assert.match(styles, /@media\(max-width:380px\)/);
});

test("existing portfolio close buttons still forward to the safe bulk workflow", () => {
  for (const label of ["Totaal PnL", "Actieve posities", "Totale waarde", "Close Long", "Close Short", "Close All"]) assert.ok(component.includes(label));
  assert.match(component, /forwardSnapshotProfit\("LONG"\)/);
  assert.match(component, /forwardSnapshotProfit\("SHORT"\)/);
  assert.match(component, /forwardSnapshotProfit\("ALL"\)/);
  assert.match(component, /\.aps-profit-/);
  assert.match(component, /profitCandidates\.length/);
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
