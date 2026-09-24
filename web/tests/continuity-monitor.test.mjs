import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("continuity monitor is beta-owner gated before any new provider call", async () => {
  const [auth, bridge, home] = await Promise.all([
    read("components/auth-provider.tsx"),
    read("components/home-navigation-bridge.tsx"),
    read("components/home-transfer-page.tsx"),
  ]);
  assert.match(auth, /betaOwner: boolean/);
  assert.match(auth, /setBetaOwner\(Boolean\(bootstrapPayload\.betaOwner\)\)/);
  assert.match(bridge, /cloudReady && betaOwner && user\?\.uid && view !== "home"/);
  assert.match(home, /useContinuityMonitor\(Boolean\(cloudReady && user\?\.uid && betaOwner\)\)/);
});

test("HOME exposes the continuity card before the existing transfer callout", async () => {
  const home = await read("components/home-transfer-page.tsx");
  const continuity = home.indexOf("<ContinuityHomeCard");
  const transfer = home.indexOf('className="tm-home-transfer-callout"');
  assert.ok(continuity > 0);
  assert.ok(transfer > continuity);
  assert.match(home, /App kosten & betalingen|ContinuityHomeCard/);
});

test("Bybit continuity form never persists credentials in browser storage", async () => {
  const source = await read("components/continuity-monitor.tsx");
  assert.match(source, /Bybit verbinden/);
  assert.match(source, /Verbinding testen/);
  assert.match(source, /read-only/);
  assert.doesNotMatch(source, /localStorage\.setItem\([^\n]*(api|secret|bybit)/i);
  assert.doesNotMatch(source, /useState\([^\n]*api_secret/i);
  assert.match(source, /api_secret: secretRef\.current\?\.value/);
});

test("continuity provider proxies are authenticated cloud routes", async () => {
  const [root, testRoute, connect, settings, ack] = await Promise.all([
    read("app/api/continuity/route.ts"),
    read("app/api/continuity/bybit/test/route.ts"),
    read("app/api/continuity/bybit/route.ts"),
    read("app/api/continuity/settings/route.ts"),
    read("app/api/continuity/alerts/ack/route.ts"),
  ]);
  for (const source of [root, testRoute, connect, settings, ack]) assert.match(source, /proxyCloud/);
  assert.match(testRoute, /\/v1\/me\/continuity\/bybit\/test/);
  assert.match(connect, /\/v1\/me\/continuity\/bybit/);
});

test("continuity CSS contains the three reference surfaces", async () => {
  const css = await read("app/continuity-monitor.css");
  assert.match(css, /\.tm-continuity-home-card/);
  assert.match(css, /\.tm-continuity-page/);
  assert.match(css, /\.tm-continuity-alert/);
  assert.match(css, /\.tm-continuity-modal/);
});
