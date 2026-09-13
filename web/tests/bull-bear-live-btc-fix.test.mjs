import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const component = readFileSync(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8");
const videoCss = readFileSync(new URL("../components/portfolio-impact-bull-bear-video.module.css", import.meta.url), "utf8");
const btcRoute = readFileSync(new URL("../app/api/markets/aster/btc-bollinger/route.ts", import.meta.url), "utf8");
const mediaRoute = readFileSync(new URL("../app/api/media/bull-bear-master/route.ts", import.meta.url), "utf8");
const dockerfile = readFileSync(new URL("../Dockerfile", import.meta.url), "utf8");

test("Bull vs Bear BTC state is independent of positions and leverage enrichment", () => {
  assert.match(component, /\/api\/markets\/aster\/btc-bollinger\?interval=/);
  assert.doesNotMatch(component, /mode=enrich&symbols=BTCUSDT/);
  assert.doesNotMatch(component, /authenticatedRequest\("\/api\/markets\/aster"\)/);
  assert.match(component, /wss:\/\/fstream\.asterdex\.com\/ws\/btcusdt@markPrice@1s/);
  assert.match(btcRoute, /const SYMBOL = "BTCUSDT"/);
  assert.match(btcRoute, /fapi\/v1\/klines/);
  assert.match(btcRoute, /const livePrice = closes\.at\(-1\)/);
  assert.doesNotMatch(btcRoute, /leverage|positions|strategy2\/focus\/markets|close-all|strategy2\/start|strategy2\/stop/);
});

test("each timeframe keeps its own Bollinger bands while the same live mark price drives position", () => {
  assert.match(component, /timeframeToAsterInterval\(timeframe\)/);
  assert.match(component, /encodeURIComponent\(interval\)/);
  for (const interval of ["1m", "5m", "15m", "1h", "4h", "1d"]) {
    assert.match(btcRoute, new RegExp(`"${interval.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`));
  }
  assert.match(component, /livePrice && livePrice > 0 \? livePrice : bollinger\.price/);
  assert.match(component, /bollingerScore\(price, bollinger\.lower, bollinger\.upper\)/);
});

test("forward and reverse masters are range-served for normal film playback", () => {
  assert.match(component, /MASTER_SOURCE = "\/api\/media\/bull-bear-master\?v=3"/);
  assert.match(component, /REVERSE_SOURCE = "\/api\/media\/bull-bear-master\?direction=reverse&v=3"/);
  assert.match(mediaRoute, /FORWARD_FILE_PATH/);
  assert.match(mediaRoute, /REVERSE_FILE_PATH/);
  assert.match(mediaRoute, /filePathFor\(request\)/);
  assert.match(mediaRoute, /"Content-Type": "video\/mp4"/);
  assert.match(mediaRoute, /"Accept-Ranges": "bytes"/);
  assert.match(mediaRoute, /"Content-Range": `bytes \$\{range\.start\}-\$\{range\.end\}\/\$\{info\.size\}`/);
  assert.match(mediaRoute, /status: 206/);
  assert.match(mediaRoute, /status: 416/);
  assert.match(dockerfile, /ffmpeg/);
  assert.match(dockerfile, /portfolio-impact-bull-bear-master-reverse\.mp4/);
});

test("primary visible motion is playback, not per-frame score scrubbing", () => {
  assert.match(component, /nextVideo\.playbackRate = playbackRate/);
  assert.match(component, /void nextVideo\.play\(\)\.catch/);
  assert.match(component, /void activeVideo\.play\(\)\.catch/);
  assert.doesNotMatch(component, /video\.currentTime = targetTime/);
  assert.doesNotMatch(component, /seek\(nextMarketScore\)|seek\(targetScore\)/);
});

test("direction switches are atomic and never opacity-crossfade through the poster", () => {
  assert.doesNotMatch(videoCss, /transition:\s*opacity/i);
  assert.match(videoCss, /\.videoActive\s*\{[^}]*opacity:\s*1/s);
  assert.match(videoCss, /\.videoInactive\s*\{[^}]*opacity:\s*0/s);
});
