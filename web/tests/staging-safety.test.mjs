import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("the cloud target is pinned to production and authenticated", async () => {
  const source = await read("lib/cloud-proxy.ts");
  assert.doesNotMatch(source, /process\.env\.CLOUD_API_URL/);
  assert.match(source, /tradementor-api-604335232956\.europe-west4\.run\.app/);
  assert.match(source, /authorization\?\.startsWith\("Bearer "\)/);
  assert.match(source, /status: 401/);
  assert.doesNotMatch(source, /ASTER_SECRET|PRIVATE_KEY|API_SECRET/);
});

test("risk-sensitive browser routes remain thin authenticated server proxies", async () => {
  const paths = [
    "app/api/execution/live/route.ts",
    "app/api/connections/aster/route.ts",
    "app/api/exchanges/aster/strategy2/start/route.ts",
    "app/api/exchanges/aster/strategy2/readiness/route.ts",
  ];
  for (const path of paths) {
    const source = await read(path);
    assert.match(source, /proxyCloud|proxyStrategy2Live/);
    assert.doesNotMatch(source, /ASTER_SECRET|PRIVATE_KEY/);
  }
});

test("Firebase identity stays pinned and its bearer token is preserved", async () => {
  const [firebase, proxy] = await Promise.all([read("lib/firebase.ts"), read("lib/cloud-proxy.ts")]);
  assert.match(firebase, /authDomain: "tradementor-production\.firebaseapp\.com"/);
  assert.match(firebase, /projectId: "tradementor-production"/);
  assert.match(proxy, /Authorization: authorization/);
});

test("browser persistence is UID scoped and rejects a mismatched cached owner", async () => {
  const [cache, page] = await Promise.all([read("lib/aster-snapshot-cache.mjs"), read("app/page.tsx")]);
  assert.match(cache, /encodeURIComponent\(String\(uid/);
  assert.match(cache, /saved\?\.uid !== uid/);
  assert.match(cache, /exchange !== "aster"/);
  assert.match(page, /tradementor\.portfolioEquity\.v2\.\$\{encodeURIComponent\(user\?\.uid \|\| ""\)\}/);
});

test("the generic proxy fails closed before any upstream request without Firebase proof", async () => {
  const source = await read("lib/cloud-proxy.ts");
  const bearerGate = source.indexOf("authorization?.startsWith");
  const upstreamFetch = source.indexOf("await fetch");
  assert.ok(bearerGate >= 0 && upstreamFetch > bearerGate);
  assert.match(source, /Firebase ID-token ontbreekt/);
  assert.match(source, /TradeMentor Cloud is tijdelijk niet bereikbaar/);
});

test("Strategy settings and bot decisions remain server-authoritative", async () => {
  const [route, control, status] = await Promise.all([
    read("app/api/exchanges/aster/strategy2/settings/route.ts"),
    read("components/aster-strategy2-maker.tsx"),
    read("lib/aster-bot-status.ts"),
  ]);
  assert.match(route, /proxyStrategy2Live/);
  assert.match(control, /result\.strategy2/);
  assert.doesNotMatch(control, /localStorage/);
  assert.match(status, /strategyId:"aster-strategy-2"/);
  assert.doesNotMatch(status, /strategy3/i);
});

test("Multi BB production proxy is narrowly scoped and preserves Firebase identity", async () => {
  const [maker, proxy, start, readiness] = await Promise.all([
    read("components/aster-strategy2-maker.tsx"), read("lib/secure-strategy2-live.ts"),
    read("app/api/exchanges/aster/strategy2/start/route.ts"), read("app/api/exchanges/aster/strategy2/readiness/route.ts"),
  ]);
  assert.match(maker, /multi_bb_v1/);
  assert.match(proxy, /const strategy2Paths = new Set/);
  assert.match(proxy, /authorization\?\.startsWith\("Bearer "\)/);
  assert.match(proxy, /Authorization: authorization/);
  assert.doesNotMatch(proxy, /process\.env\.CLOUD_API_URL/);
  assert.match(start, /proxyStrategy2Live/); assert.match(readiness, /proxyStrategy2Live/);
});

test("Multi BB live controls cannot bypass server readiness or create request loops", async () => {
  const maker = await read("components/aster-strategy2-maker.tsx");
  assert.match(maker, /async function toggleLive/);
  assert.match(maker, /if \(status\.pending\) return/);
  assert.match(maker, /if \(liveReady\) return action\("start"\)/);
  assert.match(maker, /return checkReadiness\(true\)/);
  assert.match(maker, /startWhenReady && Boolean\(result\.liveReady\)/);
  assert.match(maker, /onConfirmed\(confirmed\)/);
  assert.match(maker, /readiness\?\.liveReady === true/);
});

test("Strategy 3 browser runtime is absent", async () => {
  const page = await read("app/page.tsx");
  const status = await read("lib/aster-bot-status.ts");
  assert.doesNotMatch(page, /strategy3Tp|parseStrategy3Tp|Strategy 3/);
  assert.doesNotMatch(status, /strategy3/i);
});
