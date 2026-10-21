// Round 6: fail-closed fresh check before EVERY close attempt (first try and each account-busy retry).
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

const source = fs.readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const start = source.indexOf("  async function closeProfits() {");
const end = source.indexOf("\n  function selectFilter(", start);
const handlerCode = source.slice(start, end);
const BUSY = "Auto Hedge verwerkt momenteel dezelfde accountstatus; probeer de sluiting zo opnieuw";

// previews: array of functions (n-th preview call) -> response object (or throws). Default: healthy.
function harness({ targets, previews = [], posts = {} }) {
  const calls = [], previewCalls = [];
  const state = { message: "", refresh: 0, keys: 0 };
  const healthy = () => ({
    reliable: true,
    selected: targets.map((t) => ({ symbol: t.symbol, side: "SHORT" })),
    snapshot: { rows: targets.map((t) => ({ symbol: t.symbol, side: "SHORT", quantity: String(t.quantity), unrealizedPnl: "1.25" })) },
  });
  const ctx = {
    profitBusy: false, profitConfirming: true, profitSnapshotReliable: true,
    bulkCloseTargets: targets, bulkCloseInFlightRef: { current: false }, profitClosePercentage: 50,
    setProfitBusy: () => {}, setProfitConfirming: () => {},
    setProfitMessage: (v) => { state.message = v; }, setBulkCloseTargets: () => {}, setProfitPreview: () => {},
    onRetry: () => { state.refresh++; },
    encodeURIComponent, JSON, Promise, Error, String, Number, Math, Array,
    setTimeout: (fn) => fn(), // no real 1.5 s wait in tests
    newCloseIdempotencyKey: () => "k" + ++state.keys,
    authenticatedRequest: async (url, options) => {
      if (url.includes("manual-profit-close-plan")) {
        const n = previewCalls.length; previewCalls.push(url);
        const f = previews[n];
        return f ? f(healthy()) : healthy();
      }
      const symbol = url.split("/").at(-2);
      const n = calls.filter((c) => c.symbol === symbol).length;
      calls.push({ symbol, data: JSON.parse(options.body) });
      const script = posts[symbol] || [];
      const step = script[n];
      if (step instanceof Error) throw step;
      return { closedSize: 1 };
    },
  };
  const handler = vm.runInNewContext(handlerCode + "\ncloseProfits;", ctx);
  return { handler, calls, previewCalls, state };
}
const T = [{ symbol: "BTCUSDT", quantity: 8 }];
const drop = (res) => { res.snapshot.rows = []; return res; };

test("selected but position missing from snapshot -> stop BEFORE any order", async () => {
  const h = harness({ targets: T, previews: [drop] });
  await h.handler();
  assert.equal(h.calls.length, 0);
  assert.match(h.state.message, /Gestopt bij BTCUSDT/);
});
test("duplicate / contradictory position rows -> stop before order", async () => {
  const dup = (res) => { res.snapshot.rows.push({ ...res.snapshot.rows[0] }); return res; };
  const h = harness({ targets: T, previews: [dup] });
  await h.handler();
  assert.equal(h.calls.length, 0);
  assert.match(h.state.message, /Gestopt bij BTCUSDT/);
});
test("unreadable snapshot shape (rows not an array / reliable missing) -> stop", async () => {
  for (const mut of [(r) => { r.snapshot.rows = null; return r; }, (r) => { delete r.snapshot; return r; }, (r) => { r.reliable = false; return r; }, (r) => { r.selected = null; return r; }]) {
    const h = harness({ targets: T, previews: [mut] });
    await h.handler();
    assert.equal(h.calls.length, 0);
    assert.match(h.state.message, /Gestopt bij BTCUSDT/);
  }
});
test("selected but row profit <= 0.50 or unreadable -> stop (contradiction), no order", async () => {
  for (const pnl of ["0.50", "0.49", "abc", undefined]) {
    const m = (r) => { r.snapshot.rows[0].unrealizedPnl = pnl; return r; };
    const h = harness({ targets: T, previews: [m] });
    await h.handler();
    assert.equal(h.calls.length, 0, String(pnl));
    assert.match(h.state.message, /Gestopt bij BTCUSDT/);
  }
});
test("not selected anymore (profit gone) -> skipped without order, series continues", async () => {
  const two = [{ symbol: "BTCUSDT", quantity: 8 }, { symbol: "ETHUSDT", quantity: 3 }];
  const gone = (r) => { r.selected = r.selected.filter((s) => s.symbol !== "BTCUSDT"); return r; };
  const h = harness({ targets: two, previews: [gone] });
  await h.handler();
  assert.deepEqual(h.calls.map((c) => c.symbol), ["ETHUSDT"]);
  assert.match(h.state.message, /1 niet meer boven \$0,50 winst/);
});
test("retry: profit re-checked after the busy wait; profit gone -> NO second POST", async () => {
  const gone = (r) => { r.selected = []; return r; };
  const h = harness({ targets: T, previews: [undefined, gone], posts: { BTCUSDT: [new Error(BUSY)] } });
  await h.handler();
  assert.equal(h.calls.length, 1);
  assert.equal(h.previewCalls.length, 2);
  assert.match(h.state.message, /niet meer boven \$0,50 winst/);
});
test("retry: quantity changed during the wait -> stop, NO second POST", async () => {
  const changed = (r) => { r.snapshot.rows[0].quantity = "7"; return r; };
  const h = harness({ targets: T, previews: [undefined, changed], posts: { BTCUSDT: [new Error(BUSY)] } });
  await h.handler();
  assert.equal(h.calls.length, 1);
  assert.match(h.state.message, /Gestopt bij BTCUSDT.*positiegrootte/);
});
test("retry: preview fails during the wait -> stop, NO second POST", async () => {
  const boom = () => { throw new Error("netwerk"); };
  const h = harness({ targets: T, previews: [undefined, boom], posts: { BTCUSDT: [new Error(BUSY)] } });
  await h.handler();
  assert.equal(h.calls.length, 1);
  assert.match(h.state.message, /Gestopt bij BTCUSDT/);
});
test("retry happy path: busy x2 then success, fresh check before each of 3 POSTs, new key each time, full quantity", async () => {
  const h = harness({ targets: T, posts: { BTCUSDT: [new Error(BUSY), new Error(BUSY)] } });
  await h.handler();
  assert.equal(h.calls.length, 3);
  assert.equal(h.previewCalls.length, 3);
  assert.equal(new Set(h.calls.map((c) => c.data.idempotency_key)).size, 3);
  assert.ok(h.calls.every((c) => c.data.expected_quantity === 8));
  assert.match(h.state.message, /1 SHORTS gesloten/);
});
test("max three busy retries (4 POSTs total), then stop", async () => {
  const h = harness({ targets: T, posts: { BTCUSDT: [new Error(BUSY), new Error(BUSY), new Error(BUSY), new Error(BUSY), new Error(BUSY)] } });
  await h.handler();
  assert.equal(h.calls.length, 4);
  assert.match(h.state.message, /Gestopt bij BTCUSDT/);
});
test("UNKNOWN after a busy retry is never repeated", async () => {
  const h = harness({ targets: T, posts: { BTCUSDT: [new Error(BUSY), new Error("Sluitstatus is niet betrouwbaar bevestigd; er wordt niet opnieuw besteld")] } });
  await h.handler();
  assert.equal(h.calls.length, 2);
  assert.match(h.state.message, /Gestopt bij BTCUSDT/);
});
