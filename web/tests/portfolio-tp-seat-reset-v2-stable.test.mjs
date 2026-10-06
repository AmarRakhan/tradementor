import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const v2 = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const v3 = fs.readFileSync(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8");
const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const target = fs.readFileSync(new URL("../components/portfolio-tp-seat-reset-target.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const entry = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");

test("Portfolio TP seat reset remains available in the live classic AsterBot settings", () => {
  assert.match(entry, /AsterStrategy2Maker/);
  assert.match(maker, /PortfolioTpSeatResetTarget/);
  assert.match(maker, /resetSeatsAfterPortfolioTp/);
  assert.match(maker, /portfolioTpResetLongSlots/);
  assert.match(maker, /portfolioTpResetShortSlots/);
});

test("shared reset target still uses only the existing settings PUT", () => {
  assert.match(target, /\/api\/exchanges\/aster\/strategy2\/settings/);
  assert.match(target, /method: "PUT"/);
  assert.match(target, /Resetwaarden opslaan/);
  assert.doesNotMatch(target, /strategy2\/start|strategy2\/stop|closeAll|method: "POST"/i);
});

test("retained V2 and V3 source keep reset compatibility without being live-routed", () => {
  assert.match(v2, /PortfolioTpSeatResetTarget/);
  assert.match(v3, /PortfolioTpSeatResetTarget/);
  assert.doesNotMatch(entry, /ConfiguratorV3|BotSettingsMode/);
});

test("protected reset fields remain in the settings route", () => {
  assert.match(route, /"resetSeatsAfterPortfolioTp"/);
  assert.match(route, /"portfolioTpResetLongSlots"/);
  assert.match(route, /"portfolioTpResetShortSlots"/);
});
