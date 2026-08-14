import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("Aster hero uses only the server bot-status component and preserves the maintenance orbit", async () => {
  const page = await read("app/page.tsx");
  assert.match(page, /destination === "aster" \? <AsterBotStatus snapshot=\{snapshot\.data\} \/>/);
  assert.match(page, /<div className=\{`risk-orbit risk-\$\{view\.riskTone\}`\}/);
  assert.match(page, /<strong>\{view\.riskValue\}<\/strong>/);
  const component = await read("components/aster-bot-status.tsx");
  assert.doesNotMatch(component, /onRefresh|refresh-chip|Live handel|Exchange verbonden/);
});

test("browser parses and presents the server decision without fetching, caching, or deriving permission", async () => {
  const [component, parser] = await Promise.all([read("components/aster-bot-status.tsx"), read("lib/aster-bot-status.ts")]);
  assert.match(component, /value\.newEntry\.status/);
  assert.match(component, /value\.strategy3\.remainingAccountCapacity/);
  assert.match(component, /value\.account\.activePositions/);
  assert.match(parser, /source\.botStatusDashboard/);
  assert.match(parser, /browserDerived !== false/);
  assert.doesNotMatch(component + parser, /authenticatedRequest|\bfetch\(|localStorage|setInterval|setTimeout/);
  assert.doesNotMatch(component, /maximumPositions\s*-|activePositions\s*[<>]=?|marginRatio\s*[<>]=?|liveReady\s*&&/);
});

test("read-only details expose gates, ownership, scheduler, action, reason, and every server check", async () => {
  const component = await read("components/aster-bot-status.tsx");
  for (const field of ["liveGates", "ownershipStatus", "schedulerStatus", "lastAction", "lastReason", "newEntry.checks", "newEntry.activeBlocks"]) {
    assert.ok(component.includes(field), `missing ${field}`);
  }
  assert.doesNotMatch(component, /authenticatedRequest|\/api\/|onChanged|confirm\s*:|type="submit"|start-live|strategy3\/stop/i);
});

test("status view has no additional polling path", async () => {
  const [component, exchangeData] = await Promise.all([read("components/aster-bot-status.tsx"), read("lib/use-exchange-data.ts")]);
  assert.doesNotMatch(component, /setInterval|refresh|retry/i);
  assert.match(exchangeData, /}, 60_000\);/);
});
