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

test("Build 437 adds the Zone-Soldaten quick row to Portfolio Snapshot",async()=>{
  const component=await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-snapshot.css",import.meta.url),"utf8");
  assert.ok(component.includes("file_0000000061fc81f49a44564879d533de"));
  assert.ok(component.includes("SnapshotQuickActions"));
  assert.ok(component.includes("ZONE-SOLDATEN"));
  assert.ok(component.includes("Dubbeltik om te openen"));
  assert.ok(component.includes("BOT STATUS"));
  assert.ok(component.includes("STRATEGIE"));
  assert.ok(component.includes("INSTELLINGEN"));
  assert.ok(component.includes("onDoubleClick={openZoneSoldiers}"));
  assert.ok(component.includes("onTouchEnd={onZoneTouchEnd}"));
  assert.ok(component.includes("tradementor:open-zone-soldiers-command-center"));
  assert.ok(css.includes(".aps-quick-actions{display:grid"));
  const quick=component.indexOf("<SnapshotQuickActions />");
  const grid=component.indexOf('<div className="aps-grid">');
  assert.ok(quick>0&&quick<grid);
});
