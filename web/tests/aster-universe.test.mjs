import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const files=[
  "../components/aster-strategy2-maker.tsx",
  "../components/hyperliquid-strategy-control.tsx",
  "../components/aster-universe-status.tsx",
  "../components/aster-performance-panel.tsx",
  "../components/aster-strategy2-behavior.tsx",
].map(path=>fs.readFileSync(new URL(path,import.meta.url),"utf8"));
const source=files.join("\n");
const strategy2Source=["../components/aster-strategy2-maker.tsx","../components/aster-strategy2-behavior.tsx"]
  .map(path=>fs.readFileSync(new URL(path,import.meta.url),"utf8")).join("\n");

test("web uses a numeric Aster USDT Top-N field without preset rounding",()=>{
  assert.match(source,/Aster USDT-handelsuniversum – Top-N op volume en liquiditeit/);
  assert.match(source,/min="1" step="1"/);
  assert.doesNotMatch(source,/\["50","100","200"\]/);
  assert.doesNotMatch(source,/universeTopN:Math\.round/);
  assert.match(source,/Top‑N op Aster 24-uurs USDT-handelsvolume, na liquiditeits- en veiligheidsfilters/);
  assert.match(source,/gevraagd: \{requested\} · geschikt: \{eligible\} · geselecteerd: \{selected\}/);
  assert.match(source,/Opgehaald: \{stamp\(data\.fetchedAt\)\} · geldig tot: \{stamp\(data\.expiresAt\)\}/);
  assert.match(source,/Data: \{data\.stale===true\?"verouderd":"actueel"\}/);
  assert.ok((source.match(/<AsterUniverseStatus/g)||[]).length>=2);
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

test("web never claims Aster position management is confirmed during stale exchange data",()=>{
  const page=fs.readFileSync(new URL("../app/page.tsx",import.meta.url),"utf8");
  assert.match(page,/Aster-uitvoering niet bevestigd/);
  assert.match(page,/actuele uitvoering kon door Aster niet worden bevestigd/);
  assert.doesNotMatch(page,/Sluiten en exchange-side bescherming blijven afzonderlijk beschikbaar/);
});

test("web contains no removed external universe label",()=>{
  assert.doesNotMatch(source,new RegExp(["coin","market","cap"].join(""),"i"));
  assert.doesNotMatch(source,new RegExp(`\\b${["c","m","c"].join("")}\\b`,"i"));
});
