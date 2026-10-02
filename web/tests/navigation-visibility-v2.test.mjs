import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("navigation visibility v2 keeps HOME, ASTER and WALLET fixed while optional tabs are independently configurable", async () => {
  const [page, preferences, home, markets, news, friends, proxy, backend, version] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/navigation-preferences.ts", import.meta.url), "utf8"),
    readFile(new URL("../components/home-navigation-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/markets-navigation-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/news-navigation-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/friends-navigation-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/preferences/navigation/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../../cloud_api/main.py", import.meta.url), "utf8"),
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
  ]);

  assert.match(version, /WEBAPP_BUILD_NUMBER = "487"/);

  for (const key of ["hyperliquid", "markets", "sniper", "news", "friends", "journey"]) {
    assert.match(preferences, new RegExp(`${key}: true`));
  }
  assert.match(preferences, /destination === "home" \|\| destination === "aster" \|\| destination === "wallet"/);
  assert.match(preferences, /tradementor\.navigation\.visible\.v2\./);
  assert.match(preferences, /tradementor:navigation-visibility-change/);

  for (const label of [
    "Hyperliquid-tab tonen",
    "Markets-tab tonen",
    "Sniper-tab tonen",
    "Nieuws-tab tonen",
    "Friends-tab tonen",
    "Journey-tab tonen",
  ]) {
    assert.match(page, new RegExp(label));
  }
  assert.doesNotMatch(page, /ASTER-tab tonen/);
  assert.match(page, /Dit verandert alleen welke tabbladen je onderin ziet/);
  assert.match(page, /navigationPreferences\.hyperliquid/);
  assert.match(page, /navigationPreferences\.journey/);
  assert.match(page, /saveNavigationPreferences\(user\?\.uid, next\)/);
  assert.match(page, /\/api\/preferences\/navigation/);

  for (const bridge of [home, markets, news, friends]) {
    assert.match(bridge, /MOBILE_NAVIGATION_ORDER/);
    assert.match(bridge, /mobileNavigationDestinationVisible/);
    assert.match(bridge, /NAVIGATION_PREFERENCES_EVENT/);
  }

  assert.match(proxy, /\/v1\/me\/preferences\/navigation/);
  assert.match(backend, /class NavigationPreferenceRequest\(BaseModel\)/);
  assert.match(backend, /@app\.get\("\/v1\/me\/preferences\/navigation"\)/);
  assert.match(backend, /@app\.put\("\/v1\/me\/preferences\/navigation"\)/);
  assert.match(backend, /document\("navigation"\)/);
  assert.match(backend, /isinstance\(raw\.get\(field\), bool\) else True/);
});

test("navigation v2 only filters the mobile bottom nav; desktop rail remains available", async () => {
  const [page, home, markets, news, friends] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/home-navigation-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/markets-navigation-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/news-navigation-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/friends-navigation-bridge.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(page, /railDestinations\.map/);
  assert.match(page, /visibleDestinations\.map/);
  assert.match(home, /nav\.classList\.contains\("bottom-nav"\)/);
  for (const bridge of [markets, news, friends]) {
    assert.match(bridge, /document\.querySelectorAll<HTMLElement>\("\.bottom-nav"\)/);
    assert.match(bridge, /document\.querySelectorAll<HTMLElement>\("\.rail-nav"\)/);
  }
});