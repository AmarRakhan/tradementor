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

test("Portfolio Cycle tile prefers the durable restarted cycle over a stale report", () => {
  const state = derivePortfolioCycleCard({
    equity: 103.50,
    strategy2: {
      settings: { takeProfitMode: "PORTFOLIO" },
      multiBbCycle: { cycleStartEquity: 103.50, baseEquity: 103.50, targetEquity: 104.0175 },
      multiBb: { portfolioCycle: { cycleStartEquity: 102.95, baseEquity: 102.95, targetEquity: 103.47 } },
    },
  });
  assert.equal(state.active, true);
  assert.equal(state.progressPercent, 0);
  assert.equal(state.remainingUsd?.toFixed(2), "0.52");
  assert.equal(state.statusLabel, "Actief");
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


test("Build 481 Portfolio Cycle Snapshot is balanced when active and when UIT",async()=>{
  const { readFile }=await import("node:fs/promises");
  const [component,css]=await Promise.all([
    readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/profit-pot-snapshot.css",import.meta.url),"utf8"),
  ]);
  const start=component.indexOf("function PortfolioCycleCard");
  const end=component.indexOf("export function AsterProfitPotSnapshotBridge",start);
  const block=component.slice(start,end);
  const inactive=block.slice(0,block.indexOf("const progress"));
  const active=block.slice(block.indexOf("const progress"));
  assert.match(component,/file_00000000ba448210b16f35eaf915a01f/);
  assert.match(css,/file_00000000ba448210b16f35eaf915a01f/);
  assert.match(inactive,/PORTFOLIO CYCLUS/);
  assert.match(inactive,/<strong>UIT<\/strong>/);
  assert.match(inactive,/Geen actieve cyclus/);
  assert.doesNotMatch(inactive,/Instellen/);
  assert.match(inactive,/onClick=\{openPortfolioTakeProfitSettings\}/);
  assert.match(active,/Math\.round\(progress\).*%/s);
  assert.match(active,/aps-cycle-progress/);
  assert.match(active,/Nog \{formatCycleMoney\(state\.remainingUsd\)\}/);
  assert.match(active,/onClick=\{openPortfolioTakeProfitSettings\}/);
  assert.doesNotMatch(active,/formatCyclePercent/);
  assert.doesNotMatch(active,/state\.statusLabel/);
  assert.doesNotMatch(active,/aps-cycle-active-foot/);
  assert.match(css,/Build 481 — Portfolio Snapshot cycle visual polish/);
  assert.match(css,/\.aps-cycle-inactive-copy strong\{[\s\S]*font-size:12\.2px/);
  assert.match(css,/\.aps-cycle-inactive-copy em\{[\s\S]*font-size:6\.5px/);
  assert.match(css,/\.aps-cycle-active-head\{[\s\S]*display:grid/);
});
