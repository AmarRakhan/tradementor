// Close Profits 2.1 — the REAL frontend round handlers (sliced from the component) against an in-JS model of the
// round endpoints. Proves the client side: one round per confirmation, the phone only advances the server round,
// a lost answer is never "resent" as an order, "Hervat ronde" continues the SAME round, "Ronde afsluiten" works.
// Mocked: the round endpoints (their server behaviour is proven in cloud_api/test_close_profits_2_1_*.py).
import assert from "node:assert/strict";
import fs from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const start = source.indexOf("  // Close Profits 2.1: a round lives on the SERVER");
const end = source.indexOf("\n  function selectFilter(", start);
assert.ok(start !== -1 && end > start, "round handlers exist");
const handlerCode = stripTypeScriptTypes(source.slice(start, end));

/** In-JS model of the round endpoints: one active round, one item per advance. */
function makeServer({ outcome = {}, loseAnswerOnce = new Set(), failBeforeServer = 0 } = {}) {
  const s = { rounds: {}, active: "", log: [], closes: {}, failBeforeServer };
  const view = (r) => {
    const counts = { total: r.items.length, done: 0, skipped: 0, needsCheck: 0, remaining: 0 };
    for (const i of r.items) {
      if (i.status === "DONE") counts.done++; else if (i.status === "SKIPPED") counts.skipped++;
      else if (i.status === "NEEDS_CHECK") counts.needsCheck++; else counts.remaining++;
    }
    return JSON.parse(JSON.stringify({ ...r, counts }));
  };
  s.request = async (url, init = {}) => {
    const method = String(init.method || "GET").toUpperCase();
    s.log.push(method + " " + url);
    if (s.failBeforeServer > 0) { s.failBeforeServer--; throw new TypeError("Failed to fetch"); }   // never reached the server
    if (url === "/api/exchanges/aster/profit-close-rounds/active") {
      const r = s.rounds[s.active];
      return { round: r && (r.status === "RUNNING" || r.status === "PAUSED") ? view(r) : null };
    }
    if (url === "/api/exchanges/aster/profit-close-rounds" && method === "POST") {
      const body = JSON.parse(init.body);
      s.lastCreate = body;
      const current = s.rounds[s.active];
      if (current && (current.status === "RUNNING" || current.status === "PAUSED")) {
        throw new Error("Er loopt nog een Close Profits-ronde; hervat of sluit die eerst af");
      }
      const id = ("r" + Object.keys(s.rounds).length).padEnd(24, "0");
      s.rounds[id] = { roundId: id, status: "RUNNING", percentage: body.percentage,
        items: body.targets.map((t) => ({ symbol: t.symbol, side: "SHORT", status: "PENDING", attempt: 0 })) };
      s.active = id;
      return { created: true, round: view(s.rounds[id]) };
    }
    const m = url.match(/^\/api\/exchanges\/aster\/profit-close-rounds\/([a-z0-9]+)\/(advance|resume|abandon)$/);
    assert.ok(m, "only round endpoints are called by the handlers: " + url);
    const r = s.rounds[m[1]];
    if (m[2] === "abandon") { r.status = "ABANDONED"; s.active = ""; return { round: view(r), pending: false }; }
    if (m[2] === "resume") { if (r.status === "PAUSED") r.status = "RUNNING"; return { round: view(r) }; }
    if (r.status !== "RUNNING") return { round: view(r), busy: false };
    const item = r.items.find((i) => !["DONE", "SKIPPED", "NEEDS_CHECK"].includes(i.status));
    if (item) {
      const out = outcome[item.symbol] || "DONE";
      if (out === "PAUSE") { r.status = "PAUSED"; delete outcome[item.symbol]; }
      else { item.status = out; if (out === "DONE") s.closes[item.symbol] = (s.closes[item.symbol] || 0) + 1; }
    }
    if (!r.items.some((i) => !["DONE", "SKIPPED", "NEEDS_CHECK"].includes(i.status))) { r.status = "FINISHED"; s.active = ""; }
    if (item && loseAnswerOnce.has(item.symbol)) { loseAnswerOnce.delete(item.symbol); throw new TypeError("Failed to fetch"); }
    return { round: view(r), busy: false, waiting: false };
  };
  return s;
}

function harness(server, { targets = ["AAOIUSDT", "FILUSDT", "NATGASUSDT"], percentage = 25, active = null } = {}) {
  const ui = { messages: [], active, busy: false, refresh: 0 };
  const ctx = {
    profitBusy: false, profitConfirming: true, profitSnapshotReliable: true, profitClosePercentage: percentage,
    bulkCloseTargets: targets.map((symbol) => ({ symbol, side: "SHORT", quantity: 8 })),
    bulkCloseInFlightRef: { current: false },
    get activeProfitRound() { return ui.active; },
    setActiveProfitRound: (v) => { ui.active = v; },
    setProfitBusy: (v) => { ui.busy = v; }, setProfitConfirming() {}, setBulkCloseTargets() {}, setProfitPreview() {},
    setProfitMessage: (v) => { ui.messages.push(v); },
    onRetry: () => { ui.refresh++; },
    newCloseIdempotencyKey: (() => { let n = 0; return () => "confirm-key-" + ++n + "-padpad"; })(),
    authenticatedRequest: server.request,
    useEffect() {}, encodeURIComponent, JSON, Promise, Error, String, TypeError,
    setTimeout: (fn) => fn(),
  };
  vm.createContext(ctx);
  const api = vm.runInContext(handlerCode + "\n({ closeProfits, resumeProfitRound, abandonProfitRound, loadActiveProfitRound, profitRoundMessage });", ctx);
  return { api, ui, ctx };
}

test("one confirmation creates ONE server round with the confirmed SHORTs and drives it to the end", async () => {
  const server = makeServer();
  const h = harness(server);
  await h.api.closeProfits();
  assert.deepEqual(server.lastCreate.targets, [
    { symbol: "AAOIUSDT", side: "SHORT", quantity: 8 }, { symbol: "FILUSDT", side: "SHORT", quantity: 8 },
    { symbol: "NATGASUSDT", side: "SHORT", quantity: 8 }]);
  assert.equal(server.lastCreate.percentage, 25);
  assert.equal(server.lastCreate.confirm, true);
  assert.deepEqual(server.closes, { AAOIUSDT: 1, FILUSDT: 1, NATGASUSDT: 1 });
  assert.match(h.ui.messages.at(-1), /3 SHORTS gesloten · 0 overgeslagen · Ronde voltooid\./);
  assert.equal(h.ui.active, null);
  assert.equal(h.ui.refresh, 1);
  assert.ok(server.log.every((line) => !line.includes("/close")), "the phone never calls the per-symbol close itself");
});

test("Amar's case: answer lost at FILUSDT -> the server still has the round; resume continues, nothing twice", async () => {
  const server = makeServer({ loseAnswerOnce: new Set(["FILUSDT"]) });
  const h = harness(server);
  await h.api.closeProfits();                                 // the lost answer is simply asked again, never resent
  assert.deepEqual(server.closes, { AAOIUSDT: 1, FILUSDT: 1, NATGASUSDT: 1 });
  assert.match(h.ui.messages.at(-1), /Ronde voltooid/);
});

test("connection gone for longer: handler stops, round stays on the server, 'Hervat ronde' finishes the SAME round", async () => {
  const server = makeServer();
  const h = harness(server);
  const original = server.request;
  let calls = 0;
  server.request = async (url, init) => {                       // after the first close the phone goes offline
    if (url.endsWith("/advance") && ++calls > 1 && calls <= 4) throw new TypeError("Failed to fetch");
    return original(url, init);
  };
  h.ctx.authenticatedRequest = server.request;
  await h.api.closeProfits();
  assert.deepEqual(server.closes, { AAOIUSDT: 1 });
  assert.match(h.ui.messages.at(-1), /Verbinding onderbroken\. De ronde staat veilig op de server/);
  assert.equal(h.ui.active.counts.remaining, 2);
  const roundId = h.ui.active.roundId;
  // later: green button now reads "Hervat ronde · 2 resterend"
  h.ctx.bulkCloseInFlightRef.current = false;
  await h.api.resumeProfitRound();
  assert.deepEqual(server.closes, { AAOIUSDT: 1, FILUSDT: 1, NATGASUSDT: 1 });   // AAOI NOT closed again
  assert.equal(Object.keys(server.rounds).length, 1);
  assert.equal(server.rounds[roundId].status, "FINISHED");
});

test("a new press while a round is open never starts a second round; it shows the open round instead", async () => {
  const server = makeServer({ outcome: { FILUSDT: "PAUSE" } });
  const h = harness(server);
  await h.api.closeProfits();
  assert.equal(h.ui.active.status, "PAUSED");
  const again = harness(server);
  await again.api.closeProfits();
  assert.equal(Object.keys(server.rounds).length, 1);
  assert.match(again.ui.messages.at(-1), /Er loopt nog een ronde\./);
  assert.equal(again.ui.active.roundId, h.ui.active.roundId);
});

test("paused round: resume first unpauses on the server, then continues", async () => {
  const server = makeServer({ outcome: { FILUSDT: "PAUSE" } });
  const h = harness(server);
  await h.api.closeProfits();
  assert.match(h.ui.messages.at(-1), /Ronde gepauzeerd/);
  await h.api.resumeProfitRound();
  assert.ok(server.log.some((line) => line.endsWith("/resume")));
  assert.deepEqual(server.closes, { AAOIUSDT: 1, FILUSDT: 1, NATGASUSDT: 1 });
});

test("NEEDS_CHECK is reported per symbol and the rest continues", async () => {
  const server = makeServer({ outcome: { FILUSDT: "NEEDS_CHECK", NATGASUSDT: "SKIPPED" } });
  const h = harness(server);
  await h.api.closeProfits();
  assert.deepEqual(server.closes, { AAOIUSDT: 1 });
  assert.match(h.ui.messages.at(-1), /1 SHORTS gesloten · 1 overgeslagen · 1 te controleren in Aster \(FILUSDT\) · Ronde voltooid\./);
});

test("'Ronde afsluiten' closes the open round and frees the green button", async () => {
  const server = makeServer({ outcome: { FILUSDT: "PAUSE" } });
  const h = harness(server);
  await h.api.closeProfits();
  await h.api.abandonProfitRound();
  assert.equal(h.ui.active, null);
  assert.match(h.ui.messages.at(-1), /Ronde afgesloten/);
  assert.deepEqual(server.closes, { AAOIUSDT: 1 });
});

test("synchronous in-flight guard: two taps start one round", async () => {
  const server = makeServer();
  const h = harness(server);
  await Promise.all([h.api.closeProfits(), h.api.closeProfits()]);
  assert.equal(Object.keys(server.rounds).length, 1);
  assert.deepEqual(server.closes, { AAOIUSDT: 1, FILUSDT: 1, NATGASUSDT: 1 });
});

test("create request lost and no active round: clear message, nothing closed", async () => {
  const server = makeServer({ failBeforeServer: 2 });
  const h = harness(server);
  await h.api.closeProfits();
  assert.deepEqual(server.closes, {});
  assert.match(h.ui.messages.at(-1), /Failed to fetch|niet gelukt/);
});

test("handlers contain no order, hedge or Recovery logic of their own", () => {
  assert.doesNotMatch(handlerCode, /\/close"|expected_quantity|Recovery|rehedge|firestore|acquire|renew/i);
});

test("confirmation modal still shows the Auto Hedge consequence and keeps Focus Airbag hedges out", () => {
  assert.match(source, /data-testid="bulk-auto-hedge-warning"/);
  assert.match(source, /het paar gaat daarna in Recovery[\s\S]{0,200}re-hedge blijft UIT/);
  assert.match(source, /return side === "SHORT" && position\?\.focusAirbagHedge !== true/);
});

test("Next proxy routes map 1:1 to the backend round endpoints", () => {
  const read = (p) => fs.readFileSync(new URL("../app/api/exchanges/aster/profit-close-rounds/" + p, import.meta.url), "utf8");
  assert.match(read("route.ts"), /"\/v1\/me\/aster\/profit-close-rounds", "POST"/);
  assert.match(read("active/route.ts"), /"\/v1\/me\/aster\/profit-close-rounds\/active", "GET"/);
  for (const action of ["advance", "resume", "abandon"]) {
    const src = read(`[roundId]/${action}/route.ts`);
    assert.match(src, new RegExp("profit-close-rounds/\\$\\{roundId\\}/" + action + "`, \"POST\""));
    assert.match(src, /\^\[a-f0-9\]\{24\}\$/);
  }
});
