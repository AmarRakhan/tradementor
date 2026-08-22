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

test("browser presents only Strategy-2 server status without fetching or caching", async () => {
  const [component, parser] = await Promise.all([read("components/aster-bot-status.tsx"), read("lib/aster-bot-status.ts")]);
  assert.match(component, /value\.newEntry\.status/);
  assert.match(component, /value\.strategy2\.ownedPositions/);
  assert.match(component, /value\.remainingToTarget/);
  assert.match(component, /value\.account\.activePositions/);
  assert.match(parser, /STRATEGY2_ONLY/);
  assert.match(parser, /strategyId:"aster-strategy-2"/);
  assert.doesNotMatch(component + parser, /authenticatedRequest|\bfetch\(|localStorage|setInterval|setTimeout|strategy3/i);
});

test("read-only details expose Strategy-2 scheduler, action and reason", async () => {
  const component = await read("components/aster-bot-status.tsx");
  for (const field of ["schedulerStatus", "lastAction", "lastReason", "ownedPositions"]) {
    assert.ok(component.includes(field), `missing ${field}`);
  }
  assert.match(component, /Laatste Strategy-2-controle/);
  assert.match(component, /Laatste Strategy-2-actie/);
  assert.doesNotMatch(component, /authenticatedRequest|\/api\/|onChanged|confirm\s*:|type="submit"|strategy3/i);
});

test("status view has no additional polling path", async () => {
  const [component, exchangeData] = await Promise.all([read("components/aster-bot-status.tsx"), read("lib/use-exchange-data.ts")]);
  assert.doesNotMatch(component, /setInterval|refresh|retry/i);
  assert.match(exchangeData, /}, 60_000\);/);
});


test("Aster capacity zero is shown as waiting instead of falsely claiming active refill", async () => {
  const parser = await read("lib/aster-bot-status.ts");
  assert.match(parser, /openableCapacityBlocked/);
  assert.match(parser, /ASTER_OPENABLE_CAPACITY_WAIT/);
  assert.match(parser, /automatische hercheck blijft aan/);
});
