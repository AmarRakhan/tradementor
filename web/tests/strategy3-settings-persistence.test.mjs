import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const route = await readFile(new URL("../app/api/exchanges/aster/strategy3/settings/route.ts", import.meta.url), "utf8");
const control = await readFile(new URL("../components/aster-strategy3-control.tsx", import.meta.url), "utf8");
const cloud = await readFile(new URL("../cloud_api/main.py", import.meta.url), "utf8");
const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("Strategy 3 settings use authoritative cloud persistence", () => {
  assert.match(route, /proxyStrategy3Live/);
  assert.doesNotMatch(route, /proxyCloud|proxyCandidate/);
  assert.match(route, /\/v1\/me\/aster\/strategy3\/settings/);
  assert.doesNotMatch(route, /validateStrategy3Paper|saved\s*:\s*true/);
});

test("Strategy 3 save verifies the server-confirmed effective values", () => {
  assert.match(control, /saved\.baseNotional/);
  assert.match(control, /saved\.trailingEnabled/);
  assert.match(control, /De server bevestigde niet dezelfde Strategy-3-instellingen/);
});

test("saving while stopped preserves a proven account canary and fresh readiness can safely re-arm live", () => {
  assert.match(cloud, /account_authorized=bool\(existing\.get\("canaryValidated"\)\) and bool\(existing\.get\("liveAccountAuthorized"\)\)/);
  assert.match(cloud, /live_ready=bool\(existing\.get\("liveReady"\)\) and account_authorized/);
  assert.match(cloud, /"paperOnly":not account_authorized/);
  assert.match(cloud, /revalidated=account_authorized and bool\(report\.get\("liveReady"\)\)/);
  assert.match(cloud, /"liveReady":revalidated/);
  assert.doesNotMatch(cloud, /Read-only readiness uitgevoerd; live en canary blijven geblokkeerd/);
});

test("Strategy 3 live confirmation uses the saved draft including trailing off", () => {
  assert.match(control, /confirmedSettings=payload\("live"\)/);
  assert.match(control, /Protected Trailing \{draft\.trailing/);
  assert.doesNotMatch(control, /buildPayload\(defaults,"live"\)/);
  assert.doesNotMatch(control, /setDraft\(\{\.\.\.defaults\}\)/);
});

test("narrow recent trade rows cannot widen the mobile page", () => {
  assert.match(css, /@media\(max-width:430px\)[\s\S]*?recent-trade-row\{grid-template-columns:minmax\(105px,1\.45fr\) repeat\(3,minmax\(43px,\.7fr\)\)/);
  assert.match(css, /recent-trades-card,[^}]*max-width:100%/);
});
