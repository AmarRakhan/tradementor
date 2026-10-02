import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Aster compact Portfolio Snapshot follows the approved reference and preserves close-all flow", async () => {
  const [layout, component, css, hedgeCss, growth, hedgeManager] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8"),
    readFile(new URL("../app/portfolio-hedge.css", import.meta.url), "utf8"),
    readFile(new URL("../components/portfolio-growth-card.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-hedge-manager.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(layout, /AsterPortfolioSnapshotEnhancer/);
  assert.match(layout, /portfolio-snapshot\.css/);
  assert.match(component, /file_000000002444821084b234da2ddec369/);
  assert.match(component, /AsterHedgeManager/);
  assert.match(component, /file_00000000aa6c8210baf1b0ac8f94d18e/);
  const hedgeSummary = component.match(/function HedgeSummary[\s\S]*?function HedgeDetail/)?.[0] || "";
  assert.match(hedgeSummary, /className="aps-hedge-card"/);
  assert.match(hedgeSummary, /HEDGE DEKKING/);
  assert.doesNotMatch(hedgeSummary, /aps-hedge-goal/);
  assert.doesNotMatch(hedgeSummary, /Doel /);
  assert.doesNotMatch(hedgeSummary, /Boven doel/);
  assert.match(hedgeCss, /file_00000000aa6c8210baf1b0ac8f94d18e/);
  assert.match(hedgeCss, /\.aps-hedge-card\{[^}]*grid-template-columns:34px minmax\(0,1fr\)/);
  assert.doesNotMatch(hedgeCss, /\.aps-hedge-goal/);
  assert.match(hedgeCss, /@media\(max-width:640px\)[\s\S]*\.aps-hedge-card\{[^}]*grid-template-columns:27px minmax\(0,1fr\)/);
  assert.match(hedgeCss, /@media\(max-width:380px\)[\s\S]*\.aps-hedge-card\{[^}]*grid-template-columns:26px minmax\(0,1fr\)/);
  assert.match(hedgeManager, /file_00000000032881f495cdc99757a7d126/);
  for (const label of ["PORTFOLIO SNAPSHOT", "PORTFOLIOWAARDE", "AVAILABLE TO TRADE", "ACTIEF TRADE CAPITAL", "ACTIEVE POSITIES", "GESLOTEN RESULTAAT", "TRADES GESLOTEN", "LIQUIDATIERISICO", "RENDEMENT VANDAAG", "GEMIDDELD PER DAG", "ALLES SLUITEN"]) assert.match(component, new RegExp(label));
  assert.match(component, /portfolio-close-all/);
  assert.match(component, /legacy\.click\(\)/);
  assert.match(component, /active-trades-index > small/);
  assert.match(component, /section\[aria-label\^="Portfolio impact\."\]/);
  assert.match(component, /\.portfolio-growth-daily/);
  assert.match(component, /dailyValues\[0\]/);
  assert.match(component, /dailyValues\[1\]/);
  assert.match(growth, /todayPercentage/);
  assert.match(growth, /averageDailyPercentage/);
  assert.match(growth, /portfolio-growth-daily/);
  assert.match(growth, /\/api\/exchanges\/aster\/portfolio-growth\/daily/);
  assert.match(component, /<header>[\s\S]*aps-header-actions[\s\S]*aps-close-all[\s\S]*<\/header>/);
  assert.doesNotMatch(component, /<\/div>\s*<button type="button" className="aps-close-all"/);
  assert.match(css, /\.aster-liquidation-hero/);
  assert.match(css, /\.aster-bot-status/);
  assert.match(css, /\.metric-strip>\.metric\{display:none!important\}/);
  assert.match(css, /\.aps-close-all\{[^}]*rgba\(255,116,67,\.9\)/);
  assert.match(css, /\.aps-growth-row\{[^}]*grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(css, /\.aps-growth-card\.aps-positive strong\{color:#42e999\}/);
  assert.match(css, /\.aps-growth-card\.aps-negative strong\{color:#ff6680\}/);
  assert.doesNotMatch(css, /\.aps-close-all\{[^}]*#20e98b/);
  assert.doesNotMatch(component, /Reset startwaarde/i);
});

test("Snapshot has three live-data profit actions with separate LONG SHORT and ALL scopes", async () => {
  const [component, css, previewRoute, closeRoute] = await Promise.all([
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/positions/profitable-close-preview/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/positions/close-profitable/route.ts", import.meta.url), "utf8"),
  ]);

  for (const label of ["Close Long", "Close Short", "Close All"]) assert.match(component, new RegExp(label));
  assert.match(component, /type ProfitScope = "LONG" \| "SHORT" \| "ALL"/);
  assert.match(component, /comparison: "greater_than_or_equal"/);
  assert.match(component, /profitPreview\?\.long/);
  assert.match(component, /profitPreview\?\.short/);
  assert.match(component, /profitPreview\?\.all/);
  assert.match(component, /profitable-close-preview/);
  assert.match(component, /close-profitable/);
  assert.match(component, /eligibleCount/);
  assert.match(component, /totalProfitUsd/);
  assert.match(component, /aria-label=\{`\$\{label\}, \$\{profitMoney/);
  assert.match(css, /\.aps-profit-row\{/);
  assert.match(css, /\.aps-profit-action\{/);
  assert.match(previewRoute, /profitable-close-preview/);
  assert.match(closeRoute, /close-profitable/);
  assert.match(closeRoute, /"POST"/);
});


test("Portfolio Snapshot shows active versus configured LONG and SHORT slot capacity", async () => {
  const component = await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");

  assert.match(component, /function slotCount\(side: "long" \| "short"\)/);
  assert.match(component, /\.slot-overview \.slot-row\.\$\{side\}/);
  assert.match(component, /longCapacity: string/);
  assert.match(component, /shortCapacity: string/);
  assert.match(component, /longSlots\.active \|\| counts\?\.\[2\]/);
  assert.match(component, /shortSlots\.active \|\| counts\?\.\[3\]/);
  assert.match(component, /values\.longs\}\/\$\{values\.longCapacity\}L/);
  assert.match(component, /values\.shorts\}\/\$\{values\.shortCapacity\}S/);
  assert.match(component, /active-trades-index > small/);
});


test("Build 410 labels net exposure as exposure instead of a profit-loss amount",async()=>{
  const component=await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx",import.meta.url),"utf8");
  const hedgeSummary=component.match(/function HedgeSummary[\s\S]*?function HedgeDetail/)?.[0]||"";
  assert.ok(hedgeSummary.includes("NETTO EXPOSURE"));
  assert.equal(hedgeSummary.includes("NETTO OPEN"),false);
  assert.ok(hedgeSummary.includes("exposureMoney(exposure.netExposureUsd)"));
  assert.equal(hedgeSummary.includes("exposureMoney(exposure.netExposureUsd, true)"),false);
});

test("Build 477 moves price-zone status behind two standalone Portfolio Snapshot detail buttons",async()=>{
  const component=await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-snapshot.css",import.meta.url),"utf8");
  for(const reference of [
    "file_00000000afb481f480fb60893b473c16",
    "file_00000000a63481f493d2f56071aaeb3b",
    "file_000000002d908210a581e71c2352d09b",
  ]) assert.ok(component.includes(reference),reference);
  assert.ok(component.includes("SnapshotDetailButtons"));
  assert.ok(component.includes("Prijszone Details"));
  assert.ok(component.includes("Scanner Status"));
  assert.ok(component.includes("Dubbelklik · 3D flip"));
  assert.ok(component.includes("PriceZoneDetailsPage"));
  assert.ok(component.includes("ScannerStatusPage"));
  assert.ok(component.includes("loadPriceZoneSeatSummary"));
  assert.ok(component.includes("loadScannerStatus"));
  for(const label of ["Prijszone-strategie","Per zone","Vrij in actieve zone","Oude zones open","Max totaal","Actieve zone","Alle zones samen","LONG totaal open","SHORT totaal open","Totaal bezet"]) assert.ok(component.includes(label),label);
  const snapshot=component.match(/function Snapshot\([\s\S]*?function finiteExposure/)?.[0]||"";
  assert.match(snapshot,/SnapshotDetailButtons/);
  assert.doesNotMatch(snapshot,/<PriceZoneStrategySummary/);
  assert.ok(css.includes(".aps-detail-actions{display:grid"));
  assert.ok(css.includes(".aps-detail-page{"));
  assert.ok(css.includes(".aps-scanner-grid{"));
  assert.equal(component.includes("SnapshotQuickActions"),false);
  assert.equal(component.includes("tradementor:open-zone-soldiers-command-center"),false);
});

test("Build 469 keeps active-zone occupancy numeric across chart/backend zone transitions without fictive side caps",async()=>{
  const component=await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-snapshot.css",import.meta.url),"utf8");
  const summary=component.match(/function PriceZoneStrategySummary[\s\S]*?function Snapshot/)?.[0]||"";

  assert.match(summary,/occupiedLongActiveZone/);
  assert.match(summary,/occupiedShortActiveZone/);
  assert.match(summary,/const occupiedLongActiveZone = resolvedCounts\?\.long \?\? 0/);
  assert.match(summary,/const occupiedShortActiveZone = resolvedCounts\?\.short \?\? 0/);
  assert.match(summary,/pct\(occupiedLongActiveZone,summary\.perZoneLong\)/);
  assert.match(summary,/pct\(occupiedShortActiveZone,summary\.perZoneShort\)/);
  assert.match(summary,/summary\.zoneOpenCountsReliable/);
  assert.match(summary,/breakdown\?\.long \?\? 0/);
  assert.match(summary,/breakdown\?\.short \?\? 0/);
  assert.match(summary,/LONG totaal open[\s\S]*summary\.strategyOpenLong/);
  assert.match(summary,/SHORT totaal open[\s\S]*summary\.strategyOpenShort/);
  assert.match(summary,/Totaal bezet[\s\S]*summary\.strategyOpenTotal[\s\S]*summary\.maxTotal/);
  assert.doesNotMatch(summary,/const sideTotal\s*=/);
  assert.doesNotMatch(summary,/const longCapacity\s*=/);
  assert.doesNotMatch(summary,/const shortCapacity\s*=/);
  assert.doesNotMatch(summary,/strategyOpenLong\}\s*\/\s*\{longCapacity/);
  assert.doesNotMatch(summary,/strategyOpenShort\}\s*\/\s*\{shortCapacity/);
  assert.match(summary,/seatZoneInSync \? <b><i>\{freeLongActiveZone\}L<\/i> \/ <em>\{freeShortActiveZone\}S<\/em><\/b> : <b>— \/ —<\/b>/);
  assert.match(css,/\.aps-zone-seat-groups\{/);
  assert.match(css,/\.aps-zone-open-counts\{/);
});


test("Runtime Contract V1 phase 6 makes snapshot and scanner use operational runtime truth",async()=>{
  const component=await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx",import.meta.url),"utf8");
  assert.match(component,/runtimeTruthCanonical: boolean/);
  assert.match(component,/runtimeTruth\.source === "SERVER_RUNTIME"/);
  assert.match(component,/runtimeTruth\.strategyMode === "ZONE_WARRIORS"/);
  assert.match(component,/timestampMs\(runtimeTruth\.lastTickAt\)/);
  assert.match(component,/summary\.runtimeTruthCanonical \? summary\.activeZone/);
  assert.match(component,/runtimeTruth\.dynamicHedgeBlocking === true/);
  assert.match(component,/runtimeTruth\.queueHalted === true/);
});
