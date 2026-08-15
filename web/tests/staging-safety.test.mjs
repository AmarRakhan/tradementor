import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("the cloud target is explicit, overrideable and authenticated", async () => {
  const source = await read("lib/cloud-proxy.ts");
  assert.match(source, /process\.env\.CLOUD_API_URL/);
  assert.match(source, /tradementor-api-604335232956\.europe-west4\.run\.app/);
  assert.match(source, /authorization\?\.startsWith\("Bearer "\)/);
  assert.match(source, /status: 401/);
  assert.doesNotMatch(source, /ASTER_SECRET|PRIVATE_KEY|API_SECRET/);
});

test("risk-sensitive browser routes remain thin authenticated server proxies", async () => {
  const paths = [
    "app/api/exchanges/aster/strategy3/canary/route.ts",
    "app/api/exchanges/aster/strategy3/rapid-build/route.ts",
    "app/api/execution/live/route.ts",
    "app/api/connections/aster/route.ts",
  ];
  for (const path of paths) {
    const source = await read(path);
    assert.match(source, /proxyCloud/);
    assert.match(source, /\/v1\/me\//);
    assert.doesNotMatch(source, /fetch\(|ASTER_SECRET|PRIVATE_KEY/);
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
    read("app/api/exchanges/aster/strategy3/settings/route.ts"),
    read("components/aster-strategy3-control.tsx"),
    read("lib/aster-bot-status.ts"),
  ]);
  assert.match(route, /proxyCloud/);
  assert.match(route, /\/v1\/me\/aster\/strategy3\/settings/);
  assert.match(control, /De server bevestigde niet dezelfde Strategy-3-instellingen/);
  assert.doesNotMatch(control, /localStorage/);
  assert.match(status, /browserDerived !== false/);
  assert.match(status, /return null/);
});

test("Strategy 2 production proxy is narrowly scoped and preserves Firebase identity", async () => {
  const [maker, proxy, start, readiness] = await Promise.all([
    read("components/aster-strategy2-maker.tsx"),
    read("lib/secure-strategy2-live.ts"),
    read("app/api/exchanges/aster/strategy2/start/route.ts"),
    read("app/api/exchanges/aster/strategy2/readiness/route.ts"),
  ]);
  assert.match(maker, /const paperOnly=false/);
  assert.match(proxy, /const strategy2Paths = new Set/);
  assert.match(proxy, /authorization\?\.startsWith\("Bearer "\)/);
  assert.match(proxy, /Authorization: authorization/);
  assert.match(proxy, /CLOUD_API_URL/);
  assert.match(start, /proxyStrategy2Live/);
  assert.match(readiness, /proxyStrategy2Live/);
});

test("Strategy 2 live controls cannot bypass server readiness or create request loops", async () => {
  const maker = await read("components/aster-strategy2-maker.tsx");
  assert.match(maker, /if\(liveReady\)\{await action\("start-live"\)/);
  assert.match(maker, /if\(status\.pending\)return/);
  assert.match(maker, /onConfirmed\(confirmed\)/);
  assert.match(maker, /await checkReadiness\(\)/);
  assert.match(maker, /result\.started!==true/);
  assert.match(maker, /geen extra startopdrachten verzonden/);
  assert.match(maker, /Boolean\(readiness\?\.softwareReady\)/);
});

test("Strategy 3 simulation remains local, paper-only and orderless", async () => {
  const [route, simulator] = await Promise.all([
    read("app/api/exchanges/aster/strategy3/simulate/route.ts"),
    read("lib/aster-strategy3-paper.ts"),
  ]);
  assert.match(route, /simulateStrategy3Paper/);
  assert.doesNotMatch(route, /proxyCloud|fetch\(/);
  assert.match(simulator, /paperOnly:true,liveReady:false/);
  assert.match(simulator, /Er zijn geen echte orders verzonden/);
  assert.doesNotMatch(simulator, /placeOrder|createOrder|sendOrder/);
});

test("Strategy 3 settings survive restart through authoritative cloud state", async () => {
  const [control, route] = await Promise.all([
    read("components/aster-strategy3-control.tsx"),
    read("app/api/exchanges/aster/strategy3/settings/route.ts"),
  ]);
  assert.match(control, /fromState\(settings\)/);
  assert.match(control, /method:kind==="save"\?"PUT"/);
  assert.match(control, /setDraft\(fromState\(saved\)\)/);
  assert.match(control, /onChanged\(\)/);
  assert.doesNotMatch(control, /localStorage/);
  assert.match(route, /proxyCloud/);
});

test("Strategy 3 dashboard never invents scheduler or entry state", async () => {
  const [parser, view] = await Promise.all([
    read("lib/aster-bot-status.ts"),
    read("components/aster-bot-status.tsx"),
  ]);
  assert.match(parser, /browserDerived !== false/);
  assert.match(parser, /entryStatuses\.has\(status\)/);
  assert.match(parser, /return null/);
  assert.match(view, /STATUS NIET BETROUWBAAR/);
  assert.match(view, /INSTAPSTATUS ONBEKEND/);
  assert.doesNotMatch(view, /setInterval|setTimeout|fetch\(/);
});
