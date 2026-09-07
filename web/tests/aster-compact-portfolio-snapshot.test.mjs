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
  assert.match(component, /m_6a9e9a59189881918875e6317fdfc847/);
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