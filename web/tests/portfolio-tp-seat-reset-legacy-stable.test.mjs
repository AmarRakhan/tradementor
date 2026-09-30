import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const target = fs.readFileSync(new URL("../components/portfolio-tp-seat-reset-target.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const version = fs.readFileSync(new URL("../lib/app-version.ts", import.meta.url), "utf8");

test("Build 472 preserves Portfolio TP seat reset in the legacy STABLE maker", () => {
  assert.match(version, /WEBAPP_BUILD_NUMBER = "478"/);
  assert.match(maker, /data-feature="portfolio-tp-seat-reset"/);
  assert.match(maker, /Stoelen automatisch resetten/);
  assert.match(maker, /resetSeatsAfterPortfolioTp: x\.resetSeatsAfterPortfolioTp === true/);
  assert.match(maker, /resetSeatsAfterPortfolioTp: v\.resetSeatsAfterPortfolioTp/);
});

test("legacy maker uses explicit reset targets with cycle-start as migration fallback", () => {
  assert.match(maker, /hasPersistedResetTarget/);
  assert.match(maker, /portfolioTpResetLongSlots/);
  assert.match(maker, /portfolioTpResetShortSlots/);
  assert.match(maker, /legacyFallback=\{!hasPersistedResetTarget\}/);
  assert.match(maker, /PortfolioTpSeatResetTarget/);
  assert.match(target, /Reset naar/);
  assert.match(target, /Resetwaarden opslaan/);
});

test("legacy reset target save is order-free and uses only the settings PUT", () => {
  assert.match(target, /method: "PUT"/);
  assert.doesNotMatch(target, /strategy2\/start|strategy2\/stop|closeAll|method: "POST"|localStorage/);
  assert.match(route, /"resetSeatsAfterPortfolioTp"/);
  assert.match(route, /"portfolioTpResetLongSlots"/);
  assert.match(route, /"portfolioTpResetShortSlots"/);
});
