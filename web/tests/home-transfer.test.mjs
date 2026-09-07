import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("Home is the first mobile tab without removing Markets, News or existing tabs", async () => {
  const [home, markets, news, page] = await Promise.all([
    read("components/home-navigation-bridge.tsx"), read("components/markets-navigation-bridge.tsx"),
    read("components/news-navigation-bridge.tsx"), read("app/page.tsx"),
  ]);
  assert.match(home, /insertBefore\(button, first \|\| null\)/);
  assert.match(markets, /NAV_DESTINATIONS = \["home", \.\.\.MOBILE_DESTINATIONS\]/);
  assert.match(news, /NAV_DESTINATIONS = \["home", \.\.\.MOBILE_DESTINATIONS\]/);
  assert.match(page, /<HomeNavigationBridge \/><TradeMentorHome \/>/);
});

test("Overboeken keeps MetaMask signing user-controlled and resumable", async () => {
  const [flow, proxy, signPage] = await Promise.all([
    read("components/home-transfer-page.tsx"), read("lib/cloud-proxy.ts"), read("app/sign-withdrawal/page.tsx"),
  ]);
  assert.match(flow, /eth_signTypedData_v4/);
  assert.match(flow, /signing-session/);
  assert.match(flow, /ACTIVE_INTENT_KEY/);
  assert.match(proxy, /proxyCloudPublic/);
  assert.match(signPage, /MetaMask bevestiging/);
});
