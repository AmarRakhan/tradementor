import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const v3 = fs.readFileSync(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8");
const v2 = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const target = fs.readFileSync(new URL("../components/portfolio-tp-seat-reset-target.tsx", import.meta.url), "utf8");
const shell = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");

test("Portfolio TP seat reset 2.0 is exposed by legacy, STABLE V2 and BETA V3", () => {
  assert.match(v3, /file_00000000369082108949b160b28e0965/);
  assert.match(v3, /PortfolioTpSeatResetTarget/);
  assert.match(v2, /PortfolioTpSeatResetTarget/);
  assert.match(maker, /PortfolioTpSeatResetTarget/);
  assert.match(target, /LONG na reset/);
  assert.match(target, /SHORT na reset/);
  assert.match(target, /Resetwaarden opslaan/);
  assert.match(target, /data-feature="portfolio-tp-seat-reset-target-2"/);
  assert.match(v3, /data-beta-only="true"/);
  assert.match(shell, /release\?\.channel === "BETA"/);
});

test("shared reset target uses one server-side PUT and protected backend fields", () => {
  assert.match(target, /portfolioTpResetLongSlots: longValue/);
  assert.match(target, /portfolioTpResetShortSlots: shortValue/);
  assert.match(target, /\/api\/exchanges\/aster\/strategy2\/settings/);
  assert.match(target, /method: "PUT"/);
  assert.match(route, /"portfolioTpResetLongSlots"/);
  assert.match(route, /"portfolioTpResetShortSlots"/);
  assert.match(route, /"resetSeatsAfterPortfolioTp"/);
  assert.doesNotMatch(target, /localStorage|sessionStorage/);
});

test("saving reset values never calls start stop close or an order endpoint", () => {
  assert.match(target, /Opslaan wijzigt alleen het toekomstige resetdoel/);
  assert.match(target, /pas toegepast na bevestigde flat-state/);
  assert.doesNotMatch(target, /strategy2\/start|strategy2\/stop|closeAll|close\/|method: "POST"|order/i);
});

test("mobile styles keep the seat reset flow compact at phone widths", () => {
  assert.match(target, /\.ptp-reset-flow\{display:grid;grid-template-columns:/);
  assert.match(target, /@media\(max-width:620px\)/);
  assert.match(target, /@media\(max-width:360px\)/);
});
