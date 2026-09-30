import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const v2 = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const v3 = fs.readFileSync(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8");
const target = fs.readFileSync(new URL("../components/portfolio-tp-seat-reset-target.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const entry = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const version = fs.readFileSync(new URL("../lib/app-version.ts", import.meta.url), "utf8");

test("Build 478 keeps the Portfolio TP seat reset control in existing STABLE V2", () => {
  assert.match(version, /WEBAPP_BUILD_NUMBER = "478"/);
  assert.match(v2, /data-feature="portfolio-tp-seat-reset"/);
  assert.match(v2, /Stoelen resetten na Portfolio TP/);
  assert.match(v2, /resetSeatsAfterPortfolioTp: settings\.resetSeatsAfterPortfolioTp === true/);
  assert.match(v2, /resetSeatsAfterPortfolioTp: draft\.resetSeatsAfterPortfolioTp/);
  assert.match(v2, /hasPersistedResetTarget/);
  assert.match(v2, /portfolioTpResetLongSlots/);
  assert.match(v2, /portfolioTpResetShortSlots/);
  assert.match(v2, /PortfolioTpSeatResetTarget/);
});

test("V2 control is only shown inside Portfolio TP mode and uses the existing settings PUT", () => {
  const winstStart = v2.indexOf('id="v2-step-winst"');
  const protectionStart = v2.indexOf('id="v2-step-bescherming"');
  const winst = v2.slice(winstStart, protectionStart);
  assert.match(winst, /draft\.tpMode === "PORTFOLIO"/);
  assert.match(winst, /Stoelen resetten na Portfolio TP/);
  assert.match(target, /\/api\/exchanges\/aster\/strategy2\/settings/);
  assert.match(target, /method: "PUT"/);
  assert.match(target, /Resetwaarden opslaan/);
  assert.doesNotMatch(winst, /strategy2\/start|strategy2\/stop|closeAll|POST/);
});

test("existing STABLE V2 routing remains intact and users are not migrated to V3", () => {
  assert.match(entry, /release\?\.channel === "BETA"/);
  assert.match(entry, /BetaConfiguratorV3/);
  assert.match(entry, /BetaConfiguratorV2/);
  assert.match(entry, /betaV3Enabled[\s\S]*\? <BetaConfiguratorV3[\s\S]*: <BetaConfiguratorV2/);
});

test("the persisted setting remains protected from older editors", () => {
  assert.match(route, /"resetSeatsAfterPortfolioTp"/);
  assert.match(route, /"portfolioTpResetLongSlots"/);
  assert.match(route, /"portfolioTpResetShortSlots"/);
  assert.match(v3, /PortfolioTpSeatResetTarget/);
  assert.match(v2, /PortfolioTpSeatResetTarget/);
});
