import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("every legacy destination has a direct route and browser history entry", async () => {
  const page = await read("app/page.tsx");
  assert.match(page, /destinationIds = new Set<Destination>\(\["hyperliquid", "aster", "journey", "positions", "risk", "wallet", "admin"\]\)/);
  assert.match(page, /window\.history\.pushState\(\{ destination \}, "", destinationHref\(destination\)\)/);
  assert.match(page, /if \(route !== initial\) window\.history\.replaceState\(\{ destination: initial \}, "", destinationHref\(initial\)\)/);
  assert.match(page, /window\.addEventListener\("popstate", restoreDestination\)/);
  assert.match(page, /window\.addEventListener\("hashchange", restoreDestination\)/);
  assert.doesNotMatch(page, /destination === "positions" \? "#\/positions"/);
});

test("session labels cannot claim that personal live exchange data is connected", async () => {
  const [page, layout] = await Promise.all([read("app/page.tsx"), read("app/layout.tsx")]);
  assert.doesNotMatch(page, /LIVE DATA VERBONDEN/);
  assert.doesNotMatch(page, />LIVE DATA</);
  assert.match(page, /CLOUDSESSIE ACTIEF/);
  assert.match(layout, /DIT IS NIET JOUW ACCOUNTSTATUS/);
});

test("missing account evidence renders unknown values instead of financial zeroes", async () => {
  const page = await read("app/page.tsx");
  assert.match(page, /view\.accountDataAvailable \? String\(view\.positions\.length \|\| view\.activeCount\) : "—"/);
  assert.match(page, /value=\{view\.accountDataAvailable \? netOpenPnl : null\}/);
  assert.match(page, /totalEquity === null \? "Geen betrouwbare waarde" : formatUsd\(totalEquity\)/);
  assert.match(page, /runningBots === null \? "—" : String\(runningBots\)/);
  assert.match(page, /!known \? "Onbekend" : active \? "Actief" : "Gestopt"/);
});
