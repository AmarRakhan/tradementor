import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const files=[
  "../components/aster-dry-run-control.tsx",
  "../components/aster-strategy2-maker.tsx",
  "../components/aster-strategy3-control.tsx",
  "../components/hyperliquid-strategy-control.tsx",
  "../components/aster-universe-status.tsx",
  "../components/aster-performance-panel.tsx",
  "../components/aster-strategy2-behavior.tsx",
  "../lib/aster-strategy3-paper.ts",
].map(path=>fs.readFileSync(new URL(path,import.meta.url),"utf8"));
const source=files.join("\n");
const strategy2Source=["../components/aster-strategy2-maker.tsx","../components/aster-strategy2-behavior.tsx"]
  .map(path=>fs.readFileSync(new URL(path,import.meta.url),"utf8")).join("\n");

test("web uses a numeric Aster USDT Top-N field without preset rounding",()=>{
  assert.match(source,/Aster USDT-handelsuniversum – Top-N op volume en liquiditeit/);
  assert.match(source,/min="1" step="1"/);
  assert.doesNotMatch(source,/\["50","100","200"\]/);
  assert.doesNotMatch(source,/universeTopN:Math\.round/);
  assert.match(source,/Gevraagd: \{requested\} · geschikt: \{eligible\} · geselecteerd: \{selected\}/);
  assert.match(source,/Opgehaald: \{stamp\(data\.fetchedAt\)\} · geldig tot: \{stamp\(data\.expiresAt\)\}/);
  assert.match(source,/Data: \{data\.stale===true\?"verouderd":"actueel"\}/);
  assert.ok((source.match(/<AsterUniverseStatus/g)||[]).length>=4);
});

test("Strategy 2 distinguishes bot, entry, management and proven position counts",()=>{
  assert.match(strategy2Source,/unieke markten/);
  assert.match(strategy2Source,/positie-legs/);
  assert.match(strategy2Source,/Alleen bewezen Strategy‑2-ownership/);
  assert.match(strategy2Source,/Nieuwe instappen:/);
  assert.match(strategy2Source,/Bestaande posities:/);
  assert.match(strategy2Source,/position\.strategyId \?\? ""\) === "aster-strategy-2"/);
  assert.doesNotMatch(strategy2Source,/actieve pairs/);
});

test("web contains no removed external universe label",()=>{
  assert.doesNotMatch(source,new RegExp(["coin","market","cap"].join(""),"i"));
  assert.doesNotMatch(source,new RegExp(`\\b${["c","m","c"].join("")}\\b`,"i"));
});
