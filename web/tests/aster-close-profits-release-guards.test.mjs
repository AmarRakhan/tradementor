// Release guards: server-side profit check, series lock for unconfirmed closes, lease-expiry refusal (frontend side).
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

const source = fs.readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const start = source.indexOf("  async function closeProfits() {");
const end = source.indexOf("\n  function selectFilter(", start);
const handlerCode = source.slice(start, end);
const PNL_GONE = "Open winst is niet meer boven de ingestelde grens; geen order geplaatst";
const PNL_UNREADABLE = "Open winst is niet betrouwbaar leesbaar; sluiten is gestopt";
const UNCONFIRMED = "Vorige sluiting van dit symbool is nog niet bevestigd; controleer Aster en gebruik de individuele Close-knop";
const LEASE = "De account-lease is verlopen voordat de sluiting kon starten; er is niets geplaatst, probeer opnieuw";

function harness({ targets, posts = {} }) {
  const calls = [];
  const state = { message: "", keys: 0, waits: 0 };
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
    onRetry: () => {},
    encodeURIComponent, JSON, Promise, Error, String, Number, Math, Array,
    setTimeout: (fn) => { state.waits++; fn(); },
    newCloseIdempotencyKey: () => "k" + ++state.keys,
    authenticatedRequest: async (url, options) => {
      if (url.includes("manual-profit-close-plan")) return healthy();
      const symbol = url.split("/").at(-2);
      const n = calls.filter((c) => c.symbol === symbol).length;
      calls.push({ symbol, data: JSON.parse(options.body) });
      const step = (posts[symbol] || [])[n];
      if (step instanceof Error) throw step;
      return { closedSize: 1 };
    },
  };
  const handler = vm.runInNewContext(handlerCode + "\ncloseProfits;", ctx);
  return { handler, calls, state };
}
const TWO = [{ symbol: "BTCUSDT", quantity: 8 }, { symbol: "ETHUSDT", quantity: 3 }];

test("every close request carries the server-side safeguards and the FULL live quantity", async () => {
  const h = harness({ targets: TWO });
  await h.handler();
  assert.equal(h.calls.length, 2);
  for (const c of h.calls) {
    assert.equal(c.data.min_open_pnl_usd, 0.5);
    assert.equal(c.data.bulk_series, true);
    assert.equal(c.data.side, "SHORT");
    assert.equal(c.data.confirm, true);
  }
  assert.deepEqual(h.calls.map((c) => c.data.expected_quantity), [8, 3]);
});

test("server says profit fell to the limit -> counted as skipped, no retry, series continues", async () => {
  const h = harness({ targets: TWO, posts: { BTCUSDT: [new Error(PNL_GONE)] } });
  await h.handler();
  assert.deepEqual(h.calls.map((c) => c.symbol), ["BTCUSDT", "ETHUSDT"]);
  assert.match(h.state.message, /1 SHORTS gesloten/);
  assert.match(h.state.message, /1 niet meer boven \$0,50 winst/);
  assert.doesNotMatch(h.state.message, /Gestopt/);
});

test("server cannot read the profit -> the whole series stops", async () => {
  const h = harness({ targets: TWO, posts: { BTCUSDT: [new Error(PNL_UNREADABLE)] } });
  await h.handler();
  assert.deepEqual(h.calls.map((c) => c.symbol), ["BTCUSDT"]);
  assert.match(h.state.message, /Gestopt bij BTCUSDT/);
});

test("earlier close of the symbol is unconfirmed -> that SHORT is skipped and reported, others continue", async () => {
  const h = harness({ targets: TWO, posts: { BTCUSDT: [new Error(UNCONFIRMED)] } });
  await h.handler();
  assert.deepEqual(h.calls.map((c) => c.symbol), ["BTCUSDT", "ETHUSDT"]);
  assert.match(h.state.message, /1 overgeslagen: eerdere sluiting nog niet bevestigd/);
  assert.doesNotMatch(h.state.message, /Gestopt/);
});

test("expired lease (nothing was ordered) is retried with a NEW key, at most three times", async () => {
  const once = harness({ targets: [TWO[0]], posts: { BTCUSDT: [new Error(LEASE)] } });
  await once.handler();
  assert.equal(once.calls.length, 2);
  assert.notEqual(once.calls[0].data.idempotency_key, once.calls[1].data.idempotency_key);
  assert.doesNotMatch(once.state.message, /Gestopt/);
  const always = harness({ targets: TWO, posts: { BTCUSDT: [new Error(LEASE), new Error(LEASE), new Error(LEASE), new Error(LEASE)] } });
  await always.handler();
  assert.equal(always.calls.filter((c) => c.symbol === "BTCUSDT").length, 4);
  assert.equal(always.calls.filter((c) => c.symbol === "ETHUSDT").length, 0);
  assert.match(always.state.message, /Gestopt bij BTCUSDT/);
});

test("UNKNOWN / 502 still stops immediately and is never retried", async () => {
  const h = harness({ targets: TWO, posts: { BTCUSDT: [new Error("Sluitstatus is niet betrouwbaar bevestigd; er wordt niet opnieuw besteld")] } });
  await h.handler();
  assert.deepEqual(h.calls.map((c) => c.symbol), ["BTCUSDT"]);
  assert.match(h.state.message, /Gestopt bij BTCUSDT/);
});
