// Close Profits 2.1 — end-to-end:
//   REAL frontend handlers (openProfitConfirmation + the round handlers sliced from the component)
//   -> REAL Next proxy code (lib/cloud-proxy.ts, only CLOUD_API redirected to 127.0.0.1)
//   -> REAL FastAPI production entrypoint (cloud_api/e2e_stack_server.py: p0_close_scope_guard -> withdraw_app ->
//      main.app + the rounds router) -> REAL Firestore SDK on the EMULATOR -> HTTP-level fake Aster.
// Runs only with CP20_BACKEND=real (CI job with the emulator); skipped otherwise. Never contacts a non-local host.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import os from "node:os";
import path from "node:path";
import baseTest, { after, before } from "node:test";
import vm from "node:vm";

const REAL = process.env.CP20_BACKEND === "real";
const test = (name, fn) => baseTest(name, { skip: REAL ? false : "needs CP20_BACKEND=real (Firestore emulator)" }, fn);
const root = new URL("../", import.meta.url);
const read = (rel) => fs.readFileSync(new URL(rel, root), "utf8");
const source = read("components/aster-recent-trades.tsx");
const slice = (a, b) => { const s = source.indexOf(a), e = source.indexOf(b, s); assert.ok(s !== -1 && e > s, a); return source.slice(s, e); };
const helperCode = slice("function finite(value: unknown) {", "function baseAsset(").replace(/: unknown/g, "");
const openCode = stripTypeScriptTypes(slice("  async function openProfitConfirmation() {", "  const bulkAutoHedgeTargets = "));
const roundCode = stripTypeScriptTypes(slice("  // Close Profits 2.1: a round lives on the SERVER", "\n  function selectFilter("));

let server, port, proxyCloud;
const realFetch = globalThis.fetch;

before(async () => {
  if (!REAL) return;
  const cwd = path.resolve(new URL("../cloud_api/", root).pathname);
  server = spawn("python3", ["-W", "ignore", "e2e_stack_server.py"], { cwd, env: { ...process.env, PYTHONPATH: cwd }, stdio: ["pipe", "pipe", "inherit"] });
  port = await new Promise((resolve, reject) => {
    server.stdout.once("data", (d) => resolve(Number(String(d).trim())));
    server.once("exit", (c) => reject(new Error("backend exited " + c)));
    setTimeout(() => reject(new Error("backend did not start within 180 s")), 180000).unref();
  });
  const proxySrc = stripTypeScriptTypes(read("lib/cloud-proxy.ts"))
    .replace(/export const CLOUD_API = "[^"]+";/, `export const CLOUD_API = "http://127.0.0.1:${port}";`);
  const file = path.join(os.tmpdir(), `cloud-proxy-rounds-${process.pid}.mjs`);
  fs.writeFileSync(file, proxySrc);
  ({ proxyCloud } = await import(file));
  globalThis.fetch = (url, init) => {
    assert.equal(new URL(String(url)).hostname, "127.0.0.1", "no non-local network access in this test");
    return realFetch(url, init);
  };
});
after(() => { globalThis.fetch = realFetch; server?.stdin.end(); });

async function api(pathname, body) {
  const res = await realFetch(`http://127.0.0.1:${port}${pathname}`, body === undefined ? {} : { method: "POST", body: JSON.stringify(body) });
  return res.json();
}

// Same contract as lib/cloud-client.ts authenticatedRequest, over the REAL proxy code. `offline(url)` = phone offline.
function makeAuthenticatedRequest(offline = () => false) {
  return async (url, init = {}) => {
    if (offline(url)) throw new TypeError("Failed to fetch");
    const method = String(init.method || "GET").toUpperCase();
    const backendPath = url.replace("/api/exchanges/aster/", "/v1/me/aster/");
    const request = new Request("http://app.local" + url, { method, headers: { authorization: "Bearer test-token" }, body: init.body });
    const response = await proxyCloud(request, backendPath, method);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`);
    return payload;
  };
}

function world() {
  const positions = [], pairs = {};
  for (let i = 0; i < 12; i++) {
    const symbol = `C${String(i).padStart(2, "0")}USDT`;
    positions.push({ symbol, side: "SHORT", qty: 8 + i, mark: 100, entry: 105 });
    positions.push({ symbol, side: "LONG", qty: 5, mark: 100, entry: 95 });
    if (i % 4 === 0) pairs[symbol] = { status: "HEDGED", protectedSide: "LONG", hedgeSide: "SHORT", rehedgeEnabled: true, reservedHedgeQty: 0, generationId: "g" + i };
  }
  positions.push({ symbol: "LOSSUSDT", side: "SHORT", qty: 3, mark: 100, entry: 95 });
  return { positions, pairs };
}

async function prepare({ percentage = 25, modes = {} } = {}) {
  const w = world();
  await api("/__setup", { ...w, modes, workerProbe: false });
  await api("/__mutate", { autoHedgeEnabled: true });
  const state0 = await api("/__state");
  const live = state0.rows.map((r) => ({ symbol: r.symbol, side: r.positionSide, unrealizedPnl: Number(r.unRealizedProfit), quantity: Math.abs(Number(r.positionAmt)) }));
  return { w, shortProfit: live.filter((p) => p.side === "SHORT" && p.unrealizedPnl > 0.5), percentage };
}

async function handlers({ shortProfit, percentage }, offline) {
  const ui = { targets: [], messages: [], active: null };
  const auth = makeAuthenticatedRequest(offline);
  const openCtx = {
    profitBusy: false, profitSnapshotReliable: true, shortProfitCandidates: shortProfit, profitClosePercentage: percentage,
    setProfitConfirming() {}, setBulkCloseTargets: (v) => { ui.targets = v; }, setProfitPreview() {}, setProfitBusy() {},
    setProfitMessage: (v) => { ui.messages.push(v); }, authenticatedRequest: auth, Number, String, Math, Array, Error, JSON, URL: undefined,
  };
  vm.createContext(openCtx); vm.runInContext(helperCode, openCtx);
  await vm.runInContext(openCode + "\nopenProfitConfirmation;", openCtx)();
  const ctx = {
    profitBusy: false, profitConfirming: true, profitSnapshotReliable: true, profitClosePercentage: percentage,
    get bulkCloseTargets() { return ui.targets; }, bulkCloseInFlightRef: { current: false },
    get activeProfitRound() { return ui.active; }, setActiveProfitRound: (v) => { ui.active = v; },
    setProfitBusy() {}, setProfitConfirming() {}, setBulkCloseTargets() {}, setProfitPreview() {},
    setProfitMessage: (v) => { ui.messages.push(v); }, onRetry() {},
    newCloseIdempotencyKey: () => "e2e-confirm-" + Math.random().toString(36).slice(2) + "-pad",
    authenticatedRequest: auth, useEffect() {}, encodeURIComponent, JSON, Promise, Error, String, TypeError,
    setTimeout: (fn) => fn(),
  };
  vm.createContext(ctx);
  const h = vm.runInContext(roundCode + "\n({ closeProfits, resumeProfitRound, abandonProfitRound });", ctx);
  return { h, ui, ctx };
}

const perSymbol = (state) => state.orders.reduce((acc, [sym]) => ({ ...acc, [sym]: (acc[sym] || 0) + 1 }), {});
const shorts = () => Array.from({ length: 12 }, (_, i) => `C${String(i).padStart(2, "0")}USDT`);

for (const percentage of [25, 50, 75, 100]) {
  test(`${percentage}%: one round over the real stack closes every profitable SHORT exactly once`, async () => {
    const env = await prepare({ percentage });
    const { h, ui } = await handlers(env);
    assert.equal(ui.targets.length, 12);
    await h.closeProfits();
    const state = await api("/__state");
    assert.deepEqual(perSymbol(state), Object.fromEntries(shorts().map((s) => [s, 1])));
    assert.ok(state.orders.every(([, side]) => side === "SHORT"), "LONGs are never touched");
    assert.match(ui.messages.at(-1), /12 SHORTS gesloten · 0 overgeslagen · Ronde voltooid\./);
    assert.equal(ui.active, null);
  });
}

test("phone offline after 3 closes: round stays on the server; 'Hervat ronde' finishes it, nothing twice", async () => {
  const env = await prepare({ percentage: 25 });
  let advances = 0, online = false;
  const { h, ui, ctx } = await handlers(env, (url) => url.endsWith("/advance") && !online && ++advances > 3);
  await h.closeProfits();
  assert.match(ui.messages.at(-1), /Verbinding onderbroken/);
  assert.equal(Object.keys(perSymbol(await api("/__state"))).length, 3);
  assert.equal(ui.active.counts.remaining, 9);
  online = true;
  ctx.bulkCloseInFlightRef.current = false;
  await h.resumeProfitRound();
  assert.deepEqual(perSymbol(await api("/__state")), Object.fromEntries(shorts().map((s) => [s, 1])));
  assert.match(ui.messages.at(-1), /Ronde voltooid/);
});

test("read timeout after Aster accepted (the FIL case): reconciled on the server, never ordered twice", async () => {
  const env = await prepare({ percentage: 50, modes: { C03USDT: "drop_after_accept" } });
  const { h, ui } = await handlers(env);
  await h.closeProfits();
  assert.deepEqual(perSymbol(await api("/__state")), Object.fromEntries(shorts().map((s) => [s, 1])));
  assert.match(ui.messages.at(-1), /Ronde voltooid/);
});

test("a second confirmation while a round is open never starts a second round", async () => {
  const env = await prepare({ percentage: 25 });
  const first = await handlers(env, (url) => url.endsWith("/advance"));   // round created, then offline
  await first.h.closeProfits();
  const second = await handlers(env);
  await second.h.closeProfits();
  assert.match(second.ui.messages.at(-1), /Er loopt nog een ronde\./);
  assert.equal(second.ui.active.roundId, first.ui.active.roundId);
  assert.equal((await api("/__state")).orders.length, 0);
});
