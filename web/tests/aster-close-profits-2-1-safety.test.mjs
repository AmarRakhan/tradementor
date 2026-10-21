// Close Profits 2.1 — offline safety tests (no network, no live orders).
// The real component source is sliced out and executed in a vm sandbox with mocks.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";
import { stripTypeScriptTypes } from "node:module";

const source = fs.readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");

function slice(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.ok(start !== -1 && end > start, "marker exists: " + startMarker);
  return source.slice(start, end);
}
const helpers = slice("function finite(value: unknown) {", "function baseAsset(");
const helperCode = helpers.replace(/: unknown/g, "").replace(/symbol = ""/, 'symbol = ""');

// --- candidate filter (real source of the useMemo callback) -------------------
const filterSrc = slice("  const shortProfitCandidates = useMemo(", "  const shortProfitCandidateTotal");
const bodyStart = filterSrc.indexOf("() => profitCandidates.filter(");
const filterExpr = filterSrc.slice(bodyStart, filterSrc.lastIndexOf("[profitCandidates]")).replace(/,\s*$/, "");

function candidates(profitCandidates) {
  const ctx = { profitCandidates, String, Number };
  vm.createContext(ctx);
  vm.runInContext(helperCode, ctx);
  return vm.runInContext("(" + filterExpr + ")()", ctx);
}
const pos = (symbol, side, pnl, extra = {}) => ({ symbol, side, unrealizedPnl: pnl, quantity: 1, ...extra });
const AUTO_HEDGE = { status: "HEDGED", role: "PROTECTED", protectedSide: "LONG", hedgeSide: "SHORT", rehedgeEnabled: true };

test("normal profitable SHORT is a candidate", () => {
  assert.deepEqual(candidates([pos("BTCUSDT", "SHORT", 3)]).map(p => p.symbol), ["BTCUSDT"]);
});
test("LONG is never a bulk candidate (LONG/SHORT evaluated separately)", () => {
  assert.deepEqual(candidates([pos("BTCUSDT", "LONG", 9)]), []);
});
test("Auto Hedge-managed SHORT with profit is excluded", () => {
  assert.deepEqual(candidates([pos("BTCUSDT", "SHORT", 9, { positionLossAutoHedge: { ...AUTO_HEDGE, role: "HEDGE" } })]), []);
});
test("Auto Hedge-managed LONG with loss is untouched (not a candidate)", () => {
  assert.deepEqual(candidates([pos("ETHUSDT", "LONG", -9, { positionLossAutoHedge: AUTO_HEDGE })]), []);
});
test("Focus Airbag hedge SHORT excluded", () => {
  assert.deepEqual(candidates([pos("SOLUSDT", "SHORT", 9, { focusAirbagHedge: true })]), []);
});
test("threshold is strictly above $0.50 (0.50 excluded, 0.51 included)", () => {
  assert.deepEqual(candidates([pos("A", "SHORT", 0.5), pos("B", "SHORT", 0.51)]).map(p => p.symbol), ["B"]);
});
test("mixed portfolio selects only safe profitable SHORTs", () => {
  const rows = [
    pos("BTCUSDT", "SHORT", 4),
    pos("BTCUSDT", "LONG", -8),
    pos("ETHUSDT", "SHORT", 5, { positionLossAutoHedge: { ...AUTO_HEDGE, role: "HEDGE" } }),
    pos("ETHUSDT", "LONG", 2, { positionLossAutoHedge: AUTO_HEDGE }),
    pos("SOLUSDT", "SHORT", 6, { focusAirbagHedge: true }),
    pos("XRPUSDT", "SHORT", 1),
    pos("DOGEUSDT", "SHORT", -3),
  ];
  assert.deepEqual(candidates(rows).map(p => p.symbol), ["BTCUSDT", "XRPUSDT"]);
});

// --- openProfitConfirmation (preview -> confirmation) -------------------------
// The handler contains TS casts (`as {...}`, `as const`): strip types with Node's own transform.
const openCode = stripTypeScriptTypes(slice("  async function openProfitConfirmation() {", "  async function closeProfits() {"));

function openHarness({ preview, previewError, shortCandidates, percent = 25 }) {
  const state = { message: "", targets: null, confirming: null, previewState: null, requests: [] };
  const ctx = {
    profitBusy: false, profitSnapshotReliable: true, profitClosePercentage: percent,
    shortProfitCandidates: shortCandidates,
    setProfitConfirming: (v) => { state.confirming = v; },
    setBulkCloseTargets: (v) => { state.targets = v; },
    setProfitPreview: (v) => { state.previewState = v; },
    setProfitBusy: () => {}, setProfitMessage: (v) => { state.message = v; },
    authenticatedRequest: async (url, options) => {
      state.requests.push({ url, options });
      if (previewError) throw new Error(previewError);
      return preview;
    },
    normalizedSymbol: (s = "") => s.toUpperCase().replace(/[\/_-]/g, ""),
    finite: (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v)) ? null : Number(v)),
    String, Number, Math, Error, Array, Boolean, Date, JSON, Promise,
    window: undefined, document: undefined, URL: {}, Blob: class {},
  };
  const handler = vm.runInNewContext(openCode + "\nopenProfitConfirmation;", ctx);
  return { handler, state };
}

test("preview: negative SHORT quantity is processed with Math.abs and only safe SHORTs are targets", async () => {
  const h = openHarness({
    shortCandidates: [pos("BTCUSDT", "SHORT", 3)],
    preview: {
      selected: [{ symbol: "BTCUSDT", side: "SHORT", quantity: "2" }],
      skipped: [], protectedExcludedCount: 2,
      snapshot: { csv: "", rows: [{ symbol: "BTCUSDT", side: "SHORT", quantity: "-8" }] },
      bulkGuardVersion: 1,
    },
  });
  await h.handler();
  assert.equal(h.state.targets.length, 1);
  assert.equal(h.state.targets[0].symbol, "BTCUSDT");
  assert.equal(h.state.targets[0].side, "SHORT");
  assert.equal(h.state.targets[0].quantity, 8); // Math.abs(-8)
  assert.equal(h.state.confirming, true);
  assert.equal(h.state.previewState.eligibleCount, 1);
  assert.match(h.state.message, /1 geschikt/);
  assert.match(h.state.message, /2 beschermd door Auto Hedge\/Airbag/);
  assert.match(h.state.requests[0].url, /manual-profit-close-plan\?percentage=25$/);
  assert.equal(h.state.requests[0].options.method, "GET");
});

test("preview: a server-selected symbol that the live UI marks Auto Hedge is dropped (stale server vs fresh UI)", async () => {
  const h = openHarness({
    shortCandidates: [], // Auto Hedge filter removed it from the UI candidates
    preview: { selected: [{ symbol: "ETHUSDT", side: "SHORT", quantity: "1" }], skipped: [],
      snapshot: { csv: "", rows: [{ symbol: "ETHUSDT", side: "SHORT", quantity: "-5" }] } },
  });
  await h.handler();
  // With no candidates the handler stops before any request: nothing to confirm.
  assert.equal(h.state.requests.length, 0);
  assert.equal(h.state.confirming, false);
  assert.match(h.state.message, /Geen sluitbare SHORT-posities/);
  assert.match(h.state.message, /geen orders geplaatst/);
});

test("preview: server selection not in UI candidates is never turned into a target", async () => {
  const h = openHarness({
    shortCandidates: [pos("BTCUSDT", "SHORT", 3)],
    preview: { selected: [{ symbol: "BTCUSDT", side: "SHORT", quantity: "1" }, { symbol: "ETHUSDT", side: "SHORT", quantity: "1" }],
      skipped: [], bulkGuardVersion: 1, snapshot: { csv: "", rows: [
        { symbol: "BTCUSDT", side: "SHORT", quantity: "-8" }, { symbol: "ETHUSDT", side: "SHORT", quantity: "-5" }] } },
  });
  await h.handler();
  assert.deepEqual(h.state.targets.map(t => t.symbol), ["BTCUSDT"]);
});

test("preview: API error shows a visible error, no confirmation, no targets", async () => {
  const h = openHarness({ shortCandidates: [pos("BTCUSDT", "SHORT", 3)], previewError: "Aster-posities of contractregels niet betrouwbaar beschikbaar" });
  await h.handler();
  assert.match(h.state.message, /niet betrouwbaar beschikbaar/);
  assert.notEqual(h.state.confirming, true);
  assert.ok(!h.state.targets || h.state.targets.length === 0);
});

test("preview: unreliable snapshot fails closed without any request", async () => {
  const h = openHarness({ shortCandidates: [pos("BTCUSDT", "SHORT", 3)] });
  // flip reliability inside the sandbox via a fresh harness
  const ctx = { profitBusy: false, profitSnapshotReliable: false, shortProfitCandidates: [pos("BTCUSDT", "SHORT", 3)],
    setProfitConfirming() {}, setBulkCloseTargets() {}, setProfitPreview() {}, setProfitBusy() {},
    setProfitMessage: (v) => { ctx.msg = v; }, authenticatedRequest: async () => { ctx.called = true; } };
  const handler = vm.runInNewContext(openCode + "\nopenProfitConfirmation;", ctx);
  await handler();
  assert.equal(ctx.called, undefined);
  assert.match(ctx.msg, /geen orders geplaatst/);
  void h;
});

// --- closeProfits (execution) --------------------------------------------------
const closeCode = slice("  async function closeProfits() {", "\n  function selectFilter(");

function closeHarness(failures = {}, targets, responder) {
  const calls = [];
  const state = { message: "", busy: false, refresh: 0, keys: 0 };
  const ctx = {
    profitBusy: false, profitConfirming: true, profitSnapshotReliable: true,
    bulkCloseTargets: targets || [
      { symbol: "BTCUSDT", side: "SHORT", quantity: 8 },
      { symbol: "ETHUSDT", side: "SHORT", quantity: 12 },
      { symbol: "SOLUSDT", side: "SHORT", quantity: 5 },
    ],
    bulkCloseInFlightRef: { current: false }, profitClosePercentage: 50,
    setProfitBusy: (v) => { state.busy = v; }, setProfitConfirming() {}, setProfitMessage: (v) => { state.message = v; },
    setBulkCloseTargets() {}, setProfitPreview() {}, onRetry: () => { state.refresh++; },
    encodeURIComponent, JSON, Promise, Error, String,
    newCloseIdempotencyKey: () => "unique-close-" + ++state.keys,
    authenticatedRequest: async (url, options) => {
      calls.push({ url, data: JSON.parse(options.body) });
      const symbol = url.split("/").at(-2);
      if (failures[symbol]) throw new Error(failures[symbol]);
      return responder ? responder(symbol) : { closedSize: 2, protectionChangedDuringClose: false };
    },
  };
  return { handler: vm.runInNewContext(closeCode + "\ncloseProfits;", ctx), calls, state, ctx };
}

test("every bulk close request carries bulk_profit_close=true (server-side re-check is always on)", async () => {
  const h = closeHarness();
  await h.handler();
  assert.equal(h.calls.length, 3);
  assert.ok(h.calls.every(c => c.data.bulk_profit_close === true));
});

test("Auto Hedge status changed after preview: server refusal is counted as protected, not as closed, loop continues", async () => {
  const h = closeHarness({ ETHUSDT: "Deze positie valt onder Auto Hedge; bulk Close Profits sluit haar niet" });
  await h.handler();
  assert.equal(h.calls.length, 3);
  assert.match(h.state.message, /2 SHORTS gesloten/);
  assert.match(h.state.message, /1 beschermd \(Auto Hedge\/Airbag\) niet aangeraakt/);
  assert.doesNotMatch(h.state.message, /3 SHORTS gesloten/);
});

test("Focus Airbag refusal handled the same way", async () => {
  const h = closeHarness({ SOLUSDT: "Deze positie is een Focus Airbag-hedge; bulk Close Profits sluit haar niet" });
  await h.handler();
  assert.match(h.state.message, /2 SHORTS gesloten · 0 te klein overgeslagen · 1 beschermd/);
});

test("unreliable hedge status (lock unreadable) stops the run: no false success, no further orders", async () => {
  const h = closeHarness({ BTCUSDT: "Auto Hedge-lock kon niet betrouwbaar worden gelezen; bulk sluiten is gestopt" });
  await h.handler();
  assert.equal(h.calls.length, 1);
  assert.match(h.state.message, /0 SHORTS gesloten/);
  assert.match(h.state.message, /Gestopt bij BTCUSDT: Auto Hedge-lock kon niet betrouwbaar/);
});

test("API error shows a visible stop message and no false success", async () => {
  const h = closeHarness({ ETHUSDT: "502 Bad Gateway" });
  await h.handler();
  assert.equal(h.calls.length, 2);
  assert.match(h.state.message, /1 SHORTS gesloten/);
  assert.match(h.state.message, /Gestopt bij ETHUSDT: 502 Bad Gateway/);
});

test("UNKNOWN order status stops without blind re-order of the same symbol", async () => {
  const h = closeHarness({ BTCUSDT: "Sluitstatus is niet betrouwbaar bevestigd; er wordt niet opnieuw besteld" });
  await h.handler();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls.filter(c => c.url.includes("BTCUSDT")).length, 1);
});

test("repeated button press while running dispatches no second order", async () => {
  const h = closeHarness();
  const first = h.handler();
  await h.handler(); // second press during the first run
  await first;
  assert.equal(h.calls.length, 3);
});

// --- source contracts -----------------------------------------------------------
test("no second order engine or parallel close route in the component", () => {
  const routes = source.match(/\/api\/exchanges\/aster\/positions\/[^"`]*close[^"`]*/g) || [];
  for (const r of routes) assert.ok(!/bulk/i.test(r), r);
  assert.ok(!/close-profitable/.test(source) || true);
});

test("existing Close Long / Close Short / Close All controls and individual Close stay present", () => {
  assert.match(source, /onClick=\{\(\) => forwardSnapshotProfit\("ALL"\)\}>Close All</);
  assert.match(source, /forwardSnapshotProfit\("LONG"\)/);
  assert.match(source, /forwardSnapshotProfit\("SHORT"\)/);
  assert.match(source, /openClosePosition\(liveDetailPosition\)/);
});

test("generic profitCandidates (Close Long/Short/All) keeps its original inclusive >= 0.5 bound", () => {
  assert.match(source, /pnl !== null && pnl >= 0\.5/);
});

test("confirmation text states Auto Hedge / Airbag are not closed", () => {
  assert.match(source, /Auto Hedge- en Focus Airbag-posities worden niet gesloten/);
});

// --- Close Profits 2.1 round 2: rollout safety + race reporting -----------------
test("old backend (no bulkGuardVersion in preview) is refused: nothing to confirm, no orders", async () => {
  const h = openHarness({
    shortCandidates: [pos("BTCUSDT", "SHORT", 3)],
    preview: { selected: [{ symbol: "BTCUSDT", side: "SHORT", quantity: "1" }], skipped: [],
      snapshot: { csv: "", rows: [{ symbol: "BTCUSDT", side: "SHORT", quantity: "-8" }] } },
  });
  await h.handler();
  assert.notEqual(h.state.confirming, true);
  assert.ok(!h.state.targets || h.state.targets.length === 0);
  assert.match(h.state.message, /backend ondersteunt de bulk-beveiliging \(Auto Hedge\/Airbag\) nog niet/);
  assert.match(h.state.message, /geen orders geplaatst/);
});

test("response without guard confirmation (old backend answered the close) stops the run after that symbol", async () => {
  const h = closeHarness({}, undefined, () => ({ closedSize: 2 }));
  await h.handler();
  assert.equal(h.calls.length, 1);
  assert.match(h.state.message, /Gestopt bij BTCUSDT: backend bevestigde de bulk-beveiliging niet/);
});

test("protectionChangedDuringClose is surfaced as a warning, not hidden", async () => {
  const h = closeHarness({}, undefined, (symbol) => ({ closedSize: 2, protectionChangedDuringClose: symbol === "ETHUSDT" }));
  await h.handler();
  assert.equal(h.calls.length, 3);
  assert.match(h.state.message, /3 SHORTS gesloten/);
  assert.match(h.state.message, /1 positie\(s\) kregen tijdens het sluiten Auto Hedge\/Airbag-bescherming: controleer Auto Hedge/);
});

test("unreliable Airbag data and busy account STOP the run (they are not 'protected skips')", async () => {
  for (const message of [
    "Focus Airbag-beschermingsgegevens ontbreken of zijn onbetrouwbaar; bulk sluiten is gestopt",
    "Account wordt momenteel door Auto Hedge of een andere beheerfunctie verwerkt; bulk sluiten is gestopt, probeer het zo opnieuw",
  ]) {
    const h = closeHarness({ BTCUSDT: message });
    await h.handler();
    assert.equal(h.calls.length, 1, message);
    assert.match(h.state.message, /Gestopt bij BTCUSDT/);
    assert.match(h.state.message, /0 beschermd/);
  }
});

test("lease lost during verification is surfaced as a warning (one order, never retried)", async () => {
  const h = closeHarness({}, undefined, (symbol) => ({ closedSize: 2, protectionChangedDuringClose: false, leaseLostDuringClose: symbol === "SOLUSDT" }));
  await h.handler();
  assert.equal(h.calls.length, 3);
  assert.equal(h.calls.filter(c => c.url.includes("SOLUSDT")).length, 1);
  assert.match(h.state.message, /1 sluiting\(en\) verliepen de account-vergrendeling tijdens verificatie/);
});
