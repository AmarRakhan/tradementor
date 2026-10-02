import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Build 482 makes both Snapshot performance cards open the Rendement Overzicht", async () => {
  const [snapshot, detail, css, route, version] = await Promise.all([
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/portfolio-performance-detail.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/portfolio-growth/daily-detail/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
  ]);

  assert.match(snapshot, /onOpenPerformance\("per-day"\)/);
  assert.match(snapshot, /onOpenPerformance\("average"\)/);
  assert.match(snapshot, /PortfolioPerformanceDetail/);
  assert.match(detail, /Per dag/);
  assert.match(detail, /Analyse/);
  assert.match(detail, /Gemiddeld/);
  assert.match(detail, /Uitleg/);
  assert.match(detail, /portfolio-growth\/daily/);
  assert.match(detail, /portfolio-chart\?timeframe=5m/);
  assert.match(detail, /cashflowAdjustedPortfolioSeries/);
  assert.match(route, /portfolio-growth\/daily-detail/);
  assert.match(css, /aps-performance-flip-in/);
  assert.match(css, /aps-performance-flip-out/);
  assert.match(version, /WEBAPP_BUILD_NUMBER = "485"/);
});

test("Build 482 explains residual equity honestly instead of inventing historical unrealized PnL", async () => {
  const detail = await readFile(new URL("../components/portfolio-performance-detail.tsx", import.meta.url), "utf8");
  assert.match(detail, /equityResidualReliableAsUnrealizedPnl/);
  assert.match(detail, /equity-rest/);
  assert.match(detail, /niet als zuivere unrealized PnL te bewijzen/);
  assert.doesNotMatch(detail, /hardcoded-demo|\+4,18%|-1,14%/);
});