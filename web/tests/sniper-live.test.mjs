import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const dashboard = fs.readFileSync(new URL("../components/sniper-dashboard.tsx", import.meta.url), "utf8");
const bridge = fs.readFileSync(new URL("../components/home-navigation-bridge.tsx", import.meta.url), "utf8");
const newsBridge = fs.readFileSync(new URL("../components/news-navigation-bridge.tsx", import.meta.url), "utf8");
const marketsBridge = fs.readFileSync(new URL("../components/markets-navigation-bridge.tsx", import.meta.url), "utf8");
const css = fs.readFileSync(new URL("../app/sniper-bridge.css", import.meta.url), "utf8");
const layout = fs.readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8");
const version = fs.readFileSync(new URL("../lib/app-version.ts", import.meta.url), "utf8");
const release = fs.readFileSync(new URL("../lib/release-history.ts", import.meta.url), "utf8");

test("Sniper is a live main navigation view between Aster and News", () => {
  assert.match(bridge, /ensureSniper/);
  assert.match(bridge, /data-destination="aster"/);
  assert.match(bridge, /data-destination="news"/);
  assert.match(bridge, /<SniperDashboard cloudReady=\{cloudReady\}/);
  assert.match(newsBridge, /"markets", "aster", "sniper", "news", "journey", "wallet"/);
  assert.match(marketsBridge, /"markets", "aster", "sniper", "news", "journey", "wallet"/);
});

test("Sniper dashboard exposes exactly the agreed strategy sections and live activation", () => {
  for (const label of ["Overzicht", "Trades", "Signalen", "Prestaties", "Instellingen"]) {
    assert.match(dashboard, new RegExp(`"${label}"`));
  }
  assert.match(dashboard, /BEVESTIG LIVE SNIPER/);
  assert.match(dashboard, /Sniper gaat echte Aster-orders plaatsen/);
  assert.match(dashboard, /\/api\/exchanges\/aster\/sniper\/start/);
  assert.match(dashboard, /\/api\/exchanges\/aster\/sniper\/stop/);
  assert.doesNotMatch(dashboard, /simulation:\s*true/);
  assert.doesNotMatch(dashboard, /liveLocked\s*=\s*true/);
  assert.match(dashboard, /LIVE CANARY/);
  assert.match(dashboard, /eerste activering voert Sniper eerst automatisch één zeer kleine echte Aster open\/fill\/close-canary uit/);
  assert.match(dashboard, /canaryValidated/);
});

test("Sniper keeps hard live defaults visible and configurable", () => {
  assert.match(dashboard, /maxTradeSeconds:\s*180/);
  assert.match(dashboard, /tpMinPercent:\s*0\.18/);
  assert.match(dashboard, /tpMaxPercent:\s*0\.45/);
  assert.match(dashboard, /maxLossUsd:\s*0\.10/);
  assert.match(dashboard, /maxConcurrent:\s*3/);
  assert.match(dashboard, /Margin \/ trade/);
  assert.match(dashboard, /Leverage/);
});

test("Sniper has all twelve independent checks", () => {
  for (const name of [
    "Bollinger Band locatie","Momentum","Trendfilter","Volume bevestiging","Orderflow","Orderboek",
    "Liquiditeit","Spread check","Volatiliteit","Kosten check","Liquidatiebuffer","Historische edge",
  ]) assert.match(dashboard, new RegExp(name));
});

test("Sniper dashboard only consumes Sniper trade endpoints for management", () => {
  assert.match(dashboard, /\/api\/exchanges\/aster\/sniper/);
  assert.match(dashboard, /\/sniper\/trades\/close/);
  assert.doesNotMatch(dashboard, /\/positions\/close-profitable/);
  assert.doesNotMatch(dashboard, /\/strategy2\/start/);
});

test("mobile Sniper navigation stays compact with seven destinations", () => {
  assert.match(css, /data-destination="sniper"/);
  assert.match(css, /@media\(max-width:760px\)/);
  assert.match(css, /\.bottom-nav \.nav-button small/);
  assert.match(layout, /import "\.\/sniper-bridge\.css"/);
  assert.match(css, /grid-template-columns:repeat\(6,minmax\(0,1fr\)\)/);
});

test("build 382 release history identifies Sniper Live Trading", () => {
  assert.match(version, /WEBAPP_BUILD_NUMBER = "382"/);
  assert.match(release, /title: "SNIPER Live Trading"/);
  assert.match(release, /aavansh-sniper-build372/);
  assert.match(release, /m_6aab179ba6008191b3b874803a1508ab/);
});
