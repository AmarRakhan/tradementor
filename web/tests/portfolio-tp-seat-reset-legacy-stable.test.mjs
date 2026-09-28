import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const version = fs.readFileSync(new URL("../lib/app-version.ts", import.meta.url), "utf8");

test("Build 462 exposes Portfolio TP seat reset in the legacy STABLE maker", () => {
  assert.match(version, /WEBAPP_BUILD_NUMBER = "462"/);
  assert.match(maker, /data-feature="portfolio-tp-seat-reset"/);
  assert.match(maker, /Stoelen automatisch resetten/);
  assert.match(maker, /resetSeatsAfterPortfolioTp: x\.resetSeatsAfterPortfolioTp === true/);
  assert.match(maker, /resetSeatsAfterPortfolioTp: v\.resetSeatsAfterPortfolioTp/);
});

test("legacy maker displays immutable cycle-start reset target", () => {
  assert.match(maker, /cycleStartLongSlots/);
  assert.match(maker, /cycleStartShortSlots/);
  assert.match(maker, /Reset naar/);
  assert.match(maker, /Portfolio TP[\s\S]*Alles dicht/);
});

test("legacy maker reset control does not submit orders or close positions directly", () => {
  const start = maker.indexOf('<section className="portfolio-seat-reset"');
  const end = maker.indexOf("</section>", start);
  assert.ok(start >= 0 && end > start);
  const block = maker.slice(start, end);
  assert.doesNotMatch(block, /authenticatedRequest|strategy2\/start|strategy2\/stop|closeAll|POST/);
  assert.match(route, /"resetSeatsAfterPortfolioTp"/);
});
