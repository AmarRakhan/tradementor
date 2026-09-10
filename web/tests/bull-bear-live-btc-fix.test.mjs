import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const component = readFileSync(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8");
const btcRoute = readFileSync(new URL("../app/api/markets/aster/btc-bollinger/route.ts", import.meta.url), "utf8");
const mediaRoute = readFileSync(new URL("../app/api/media/bull-bear-master/route.ts", import.meta.url), "utf8");

test("Bull vs Bear BTC state is independent of positions and leverage enrichment", () => {
  assert.match(component, /\/api\/markets\/aster\/btc-bollinger\?interval=/);
  assert.doesNotMatch(component, /mode=enrich&symbols=BTCUSDT/);
  assert.doesNotMatch(component, /authenticatedRequest\("\/api\/markets\/aster"\)/);
  assert.match(btcRoute, /const SYMBOL = "BTCUSDT"/);
  assert.match(btcRoute, /fapi\/v1\/klines/);
  assert.match(btcRoute, /const livePrice = closes\.at\(-1\)/);
  assert.doesNotMatch(btcRoute, /leverage|positions|strategy2\/focus\/markets|close-all|strategy2\/start|strategy2\/stop/);
});

test("each timeframe is calculated from its own BTC Bollinger request", () => {
  assert.match(component, /timeframeToAsterInterval\(timeframe\)/);
  assert.match(component, /encodeURIComponent\(interval\)/);
  for (const interval of ["1m", "5m", "15m", "1h", "4h", "1d"]) {
    assert.match(btcRoute, new RegExp(`"${interval.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`));
  }
  assert.match(btcRoute, /\(\(price - lower\) \/ \(upper - lower\)\) \* 100/);
});

test("master video is served as MP4 with byte-range support for mobile scrubbing", () => {
  assert.match(component, /MASTER_SOURCE = "\/api\/media\/bull-bear-master\?v=2"/);
  assert.match(mediaRoute, /"Content-Type": "video\/mp4"/);
  assert.match(mediaRoute, /"Accept-Ranges": "bytes"/);
  assert.match(mediaRoute, /"Content-Range": `bytes \$\{range\.start\}-\$\{range\.end\}\/\$\{info\.size\}`/);
  assert.match(mediaRoute, /status: 206/);
  assert.match(mediaRoute, /status: 416/);
});
