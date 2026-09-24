import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("Home is first and Sniper is inserted without removing Markets, News or existing tabs", async () => {
  const [home, markets, news, page] = await Promise.all([
    read("components/home-navigation-bridge.tsx"), read("components/markets-navigation-bridge.tsx"),
    read("components/news-navigation-bridge.tsx"), read("app/page.tsx"),
  ]);
  assert.ok(home.includes("nav.insertBefore(home, first || null)"));
  assert.ok(home.includes("nav.insertBefore(home, first || null)"));
  assert.match(home, /data-destination="aster"/);
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


test("Build 414 cold-starts directly on ASTER without synthesizing a HOME portal first", async () => {
  const [bridge, page, manifestRaw] = await Promise.all([
    read("components/home-navigation-bridge.tsx"),
    read("app/page.tsx"),
    read("public/manifest.webmanifest"),
  ]);
  const manifest = JSON.parse(manifestRaw);
  assert.equal(manifest.start_url, "/?source=pwa&appVersion=46#/aster");
  assert.match(page, /useState<Destination>\("aster"\)/);
  assert.match(page, /let initial: Destination = route \|\| "aster"/);
  assert.match(page, /window\.scrollTo\(\{ top: 0, left: 0, behavior: "auto" \}\)/);
  assert.match(bridge, /launchUrl\.hash = "\/aster"/);
  assert.doesNotMatch(bridge, /tmView: "home" \}, "", urlWithView\("home"\)/);
});
