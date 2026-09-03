import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const component = fs.readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const css = fs.readFileSync(new URL("../components/aster-profit-close.module.css", import.meta.url), "utf8");
const previewProxy = fs.readFileSync(new URL("../app/api/exchanges/aster/positions/profitable-close-preview/route.ts", import.meta.url), "utf8");
const closeProxy = fs.readFileSync(new URL("../app/api/exchanges/aster/positions/close-profitable/route.ts", import.meta.url), "utf8");

test("bulk profit action preserves existing Tradecentrum controls", () => {
  assert.match(component, /Toon alles/);
  assert.match(component, /ClosePositionControl/);
  assert.match(component, /Close \$\{profitCandidates\.length\} profits/);
  assert.doesNotMatch(component, /netto\s*[≥>]/i);
});

test("bulk profit action refreshes preview, confirms, and posts once while disabled", () => {
  assert.match(component, /profitable-close-preview/);
  assert.match(component, /close-profitable/);
  assert.match(component, /profitBusy \|\|/);
  assert.match(component, /crypto\.randomUUID\(\)/);
  assert.match(component, /createPortal/);
  assert.match(component, /Zowel LONG- als SHORT-posities/);
  assert.match(component, /Geen profits om te sluiten/);
});

test("mobile footer keeps a compact single-line green action", () => {
  assert.match(css, /\.closeProfits/);
  assert.match(css, /white-space:\s*nowrap/);
  assert.match(css, /overflow:\s*hidden/);
  assert.match(css, /@media\s*\(max-width:\s*420px\)/);
  assert.match(css, /#58f0ae/);
});

test("Next proxies use the UID-authenticated cloud routes", () => {
  assert.match(previewProxy, /\/v1\/me\/aster\/positions\/profitable-close-preview/);
  assert.match(closeProxy, /\/v1\/me\/aster\/positions\/close-profitable/);
});
