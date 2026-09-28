import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("profit notifications are wired between release history and version without a new home card", async () => {
  const [layout, component, css] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/profit-notifications.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/profit-notifications.css", import.meta.url), "utf8"),
  ]);
  const release = layout.indexOf("<ReleaseHistoryControl />");
  const bell = layout.indexOf("<ProfitNotificationControl />");
  const version = layout.indexOf("<AppVersionControl />");
  assert.ok(release >= 0 && bell > release && version > bell);
  assert.match(layout, /<ProfitNotificationPanel \/>/);
  assert.match(layout, /<ProfitCelebration \/>/);
  assert.match(component, /aria-label="Pushmeldingen beheren"/);
  assert.doesNotMatch(layout, /Pushmeldingen beheren<\/section>/);
  assert.match(css, /\.profit-notification-header-button\{[^}]*width:28px/);
  assert.match(css, /\.profit-notification-overlay\{position:fixed;z-index:99998;inset:28px 0 0/);
});

test("settings UI includes the complete approved notification policy", async () => {
  const source = await readFile(new URL("../components/profit-notifications.tsx", import.meta.url), "utf8");
  for (const label of [
    "Iedere",
    "Samenvatting",
    "15 min",
    "30 min",
    "60 min",
    "Nieuwe LONG-posities",
    "Nieuwe SHORT-posities",
    "Alleen winsttrades",
    "Portfolio Take Profit behaald",
    "Portfolio &amp; Available realtime verversen bij verzenden",
    "Minimum winst",
    "Voorbeeld melding",
    "Opslaan",
    "Testmelding versturen",
  ]) assert.ok(source.includes(label), "missing " + label);

  assert.match(source, /Notification\.requestPermission\(\)/);
  assert.match(source, /pushManager\.subscribe/);
  assert.match(source, /applicationServerKey/);
  assert.match(source, /activeSubscriptions/);
  assert.match(source, /iPhone werkt Web Push.*Zet op beginscherm/);
  assert.match(source, /notification_test|Testmelding/);
});

test("LONG and SHORT entry switches are independent, opt-in and persist through the settings API", async () => {
  const source = await readFile(new URL("../components/profit-notifications.tsx", import.meta.url), "utf8");
  assert.match(source, /longEntryNotificationsEnabled: boolean/);
  assert.match(source, /shortEntryNotificationsEnabled: boolean/);
  assert.match(source, /longEntryNotificationsEnabled: false/);
  assert.match(source, /shortEntryNotificationsEnabled: false/);
  assert.match(source, /longEntryNotificationsEnabled: settings\.longEntryNotificationsEnabled/);
  assert.match(source, /shortEntryNotificationsEnabled: settings\.shortEntryNotificationsEnabled/);

  const modeIndex = source.indexOf('className="profit-setting-block mode"');
  const longIndex = source.indexOf(">Nieuwe LONG-posities<");
  const shortIndex = source.indexOf(">Nieuwe SHORT-posities<");
  const winsIndex = source.indexOf(">Alleen winsttrades");
  assert.ok(modeIndex >= 0 && longIndex > modeIndex && shortIndex > longIndex && winsIndex > shortIndex);
  assert.match(source, /label="Nieuwe LONG-posities"/);
  assert.match(source, /label="Nieuwe SHORT-posities"/);
});


test("native push is delivered by the service worker and notification click deep-links back to the app", async () => {
  const sw = await readFile(new URL("../public/sw.js", import.meta.url), "utf8");
  assert.match(sw, /addEventListener\("push"/);
  assert.match(sw, /showNotification/);
  assert.match(sw, /payload\.body/);
  assert.match(sw, /payload\.tag/);
  assert.match(sw, /addEventListener\("notificationclick"/);
  assert.match(sw, /clients\.matchAll/);
  assert.match(sw, /clients\.openWindow/);
});

test("notification API proxies remain authenticated and include settings, subscription, test and recent feeds", async () => {
  const paths = [
    "../app/api/notifications/settings/route.ts",
    "../app/api/notifications/public-key/route.ts",
    "../app/api/notifications/subscriptions/route.ts",
    "../app/api/notifications/test/route.ts",
    "../app/api/notifications/recent/route.ts",
  ];
  const values = await Promise.all(paths.map((path) => readFile(new URL(path, import.meta.url), "utf8")));
  for (const value of values) assert.match(value, /proxyCloud/);
  assert.match(values[0], /\/v1\/me\/notifications\/settings/);
  assert.match(values[2], /\/v1\/me\/notifications\/subscriptions/);
  assert.match(values[3], /\/v1\/me\/notifications\/test/);
  assert.match(values[4], /after_ms/);
});

test("approved visual references are recorded in the canonical release history", async () => {
  const history = await readFile(new URL("../lib/release-history.ts", import.meta.url), "utf8");
  for (const id of [
    "file_00000000b8ec81f4b0a248b4dc06c234",
    "file_00000000909882108ab7517ab276779f",
    "file_000000008dd082469c173c928eaa3c1a",
    "file_00000000d6a88210b0f99525e33d570c",
    "file_00000000ebcc8243924098b6858456ae",
    "file_00000000cd448210b066edf7a499973e",
  ]) assert.ok(history.includes(id), "missing visual reference " + id);
});


test("test push can safely repair a stale device subscription exactly once", async () => {
  const source = await readFile(new URL("../components/profit-notifications.tsx", import.meta.url), "utf8");
  assert.match(source, /ensureDeviceSubscription\(forceRenew = false\)/);
  assert.match(source, /subscription\.unsubscribe\(\)/);
  assert.match(source, /subscriptions\/remove/);
  assert.match(source, /PUSH_SUBSCRIPTION_EXPIRED\|PUSH_PROVIDER_AUTH_REJECTED/);
  assert.match(source, /await ensureDeviceSubscription\(true\)/);
  assert.match(source, /automatisch hersteld/);
});


test("native push content does not include the Amar Crypto Bot brand text", async () => {
  const [component, sw] = await Promise.all([
    readFile(new URL("../components/profit-notifications.tsx", import.meta.url), "utf8"),
    readFile(new URL("../public/sw.js", import.meta.url), "utf8"),
  ]);
  const preview = component.slice(component.indexOf('<section className="profit-preview">'), component.indexOf('{message &&'));
  assert.doesNotMatch(preview, /Amar Crypto Bot 2026/);
  assert.doesNotMatch(sw, /title:\s*"Amar Crypto Bot 2026"/);
  assert.doesNotMatch(sw, /payload\.title \|\| "Amar Crypto Bot 2026"/);
});
