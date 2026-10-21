import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const component = fs.readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const css = fs.readFileSync(new URL("../components/aster-profit-close.module.css", import.meta.url), "utf8");
const previewProxy = fs.readFileSync(new URL("../app/api/exchanges/aster/positions/profitable-close-preview/route.ts", import.meta.url), "utf8");
const closeProxy = fs.readFileSync(new URL("../app/api/exchanges/aster/positions/close-profitable/route.ts", import.meta.url), "utf8");

test("bulk profit action preserves existing Tradecentrum controls", () => {
  assert.match(component, /Toon alles/);
  assert.match(component, /PositionClosePanel/);
  assert.match(component, /LONG: profitCandidates\.filter/);
  assert.match(component, /SHORT: profitCandidates\.filter/);
  assert.match(component, /Close \$\{shortProfitCandidates\.length\} SHORT profits/);
  assert.doesNotMatch(component, /netto\s*[≥>]/i);
});

test("SHORT-only bulk sends the confirmed positions as ONE server round (2.1); the server uses the individual CLOSE", () => {
  assert.match(component, /return \(side === "LONG" \|\| side === "SHORT"\) && pnl !== null && pnl >= 0\.5/);
  assert.match(component, /const shortProfitCandidates = useMemo/);
  assert.match(component, /String\(position\.side \|\| ""\)\.toUpperCase\(\) === "SHORT" && \(finite\(position\.unrealizedPnl\) \|\| 0\) > 0\.5/);
  assert.match(component, /manual-profit-close-plan/);
  assert.match(component, /await authenticatedRequest\(/);
  assert.match(component, /"\/api\/exchanges\/aster\/profit-close-rounds"/);
  assert.match(component, /targets: bulkCloseTargets\.map\(\(target\) => \(\{ symbol: target\.symbol, side: "SHORT", quantity: target\.quantity \}\)\)/);
  assert.match(component, /percentage: profitClosePercentage, idempotency_key: newCloseIdempotencyKey\(\)/);
  assert.match(component, /bulkCloseInFlightRef\.current/);
  assert.match(component, /createPortal/);
  assert.match(component, /break;/);
  assert.match(component, /Geen SHORT profits om te sluiten/);
  assert.match(component, /Hervat ronde · \$\{activeProfitRound\.counts\.remaining\} resterend/);
  assert.match(component, /Ronde afsluiten/);
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

test("every profitable close reaches Cloud with one explicit ALL LONG or SHORT scope", () => {
  assert.match(closeProxy, /new URL\(request\.url\)/);
  assert.match(closeProxy, /searchParams\.get\("side"\)\s*\?\?\s*"ALL"/);
  assert.match(closeProxy, /VALID_SCOPES\.has\(scope\)/);
  assert.match(closeProxy, /LONG/);
  assert.match(closeProxy, /SHORT/);
  assert.match(closeProxy, /\?side=\$\{encodeURIComponent\(scope\)\}/);
  assert.doesNotMatch(closeProxy, /proxyCloud\(request,\s*CLOUD_PATH,\s*"POST"\)/);
});
