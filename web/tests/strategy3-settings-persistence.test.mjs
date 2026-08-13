import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const route = await readFile(new URL("../app/api/exchanges/aster/strategy3/settings/route.ts", import.meta.url), "utf8");
const control = await readFile(new URL("../components/aster-strategy3-control.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("Strategy 3 settings use authoritative cloud persistence", () => {
  assert.match(route, /proxyCloud/);
  assert.match(route, /\/v1\/me\/aster\/strategy3\/settings/);
  assert.doesNotMatch(route, /validateStrategy3Paper|saved\s*:\s*true/);
});

test("Strategy 3 save verifies the server-confirmed effective values", () => {
  assert.match(control, /saved\.baseNotional/);
  assert.match(control, /saved\.trailingEnabled/);
  assert.match(control, /De server bevestigde niet dezelfde Strategy-3-instellingen/);
});

test("narrow recent trade rows cannot widen the mobile page", () => {
  assert.match(css, /@media\(max-width:430px\)[\s\S]*?recent-trade-row\{grid-template-columns:minmax\(0,1fr\) auto repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(css, /recent-trades-card,[^}]*max-width:100%/);
});