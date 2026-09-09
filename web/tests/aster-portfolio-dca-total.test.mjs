import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { effectiveAsterDcaCount, totalAsterDca } from "../lib/aster-dca-count.mjs";

const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");

test("Aster active-trades index uses the same Multi BB runtime DCA count as Tradecentrum", () => {
  assert.match(page, /effectiveAsterDcaCount\(row, asRecord\(data\.strategy2\)\)/);
  const position = { symbol: "ICPUSDT", side: "LONG", quantity: 1, dcaCount: 2 };
  const strategy2 = { multiBbPositions: { "ICPUSDT|LONG": { dcaCount: 25 } } };
  assert.equal(effectiveAsterDcaCount(position, strategy2), 25);
});

test("Portfolio DCA total excludes initial entries and sums every confirmed DCA add", () => {
  const entries = [1, 1, 11, 11, 7, 1, 11, 10, 11, 5, 26, 28];
  const positions = entries.map((entryCount, index) => ({ symbol: `C${index}USDT`, side: "LONG", quantity: 1, dcaCount: 0 }));
  const multiBbPositions = Object.fromEntries(entries.map((entryCount, index) => [`C${index}USDT|LONG`, { dcaCount: entryCount - 1 }]));
  assert.equal(totalAsterDca(positions, { multiBbPositions }), 111);
});

test("runtime DCA falls back to the server position count when no managed runtime exists", () => {
  assert.equal(effectiveAsterDcaCount({ symbol: "BTCUSDT", side: "SHORT", dcaCount: 4 }, {}), 4);
});
