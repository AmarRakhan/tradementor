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
function makeAuthenticatedRequest(offline = () => false, loseAnswer = () => false) {
  return async (url, init = {}) => {
    if (offline(url)) throw new TypeError("Failed to fetch");
    const method = String(init.method || "GET").toUpperCase();
    const backendPath = url.replace("/api/exchanges/aster/", "/v1/me/aster/");
    const request = new Request("http://app.local" + url, { method, headers: { authorization: "Bearer test-token" }, body: init.body });
    const response = await proxyCloud(request, backendPath, method);
    const payload = await response.json().catch(() => ({}));
    if (loseAnswer(url)) throw new TypeError("Failed to fetch");   // the server DID handle it; the answer is lost
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

// The 2.0 integration world: 25 SHORTs (5 Auto Hedge) + edge cases (exactly $0,50, $0,51, losing, too small).
function world20() {
  const positions = [], pairs = {};
  for (let i = 0; i < 25; i++) {
    const symbol = `C${String(i).padStart(2, "0")}USDT`;
    positions.push({ symbol, side: "SHORT", qty: 8 + i, mark: 100, entry: 105 });
    positions.push({ symbol, side: "LONG", qty: 5, mark: 100, entry: 95 });
    if (i % 5 === 0) pairs[symbol] = { status: "HEDGED", protectedSide: "LONG", hedgeSide: "SHORT", rehedgeEnabled: true, reservedHedgeQty: 0, generationId: "g" + i };
  }
  positions.push({ symbol: "EDGE50USDT", side: "SHORT", qty: 1, mark: 100, entry: 100.5 });
  positions.push({ symbol: "EDGE51USDT", side: "SHORT", qty: 1, mark: 100, entry: 100.51 });
  positions.push({ symbol: "LOSSUSDT", side: "SHORT", qty: 3, mark: 100, entry: 95 });
  positions.push({ symbol: "TINYUSDT", side: "SHORT", qty: 0.002, mark: 100, entry: 400, minQty: 0.001, step: 0.001 });
  return { positions, pairs };
}

async function prepare({ percentage = 25, modes = {}, w = world(), workerProbe = false } = {}) {
  await api("/__setup", { ...w, modes, workerProbe });
  await api("/__mutate", { autoHedgeEnabled: true });
  const state0 = await api("/__state");
  const live = state0.rows.map((r) => ({ symbol: r.symbol, side: r.positionSide, unrealizedPnl: Number(r.unRealizedProfit), quantity: Math.abs(Number(r.positionAmt)) }));
  return { w, shortProfit: live.filter((p) => p.side === "SHORT" && p.unrealizedPnl > 0.5), percentage };
}

async function handlers({ shortProfit, percentage }, offline, loseAnswer) {
  const ui = { targets: [], messages: [], active: null };
  const auth = makeAuthenticatedRequest(offline, loseAnswer);
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


// ---- the 2.0 frontend -> proxy -> backend integration contracts, now on the 2.1 round (contract matrix) ----------
const shorts25 = () => Array.from({ length: 25 }, (_, i) => `C${String(i).padStart(2, "0")}USDT`);

for (const percentage of [25, 50, 75, 100]) {
  test(`2.0 world ${percentage}%: 25 SHORTs (5 Auto Hedge) + edge cases, exact sizes, LONGs untouched, worker deferred`, async () => {
    const w = world20();
    const env = await prepare({ percentage, w, workerProbe: true });
    const state0 = await api("/__state");
    const { h, ui } = await handlers(env);
    assert.deepEqual(ui.targets.map((t) => t.symbol).sort(), [...shorts25(), "EDGE51USDT", "TINYUSDT"].sort());   // strict > 0,50
    for (const t of ui.targets) assert.equal(t.quantity, state0.positions[`${t.symbol}|SHORT`]);   // FULL live quantity
    await h.closeProfits();
    const state = await api("/__state");
    const tinySkipped = percentage < 100;                     // partial TINY falls below the $5 minimum notional
    assert.equal(state.orders.length, 25 + 1 + (tinySkipped ? 0 : 1), "one MARKET order per closable SHORT");
    assert.deepEqual(state.orders.map(([sym]) => sym),
      ui.targets.map((t) => t.symbol).filter((sym) => !(tinySkipped && sym === "TINYUSDT")), "sequential, preview order");
    for (const [sym, side, qty] of state.orders) {
      assert.equal(side, "SHORT");
      const full = state0.positions[`${sym}|SHORT`];
      assert.ok(Math.abs(qty - full * percentage / 100) < 1e-6 || Math.abs(qty - Math.floor(full * percentage / 100 / 0.001 + 1e-9) * 0.001) < 1e-6, `${sym} ${qty}`);
    }
    for (const key of Object.keys(state0.positions).filter((k) => k.endsWith("|LONG"))) assert.equal(state.positions[key], state0.positions[key]);
    assert.equal(state.positions["LOSSUSDT|SHORT"], 3);
    assert.equal(state.positions["EDGE50USDT|SHORT"], 1);
    for (const sym of Object.keys(w.pairs)) { assert.equal(state.pairs[sym].status, "RECOVERY"); assert.equal(state.pairs[sym].rehedgeEnabled, false); }
    const hedged = new Set(Object.keys(w.pairs));
    const hedgedProbes = state.probes.filter((p) => hedged.has(p.symbol));
    assert.equal(hedgedProbes.length, hedged.size);
    assert.ok(hedgedProbes.every((p) => p.workerGotLease === false), "Auto Hedge worker deferred during every Auto Hedge close");
    assert.equal(state.leaseHolder?.token || "", "");                      // account lease released
    assert.match(ui.messages.at(-1), tinySkipped ? /26 SHORTS gesloten · 1 overgeslagen · Ronde voltooid\./ : /27 SHORTS gesloten · 0 overgeslagen · Ronde voltooid\./);
  });
}

test("response lost AFTER the backend executed the step: asked again, never ordered twice", async () => {
  const env = await prepare({ percentage: 50 });
  let lost = 0;
  const { h, ui } = await handlers(env, undefined, (url) => url.endsWith("/advance") && lost++ % 3 === 1);
  await h.closeProfits();
  assert.deepEqual(perSymbol(await api("/__state")), Object.fromEntries(shorts().map((s) => [s, 1])));
  assert.match(ui.messages.at(-1), /Ronde voltooid/);
});

test("three simultaneous taps / two tabs never start a second round or a second order", async () => {
  const env = await prepare({ percentage: 25 });
  const a = await handlers(env), b = await handlers(env);
  await Promise.all([a.h.closeProfits(), a.h.closeProfits(), a.h.closeProfits(), b.h.closeProfits()]);
  assert.deepEqual(perSymbol(await api("/__state")), Object.fromEntries(shorts().map((s) => [s, 1])));
});

test("between preview and execution: changed size and fallen profit are skipped without an order, the rest continues", async () => {
  const env = await prepare({ percentage: 25 });
  const { h, ui } = await handlers(env);
  await api("/__mutate", { pos: { "C01USDT|SHORT": 7 }, marks: { C02USDT: 104.99 } });
  await h.closeProfits();
  const per = perSymbol(await api("/__state"));
  assert.equal(per.C01USDT, undefined);
  assert.equal(per.C02USDT, undefined);
  assert.equal(Object.keys(per).length, 10);
  assert.match(ui.messages.at(-1), /10 SHORTS gesloten · 2 overgeslagen · Ronde voltooid\./);
});

test("plain SHORT that becomes an Auto Hedge pair after the preview is closed with the existing manual transition", async () => {
  const env = await prepare({ percentage: 25, workerProbe: true });
  const { h } = await handlers(env);
  await api("/__mutate", { pairs: { C01USDT: { status: "HEDGED", protectedSide: "LONG", hedgeSide: "SHORT", rehedgeEnabled: true, reservedHedgeQty: 0, generationId: "late" } } });
  await h.closeProfits();
  const state = await api("/__state");
  assert.equal(perSymbol(state).C01USDT, 1);
  assert.equal(state.pairs.C01USDT.status, "RECOVERY");
  assert.equal(state.positions["C01USDT|LONG"], 5);
  assert.ok(state.probes.filter((p) => p.symbol === "C01USDT").every((p) => p.workerGotLease === false));
});
