import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Aster compact Portfolio Snapshot follows the approved reference and preserves close-all flow", async () => {
  const [layout, component, css, growth] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8"),
    readFile(new URL("../components/portfolio-growth-card.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(layout, /AsterPortfolioSnapshotEnhancer/);
  assert.match(layout, /portfolio-snapshot\.css/);
  assert.match(component, /file_00000000a7bc82438e4e1d5f076b47c9/);
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
