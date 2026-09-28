import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const v3 = fs.readFileSync(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");

test("Portfolio TP seat reset uses the binding visual reference and is BETA UI only", () => {
  assert.match(v3, /file_00000000369082108949b160b28e0965/);
  assert.match(v3, /Stoelen resetten naar startinstelling/);
  assert.match(v3, /Na behalen doel \(Portfolio TP\)/);
  assert.match(v3, /Wat gebeurt er\?/);
  assert.match(v3, /v3-tp-seat-reset/);
  assert.match(v3, /data-beta-only="true"/);
});

test("seat reset setting round-trips through confirmed settings and the existing PUT", () => {
  assert.match(v3, /resetSeatsAfterPortfolioTp: settings\.resetSeatsAfterPortfolioTp === true/);
  assert.match(v3, /resetSeatsAfterPortfolioTp: source\.resetSeatsAfterPortfolioTp/);
  assert.match(v3, /update\("resetSeatsAfterPortfolioTp",v\)/);
  assert.match(v3, /updateQuick\("resetSeatsAfterPortfolioTp",v\)/);
  assert.match(route, /"resetSeatsAfterPortfolioTp"/);
});

test("UI explains close-confirm-reset order and never presents a manual close action", () => {
  const start = v3.indexOf('<section className="v3-tp-seat-reset"');
  const end = v3.indexOf("</section>", start);
  assert.ok(start >= 0 && end > start);
  const block = v3.slice(start, end);
  assert.match(block, /Eerst alles sluiten en bevestigen\. Daarna pas de stoelreset/);
  assert.match(block, /nieuwe entries geblokkeerd/);
  assert.doesNotMatch(block, /authenticatedRequest/);
  assert.doesNotMatch(block, /closeAll|close\/|POST/);
});

test("mobile styles keep the seat reset flow compact at phone widths", () => {
  assert.match(v3, /\.v3-seat-reset-flow\{display:grid;grid-template-columns:/);
  assert.match(v3, /@media\(max-width:430px\)/);
  assert.match(v3, /@media\(max-width:350px\)/);
});
