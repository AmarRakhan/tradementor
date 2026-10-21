import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

const source = fs.readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const start = source.indexOf("  async function closeProfits() {");
const end = source.indexOf("\n  function selectFilter(", start);
assert.ok(start !== -1 && end > start, "central CLOSE handler exists");
const handlerCode = source.slice(start, end);

function harness(percent, failures = {}) {
  const calls = [];
  const state = { message: "", busy: false, refresh: 0, keys: 0 };
  const targets = [
    { symbol: "BTCUSDT", side: "SHORT", quantity: 8 },
    { symbol: "ETHUSDT", side: "SHORT", quantity: 12 },
    { symbol: "SOLUSDT", side: "SHORT", quantity: 5 },
  ];
  const ctx = {
    profitBusy: false, profitConfirming: true, profitSnapshotReliable: true,
    bulkCloseTargets: targets, bulkCloseInFlightRef: { current: false },
    profitClosePercentage: percent,
    setProfitBusy: (v) => { state.busy = v; },
    setProfitConfirming: () => {},
    setProfitMessage: (v) => { state.message = v; },
    setBulkCloseTargets: () => {},
    setProfitPreview: () => {},
    onRetry: () => { state.refresh++; },
    encodeURIComponent, JSON, Promise, Error, String,
    newCloseIdempotencyKey: () => "unique-close-" + ++state.keys,
    authenticatedRequest: async (url, options) => {
      if (url.includes("manual-profit-close-plan")) {
        return { reliable: true, selected: targets.map((t) => ({ symbol: t.symbol, side: "SHORT" })),
                 snapshot: { rows: targets.map((t) => ({ symbol: t.symbol, side: "SHORT", quantity: String(t.quantity), unrealizedPnl: "1.25" })) } };
      }
      calls.push({ url, options, data: JSON.parse(options.body) });
      const symbol = url.split("/").at(-2);
      if (failures[symbol]) throw new Error(failures[symbol]);
      return { closedSize: 2, autoHedgeStatus: "RECOVERY" };
    },
  };
  const handler = vm.runInNewContext(handlerCode + "\ncloseProfits;", ctx);
  return { handler, calls, state, ctx };
}

for (const percentage of [25, 50, 75, 100]) {
  test("SHORT bulk uses existing individual route once per symbol at " + percentage + "%", async () => {
    const h = harness(percentage);
    await h.handler();
    assert.deepEqual(h.calls.map(c => c.url), [
      "/api/exchanges/aster/positions/BTCUSDT/close",
      "/api/exchanges/aster/positions/ETHUSDT/close",
      "/api/exchanges/aster/positions/SOLUSDT/close",
    ]);
    assert.deepEqual(h.calls.map(c => c.data.side), ["SHORT", "SHORT", "SHORT"]);
    assert.deepEqual(h.calls.map(c => c.data.percentage), [percentage, percentage, percentage]);
    assert.deepEqual(h.calls.map(c => c.data.expected_quantity), [8, 12, 5]);
    assert.equal(new Set(h.calls.map(c => c.data.idempotency_key)).size, 3);
    assert.ok(h.calls.every(c => c.data.confirm === true && c.options.method === "POST"));
    assert.equal(h.state.refresh, 1);
    assert.match(h.state.message, /3 SHORTS gesloten/);
    assert.equal(h.ctx.bulkCloseInFlightRef.current, false);
  });
}

test("confirmed pre-submit minimum order error skips one SHORT and continues", async () => {
  const h = harness(25, { ETHUSDT: "De gekozen gedeeltelijke sluiting is te klein voor dit contract" });
  await h.handler();
  assert.equal(h.calls.length, 3);
  assert.match(h.state.message, /2 SHORTS gesloten · 1 te klein overgeslagen/);
});

test("broad Aster contract validation error stops instead of skipping", async () => {
  const h = harness(25, { ETHUSDT: "Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: invalid filter" });
  await h.handler();
  assert.equal(h.calls.length, 2);
  assert.match(h.state.message, /Gestopt bij ETHUSDT/);
  assert.doesNotMatch(h.state.message, /1 te klein overgeslagen/);
});

test("UNKNOWN stops after failed SHORT without submitting the next", async () => {
  const h = harness(50, { ETHUSDT: "timeout UNKNOWN order status" });
  await h.handler();
  assert.deepEqual(h.calls.map(c => c.data.side), ["SHORT", "SHORT"]);
  assert.equal(h.calls.length, 2);
  assert.match(h.state.message, /Gestopt bij ETHUSDT/);
});

test("synchronous in-flight guard prevents simultaneous duplicate dispatch", async () => {
  const h = harness(25);
  await Promise.all([h.handler(), h.handler()]);
  assert.equal(h.calls.length, 3);
});

test("preview selection is STRICTLY profitable SHORT only", () => {
  assert.match(source, /return \(side === "LONG" \|\| side === "SHORT"\) && pnl !== null && pnl >= 0\.5/);
  assert.match(source, /const shortProfitCandidates = useMemo/);
  assert.match(source, /String\(position\.side \|\| ""\)\.toUpperCase\(\) === "SHORT" && \(finite\(position\.unrealizedPnl\) \|\| 0\) > 0\.5/);
  assert.match(source, /return side === "SHORT" && position\?\.focusAirbagHedge !== true/);
});
