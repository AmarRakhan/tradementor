// Close Profits 2.0 — offline combination test:
//   REAL frontend handlers (openProfitConfirmation + closeProfits sliced from the component)
//   -> REAL Next proxy code (lib/cloud-proxy.ts, only CLOUD_API redirected to 127.0.0.1)
//   -> local HTTP wrapper -> REAL close/preview route source (cloud_api/main.py via AST)
//   -> in-memory Firestore model + simulated Aster ledger.
// Mocked: Firestore, Aster, browser/React state, Firebase auth. No production host is ever contacted.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import baseTest, { after, before } from "node:test";
const test = (name, fn) => baseTest(name, async (t) => { if (backendUnavailable) return t.skip("backend not startable: " + backendUnavailable); return fn(t); });
import { stripTypeScriptTypes } from "node:module";
import vm from "node:vm";

const root = new URL("../", import.meta.url);
const read = (rel) => fs.readFileSync(new URL(rel, root), "utf8");
const source = read("components/aster-recent-trades.tsx");
const slice = (a, b) => { const s = source.indexOf(a), e = source.indexOf(b, s); assert.ok(s !== -1 && e > s, a); return source.slice(s, e); };
const helperCode = slice("function finite(value: unknown) {", "function baseAsset(").replace(/: unknown/g, "");
const closeCode = slice("  async function closeProfits() {", "\n  function selectFilter(");
const openCode = stripTypeScriptTypes(slice("  async function openProfitConfirmation() {", "  const bulkAutoHedgeTargets = "));

let server, port, proxyCloud, stopServer, backendUnavailable = "";
const realFetch = globalThis.fetch;

before(async () => {
  const cwd = path.resolve(new URL("../cloud_api/", root).pathname);
  const env = { ...process.env, PYTHONPATH: [cwd, process.env.CP20_PYTHONPATH].filter(Boolean).join(path.delimiter) };
  server = spawn("python3", ["offline_close_server.py"], { cwd, env, stdio: ["pipe", "pipe", "inherit"] });
  try {
    port = await new Promise((resolve, reject) => {
      server.stdout.once("data", (d) => resolve(Number(String(d).trim())));
      server.once("error", reject); server.once("exit", (c) => reject(new Error("backend exited " + c)));
    });
  } catch (error) {
    backendUnavailable = String(error);          // e.g. httpx missing: set CP20_PYTHONPATH to a dir with an httpx stub, or install deps
    return;
  }
  const proxySrc = stripTypeScriptTypes(read("lib/cloud-proxy.ts"))
    .replace(/export const CLOUD_API = "[^"]+";/, `export const CLOUD_API = "http://127.0.0.1:${port}";`);
  const file = path.join(os.tmpdir(), `cloud-proxy-${process.pid}.mjs`);
  fs.writeFileSync(file, proxySrc);
  ({ proxyCloud } = await import(file));
  globalThis.fetch = (url, init) => {                       // hard guard: never leave 127.0.0.1
    assert.equal(new URL(String(url)).hostname, "127.0.0.1", "no non-local network access in this test");
    return realFetch(url, init);
  };
  stopServer = () => { server.stdin.end(); };
});
after(() => { globalThis.fetch = realFetch; stopServer?.(); });

async function api(pathname, body) {
  const res = await realFetch(`http://127.0.0.1:${port}${pathname}`, body === undefined ? {} : { method: "POST", body: JSON.stringify(body) });
  return res.json();
}

// the three Next route files map /api/exchanges/aster/... to /v1/me/aster/... (asserted, not assumed)
assert.match(read("app/api/exchanges/aster/positions/[symbol]/close/route.ts"), /`\/v1\/me\/aster\/positions\/\$\{encodeURIComponent\(symbol\)\}\/close`, "POST"/);
assert.match(read("app/api/exchanges/aster/positions/manual-profit-close-plan/route.ts"), /\/v1\/me\/aster\/positions\/manual-profit-close-plan\?percentage=\$\{raw\}/);

// Same contract as lib/cloud-client.ts authenticatedRequest (token, JSON, detail -> Error), over the real proxy code.
function makeAuthenticatedRequest(afterForward) {
  return async (url, init = {}) => {
    const method = String(init.method || "GET").toUpperCase();
    const m = url.match(/^\/api\/exchanges\/aster\/positions\/([^/]+)\/close$/);
    const backendPath = m ? `/v1/me/aster/positions/${m[1]}/close`
      : url.replace("/api/exchanges/aster/", "/v1/me/aster/");
    const request = new Request("http://app.local" + url, { method, headers: { authorization: "Bearer test-token" }, body: init.body });
    const response = await proxyCloud(request, backendPath, method);
    const payload = await response.json().catch(() => ({}));
    if (m && afterForward) afterForward(m[1]);              // e.g. connection lost AFTER the backend handled the order
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `Accountgegevens niet beschikbaar (HTTP ${response.status}).`);
    return payload;
  };
}

function world() {
  const positions = [], pairs = {};
  for (let i = 0; i < 25; i++) {
    const symbol = `C${String(i).padStart(2, "0")}USDT`;
    positions.push({ symbol, side: "SHORT", qty: 8 + i, mark: 100, entry: 105 });          // pnl 5*qty > 0.5
    positions.push({ symbol, side: "LONG", qty: 5, mark: 100, entry: 95 });                // hedge partner / plain LONG
    if (i % 5 === 0) pairs[symbol] = { status: "HEDGED", protectedSide: "LONG", hedgeSide: "SHORT", rehedgeEnabled: true, reservedHedgeQty: 0, generationId: "g" + i };
  }
  positions.push({ symbol: "EDGE50USDT", side: "SHORT", qty: 1, mark: 100, entry: 100.5 });   // pnl exactly 0.50  -> excluded
  positions.push({ symbol: "EDGE51USDT", side: "SHORT", qty: 1, mark: 100, entry: 100.51 });  // pnl 0.51 -> included
  positions.push({ symbol: "LOSSUSDT", side: "SHORT", qty: 3, mark: 100, entry: 95 });        // losing SHORT -> excluded
  positions.push({ symbol: "TINYUSDT", side: "SHORT", qty: 0.002, mark: 100, entry: 400, minQty: 0.001, step: 0.001 }); // profitable, 25% below step
  return { positions, pairs };
}

async function run({ percentage, modes = {}, workerProbe = true, afterForward, concurrent = false, between, autoHedgeEnabled = true }) {
  const w = world();
  await api("/__setup", { ...w, modes, workerProbe });
  await api("/__mutate", { autoHedgeEnabled });
  const state0 = await api("/__state");
  const auth = makeAuthenticatedRequest(afterForward);
  const live = state0.rows.map((r) => ({
    symbol: r.symbol, side: r.positionSide, unrealizedPnl: Number(r.unRealizedProfit), quantity: Math.abs(Number(r.positionAmt)),
    positionLossAutoHedge: w.pairs[r.symbol] ? { status: "HEDGED", role: r.positionSide === "SHORT" ? "HEDGE" : "PROTECTED" } : undefined,
  }));
  const shortProfit = live.filter((p) => p.side === "SHORT" && p.unrealizedPnl > 0.5);
  const ui = { targets: [], messages: [], busy: false, confirming: false };
  const openCtx = {
    profitBusy: false, profitSnapshotReliable: true, shortProfitCandidates: shortProfit, profitClosePercentage: percentage,
    setProfitConfirming: (v) => { ui.confirming = v; }, setBulkCloseTargets: (v) => { ui.targets = v; },
    setProfitPreview() {}, setProfitBusy: (v) => { ui.busy = v; }, setProfitMessage: (v) => { ui.messages.push(v); },
    authenticatedRequest: auth, Number, String, Math, Array, Error, JSON, URL: undefined,
  };
  vm.createContext(openCtx); vm.runInContext(helperCode, openCtx);
  await vm.runInContext(openCode + "\nopenProfitConfirmation;", openCtx)();
  if (between) await between();                                   // world changes after the preview, before the confirmation is executed
  const closeCtx = {
    profitBusy: false, profitConfirming: true, profitSnapshotReliable: true, bulkCloseTargets: ui.targets,
    bulkCloseInFlightRef: { current: false }, profitClosePercentage: percentage,
    setProfitBusy() {}, setProfitConfirming() {}, setProfitMessage: (v) => { ui.messages.push(v); }, setBulkCloseTargets() {}, setProfitPreview() {},
    onRetry() {}, encodeURIComponent, JSON, Promise, Error, String, setTimeout: (fn) => fn(),
    newCloseIdempotencyKey: (() => { let n = 0; return () => `bulk-key-${percentage}-${Date.now()}-${++n}-pad`; })(),
    authenticatedRequest: auth,
  };
  const handler = vm.runInNewContext(closeCode + "\ncloseProfits;", closeCtx);
  if (concurrent) await Promise.all([handler(), handler(), handler()]); else await handler();
  return { w, state0, ui, state: await api("/__state"), close: handler, closeCtx };
}

const expectedSymbols = () => [...Array.from({ length: 25 }, (_, i) => `C${String(i).padStart(2, "0")}USDT`), "EDGE51USDT", "TINYUSDT"];

for (const percentage of [25, 50, 75, 100]) {
  test(`${percentage}%: 25 profitable SHORTs (5 Auto Hedge) + edge cases via frontend -> proxy -> backend`, async () => {
    const { ui, state, state0 } = await run({ percentage });
    const targets = ui.targets.map((t) => t.symbol).sort();
    assert.deepEqual(targets, expectedSymbols().sort());                       // strict > 0.50: EDGE50 / LOSS excluded; LONGs absent
    assert.ok(ui.targets.every((t) => t.side === "SHORT"));
    for (const t of ui.targets) assert.equal(t.quantity, state0.positions[`${t.symbol}|SHORT`]);   // expected_quantity = FULL live quantity
    // TINY: partial sizes fall below the contract minimum notional ($5) -> skipped; 100% is a full close (no partial filters)
    const tinyAtThisPct = percentage < 100;
    const orders = state.orders;
    assert.equal(orders.length, 25 + 1 + (tinyAtThisPct ? 0 : 1), "one MARKET order per closable SHORT");
    for (const [sym, side, qty] of orders) {
      assert.equal(side, "SHORT");                                              // never a LONG order
      const full = state0.positions[`${sym}|SHORT`];
      assert.ok(Math.abs(qty - full * percentage / 100) < 1e-6 || Math.abs(qty - Math.floor(full * percentage / 100 / 0.001 + 1e-9) * 0.001) < 1e-6, `${sym} ${qty}`);
    }
    for (const symbol of Object.keys(state0.positions).filter((k) => k.endsWith("|LONG"))) assert.equal(state.positions[symbol], state0.positions[symbol]);
    assert.equal(state.positions["LOSSUSDT|SHORT"], 3);                         // untouched
    assert.equal(state.positions["EDGE50USDT|SHORT"], 1);
    const closedHedged = Object.entries(state.pairs).filter(([s]) => s in world().pairs);
    for (const [, doc] of closedHedged) { assert.equal(doc.status, "RECOVERY"); assert.equal(doc.rehedgeEnabled, false); }   // existing manual transition
    // Auto Hedge-managed symbols: the existing route holds the account lease across freeze + order -> worker deferred
    const hedged = new Set(Object.keys(world().pairs));
    const hedgedProbes = state.probes.filter((p) => hedged.has(p.symbol));
    assert.equal(hedgedProbes.length, hedged.size);
    assert.ok(hedgedProbes.every((p) => p.workerGotLease === false), "Auto Hedge worker is deferred during every Auto Hedge-managed close");
    assert.equal(state.leaseHolder?.token || "", "");                           // lease released
    if (tinyAtThisPct) assert.match(ui.messages.at(-1), /1 te klein overgeslagen/);
    assert.match(ui.messages.at(-1), /Verwerking voltooid/);
    // sequential: the backend saw the requests one after another in the preview order
    assert.deepEqual(state.requests.map((r) => r.symbol), ui.targets.map((t) => t.symbol));
    assert.ok(state.requests.every((r) => Object.keys(r.body).sort().join() === "confirm,expected_quantity,idempotency_key,percentage,side"));
  });
}

test("UNKNOWN (connection lost after Aster accepted) stops the series at once; replay never doubles the order", async () => {
  const r = await run({ percentage: 25, modes: { C05USDT: "drop_after_accept" } });
  const ordered = r.state.orders.map((o) => o[0]);
  assert.deepEqual(ordered, ["C00USDT", "C01USDT", "C02USDT", "C03USDT", "C04USDT", "C05USDT"]);   // nothing after the UNKNOWN
  assert.match(r.ui.messages.at(-1), /Gestopt bij C05USDT/);
  assert.equal(r.state.pairs.C05USDT.status, "MANUAL_RELEASE_UNCERTAIN");
  // user (or a stale tab) replays the same stale target list: the exchange quantity moved -> refused, no second order
  r.closeCtx.bulkCloseTargets = r.ui.targets; r.closeCtx.bulkCloseInFlightRef.current = false;
  await r.close();
  const after = await api("/__state");
  assert.equal(after.orders.filter((o) => o[0] === "C05USDT").length, 1);
  assert.equal(after.orders.length, 6);                                                              // replay refused at the first (changed) position
});

test("response lost AFTER the backend executed (proxy/network drop): series stops, no automatic retry, one order", async () => {
  const r = await run({ percentage: 50, afterForward: (symbol) => { if (symbol === "C03USDT") throw new TypeError("fetch failed"); } });
  assert.equal(r.state.orders.filter((o) => o[0] === "C03USDT").length, 1);
  assert.equal(r.state.orders.some((o) => o[0] === "C04USDT"), false);
  assert.match(r.ui.messages.at(-1), /Gestopt bij C03USDT/);
  assert.equal(r.state.requests.filter((q) => q.symbol === "C03USDT").length, 1);                   // no retry of the POST
});

test("repeated clicks on the green button during a running series do not duplicate orders", async () => {
  const r = await run({ percentage: 25, concurrent: true });
  assert.equal(r.state.requests.length, 27);
  assert.equal(new Set(r.state.orders.map((o) => o[0])).size, r.state.orders.length);                // each SHORT ordered once
});

test("positions changing between snapshot and execution are refused, never closed with a wrong size", async () => {
  const w = world();
  await api("/__setup", { ...w, workerProbe: false });
  const auth = makeAuthenticatedRequest();
  const stale = [{ symbol: "C01USDT", side: "SHORT", quantity: 9 }, { symbol: "C02USDT", side: "SHORT", quantity: 3 }];  // C02 really 10
  const closeCtx = { profitBusy: false, profitConfirming: true, profitSnapshotReliable: true, bulkCloseTargets: stale, bulkCloseInFlightRef: { current: false },
    profitClosePercentage: 25, setProfitBusy() {}, setProfitConfirming() {}, setProfitMessage() {}, setBulkCloseTargets() {}, setProfitPreview() {}, onRetry() {},
    encodeURIComponent, JSON, Promise, Error, String, setTimeout: (fn) => fn(), newCloseIdempotencyKey: (() => { let n = 0; return () => `stale-key-${++n}-padpadpad`; })(), authenticatedRequest: auth };
  await vm.runInNewContext(closeCode + "\ncloseProfits;", closeCtx)();
  const s = await api("/__state");
  assert.deepEqual(s.orders.map((o) => o[0]), ["C01USDT"]);                                          // C02 refused (stale) and the series stopped
  assert.equal(s.positions["C02USDT|SHORT"], 10);
});

test("profit fell to <= $0,50 between preview and execution: that SHORT is skipped without an order, the rest continues", async () => {
  const r = await run({ percentage: 25, between: () => api("/__mutate", { marks: { C00USDT: 104.95 } }) });   // 8 * 0.05 = $0,40
  assert.equal(r.state.orders.some((o) => o[0] === "C00USDT"), false);
  assert.equal(r.state.orders.some((o) => o[0] === "C01USDT"), true);
  assert.match(r.ui.messages.at(-1), /1 niet meer boven \$0,50 winst/);
});

test("plain SHORT becomes an Auto Hedge pair between preview and execution: closed with the existing manual transition, worker deferred", async () => {
  const r = await run({ percentage: 50, between: () => api("/__mutate", {
    pairs: { C07USDT: { status: "HEDGED", protectedSide: "LONG", hedgeSide: "SHORT", rehedgeEnabled: true, reservedHedgeQty: 0, generationId: "late" } } }) });
  assert.equal(r.state.pairs.C07USDT.status, "RECOVERY");
  assert.equal(r.state.pairs.C07USDT.rehedgeEnabled, false);
  assert.equal(r.state.orders.filter((o) => o[0] === "C07USDT").length, 1);
  const probe = r.state.probes.find((p) => p.symbol === "C07USDT");
  assert.equal(probe.workerGotLease, false);
});

test("plain SHORT with a same-symbol LONG holds the account lease while Auto Hedge is on (worker deferred); off -> unchanged", async () => {
  let r = await run({ percentage: 25 });
  assert.ok(r.state.probes.filter((p) => /^C\d\d/.test(p.symbol)).every((p) => p.workerGotLease === false));
  r = await run({ percentage: 25, autoHedgeEnabled: false });
  const hedged = new Set(Object.keys(world().pairs));
  assert.ok(r.state.probes.filter((p) => /^C\d\d/.test(p.symbol) && !hedged.has(p.symbol)).every((p) => p.workerGotLease === true));   // original lease-free path
});
