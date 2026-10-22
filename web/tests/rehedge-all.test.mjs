import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { outcomeLabel, recoveryPairs, summarizeRehedgeAll } from "../lib/rehedge-all.mjs";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("Re-Hedge All sits directly left of 25% and the close percentages are unchanged", async () => {
  const source = await read("../components/aster-recent-trades.tsx");
  const row = source.slice(source.indexOf('aria-label="Percentage winstposities sluiten"'));
  const button = row.indexOf("<RehedgeAllButton />");
  const percentages = row.indexOf("([25,50,75,100] as const).map");
  assert.ok(button > 0 && percentages > button, "button must precede the 25/50/75/100 buttons");
  assert.match(row.slice(0, 400), /gridTemplateColumns:"minmax\(0,1\.7fr\) repeat\(4,minmax\(0,1fr\)\)"/);
  assert.doesNotMatch(row.slice(0, 400), /overflowX|overflow-x|nowrap.*scroll/);
  assert.match(source, /onClick=\{\(\) => setProfitClosePercentage\(percentage\)\}/);
  assert.match(source, /Close \$\{shortProfitCandidates\.length\} SHORT profits/);
});

test("the component sends exactly one server request and has no order, size or hedge logic", async () => {
  const component = await read("../components/aster-rehedge-all.tsx");
  const posts = component.match(/method: "POST"/g) || [];
  assert.equal(posts.length, 1);
  assert.match(component, /\/api\/exchanges\/aster\/position-loss-auto-hedge\/rehedge-all/);
  assert.match(component, /confirm: true/);
  assert.doesNotMatch(component, /\/rehedge`|\/close"|expected_quantity|positionAmt|quantity \*|submit_order/);
  assert.match(component, /const inFlight = useRef\(false\)/);
  assert.match(component, /if \(inFlight\.current\) return;/);
  assert.match(component, /"Re-Hedging…" : "Re-Hedge All"/);
  assert.match(component, /Re-Hedge All afgerond/);
  assert.match(component, /nooit groter dan de LONG/);
});

test("proxy route forwards to the backend bulk endpoint only", async () => {
  const route = await read("../app/api/exchanges/aster/position-loss-auto-hedge/rehedge-all/route.ts");
  assert.match(route, /proxyCloud\(request, "\/v1\/me\/aster\/position-loss-auto-hedge\/rehedge-all", "POST"\)/);
  assert.doesNotMatch(route, /export async function (GET|PUT|DELETE)/);
});

test("only Recovery statuses count as candidates", () => {
  const pairs = ["HEDGED", "RECOVERY", "REHEDGE_ARMED", "DISABLED", "CLOSED", "HEDGING", "MANUAL_RELEASE_UNCERTAIN"]
    .map((status, i) => ({ symbol: `S${i}USDT`, status }));
  assert.deepEqual(recoveryPairs(pairs).map((p) => p.status), ["RECOVERY", "REHEDGE_ARMED", "DISABLED", "MANUAL_RELEASE_UNCERTAIN"]);
  assert.deepEqual(recoveryPairs(null), []);
});

test("summary groups outcomes and never claims protection that the server did not confirm", () => {
  const summary = summarizeRehedgeAll({
    found: 6, ordersSent: 3, mode: "LIVE",
    items: [
      { symbol: "ICPUSDT", outcome: "PROTECTED", longNotional: 150, shortNotionalBefore: 0, shortNotionalAfter: 150, hedgePercent: 100 },
      { symbol: "INJUSDT", outcome: "PARTIAL", longNotional: 150, shortNotionalBefore: 40, shortNotionalAfter: 100, hedgePercent: 66.666 },
      { symbol: "INTCUSDT", outcome: "SKIPPED", reason: "OVER_HEDGED" },
      { symbol: "KORUUSDT", outcome: "TOO_SMALL" },
      { symbol: "NATGASUSDT", outcome: "UNKNOWN" },
      { symbol: "AAOIUSDT", outcome: "QUEUED" },
    ],
  });
  assert.deepEqual([summary.found, summary.protected, summary.busy, summary.skipped, summary.attention], [6, 1, 2, 2, 1]);
  assert.equal(summary.rows[0].symbol, "ICP");
  assert.equal(summary.rows[0].longNotional, "$150,00");
  assert.equal(summary.rows[1].hedgePercent, "66.6%");                          // floored, never rounded up
  assert.match(summary.rows[2].label, /SHORT is al groter dan de LONG/);
  assert.match(outcomeLabel({ outcome: "UNKNOWN" }), /nooit dubbel/);
  assert.equal(summarizeRehedgeAll({ mode: "SHADOW", items: [] }).testMode, true);
});
