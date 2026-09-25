import test from "node:test";
import assert from "node:assert/strict";
import { derivePortfolioCycleCard } from "../lib/portfolio-cycle-card.ts";

test("Portfolio Cycle tile stays inactive outside Portfolio TP mode", () => {
  const state = derivePortfolioCycleCard({ strategy2: { settings: { takeProfitMode: "PER_TRADE" } } });
  assert.equal(state.active, false);
  assert.equal(state.statusLabel, "Niet ingesteld");
});

test("Portfolio Cycle tile stays inactive until a valid cycle exists", () => {
  const state = derivePortfolioCycleCard({ strategy2: { settings: { takeProfitMode: "PORTFOLIO" } } });
  assert.equal(state.active, false);
});

test("Portfolio Cycle tile calculates live progress from server cycle data", () => {
  const state = derivePortfolioCycleCard({
    equity: 139.25,
    strategy2: {
      settings: { takeProfitMode: "PORTFOLIO" },
      multiBb: { portfolioCycle: { baseEquity: 128.49, targetEquity: 140.12 } },
    },
  });
  assert.equal(state.active, true);
  assert.equal(state.statusLabel, "Bijna eruit");
  assert.equal(state.remainingUsd?.toFixed(2), "0.87");
  assert.equal(state.remainingPercent?.toFixed(2), "0.62");
  assert.ok((state.progressPercent ?? 0) > 90);
});

test("Portfolio Cycle tile supports legacy multiBbCycle payloads and caps at target", () => {
  const state = derivePortfolioCycleCard({
    account: { totalMarginBalance: 105 },
    strategy2: {
      settings: { takeProfitMode: "PORTFOLIO" },
      multiBbCycle: { cycleStartEquity: 100, targetEquity: 105 },
    },
  });
  assert.equal(state.active, true);
  assert.equal(state.progressPercent, 100);
  assert.equal(state.remainingUsd, 0);
  assert.equal(state.statusLabel, "Doel bereikt");
});


test("Build 432 inactive Portfolio Cycle Snapshot hides the duplicate Niet ingesteld headline",async()=>{
  const { readFile }=await import("node:fs/promises");
  const component=await readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx",import.meta.url),"utf8");
  const start=component.indexOf("function PortfolioCycleCard");
  const inactive=component.slice(start,component.indexOf("const progress",start));
  assert.match(inactive,/PORTFOLIO CYCLUS/);
  assert.match(inactive,/Portfolio TP niet actief/);
  assert.doesNotMatch(inactive,/<strong>Niet ingesteld<\/strong>/);
});
