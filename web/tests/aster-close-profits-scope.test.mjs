import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

const source = fs.readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const start = source.indexOf("  async function closeProfits() {");
const end = source.indexOf("\n  function selectFilter(", start);
const handlerCode = source.slice(start, end);

function run(failures = {}) {
  const calls = [];
  const ctx = {
    profitBusy: false, profitConfirming: true, profitSnapshotReliable: true, profitClosePercentage: 25,
    bulkCloseTargets: [{ symbol: "BTCUSDT", side: "SHORT", quantity: 8 }, { symbol: "ETHUSDT", side: "SHORT", quantity: 12 }],
    bulkCloseInFlightRef: { current: false }, message: "",
    setProfitBusy() {}, setProfitConfirming() {}, setProfitMessage(v) { ctx.message = v; }, setBulkCloseTargets() {},
    setProfitPreview() {}, onRetry() {}, encodeURIComponent, JSON, Promise, Error, String, n: 0, setTimeout: (fn) => fn(),
    newCloseIdempotencyKey: () => "key-" + ++ctx.n,
    authenticatedRequest: async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body), method: options.method });
      const symbol = url.split("/").at(-2);
      if (failures[symbol]) throw new Error(failures[symbol]);
      return { closedSize: 2, autoHedgeStatus: "RECOVERY" };
    },
  };
  return { handler: vm.runInNewContext(handlerCode + "\ncloseProfits;", ctx), calls, ctx };
}

test("each SHORT goes through the existing individual close route with exactly the individual body", async () => {
  const h = run();
  await h.handler();
  assert.deepEqual(h.calls.map((c) => c.url), [
    "/api/exchanges/aster/positions/BTCUSDT/close", "/api/exchanges/aster/positions/ETHUSDT/close"]);
  for (const [i, call] of h.calls.entries()) {
    assert.deepEqual(Object.keys(call.body).sort(), ["confirm", "expected_quantity", "idempotency_key", "percentage", "side"]);
    assert.equal(call.body.side, "SHORT");
    assert.equal(call.body.percentage, 25);
    assert.equal(call.body.expected_quantity, [8, 12][i]);       // full live quantity, backend computes the partial
  }
  assert.equal(new Set(h.calls.map((c) => c.body.idempotency_key)).size, 2);
});

test("a hedge-status consequence of the individual route never stops or alters the run", async () => {
  const h = run();
  await h.handler();
  assert.match(h.ctx.message, /2 SHORTS gesloten/);
});

test("too-small order is skipped, unknown outcome stops the series", async () => {
  let h = run({ BTCUSDT: "De gekozen gedeeltelijke sluiting is te klein voor dit contract" });
  await h.handler();
  assert.equal(h.calls.length, 2);
  assert.match(h.ctx.message, /1 SHORTS gesloten · 1 te klein overgeslagen/);
  h = run({ BTCUSDT: "Sluitstatus is niet betrouwbaar bevestigd; er wordt niet opnieuw besteld" });
  await h.handler();
  assert.equal(h.calls.length, 1);
  assert.match(h.ctx.message, /Gestopt bij BTCUSDT/);
});

test("handler has no hedge/Recovery/Auto Hedge logic of its own", () => {
  assert.doesNotMatch(handlerCode, /Recovery|rehedge|bulk_profit_close|lease|firestore/i);
  assert.equal((handlerCode.match(/Auto Hedge/g) || []).length, 3);   // only comment + the two pre-order refusal patterns
});

test("confirmation modal shows the Auto Hedge consequence and keeps Focus Airbag hedges out", () => {
  assert.match(source, /data-testid="bulk-auto-hedge-warning"/);
  assert.match(source, /het paar gaat daarna in Recovery[\s\S]{0,200}re-hedge blijft UIT/);
  assert.match(source, /position\?\.focusAirbagHedge !== true/);
});

test("real ContractRules minimum refusals are skipped; other contract errors still stop", async () => {
  for (const msg of [
    "Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: Order ligt onder de minimale Aster-hoeveelheid",
    "Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: Order ligt onder de minimale Aster-orderwaarde",
    "Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: Hoeveelheid en marktprijs moeten positief zijn"]) {
    const h = run({ BTCUSDT: msg });
    await h.handler();
    assert.equal(h.calls.length, 2, msg);
    assert.match(h.ctx.message, /1 SHORTS gesloten · 1 te klein overgeslagen/);
  }
  const h = run({ BTCUSDT: "Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: Order ligt boven de maximale Aster-hoeveelheid" });
  await h.handler();
  assert.equal(h.calls.length, 1);
  assert.match(h.ctx.message, /Gestopt bij BTCUSDT/);
});

test("account-lease busy refusal retries at most 3 times with a NEW key, then stops; nothing else is retried", async () => {
  const busy = "Auto Hedge verwerkt momenteel dezelfde accountstatus; probeer de sluiting zo opnieuw";
  let h = run({ BTCUSDT: busy });
  await h.handler();
  assert.equal(h.calls.filter((c) => c.url.includes("BTCUSDT")).length, 4);   // 1 + 3 retries
  assert.equal(new Set(h.calls.map((c) => c.body.idempotency_key)).size, h.calls.length);
  assert.equal(h.calls.some((c) => c.url.includes("ETHUSDT")), false);        // series stopped
  h = run({ BTCUSDT: "Sluitstatus is niet betrouwbaar bevestigd; er wordt niet opnieuw besteld" });
  await h.handler();
  assert.equal(h.calls.length, 1);                                            // UNKNOWN is never retried
  h = run({ BTCUSDT: "TradeMentor Cloud is tijdelijk niet bereikbaar" });
  await h.handler();
  assert.equal(h.calls.length, 1);                                            // network/proxy loss is never retried
});
