import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const component = readFileSync(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../components/portfolio-impact-battle.module.css", import.meta.url), "utf8");
const videoCss = readFileSync(new URL("../components/portfolio-impact-bull-bear-video.module.css", import.meta.url), "utf8");
const btcRoute = readFileSync(new URL("../app/api/markets/aster/btc-bollinger/route.ts", import.meta.url), "utf8");
const mediaRoute = readFileSync(new URL("../app/api/media/bull-bear-master/route.ts", import.meta.url), "utf8");
const dockerfile = readFileSync(new URL("../Dockerfile", import.meta.url), "utf8");

test("Bull vs Bear keeps the premium master movie but uses normal bidirectional playback", () => {
  assert.match(component, /MASTER_SOURCE = "\/api\/media\/bull-bear-master\?v=3"/);
  assert.match(component, /REVERSE_SOURCE = "\/api\/media\/bull-bear-master\?direction=reverse&v=3"/);
  assert.match(component, /POSTER_SOURCE = "\/portfolio-impact-bull-bear-neutral\.webp"/);
  assert.match(component, /forwardVideoRef/);
  assert.match(component, /reverseVideoRef/);
  assert.match(component, /\.play\(\)/);
  assert.match(component, /playbackRate/);
  assert.doesNotMatch(component, /video\.currentTime = targetTime/);
  assert.match(mediaRoute, /REVERSE_FILE_PATH/);
  assert.match(mediaRoute, /direction.*reverse/);
  assert.match(dockerfile, /portfolio-impact-bull-bear-master-reverse\.mp4/);
  assert.match(dockerfile, /-vf "reverse,fps=30/);
  assert.match(videoCss, /\.videoActive/);
  assert.match(videoCss, /\.videoInactive/);
});

test("Bull vs Bear motion is driven only by independent read-only BTC Bollinger market data", () => {
  assert.match(component, /\/api\/markets\/aster\/btc-bollinger\?interval=/);
  assert.match(component, /timeframeToAsterInterval\(timeframe\)/);
  assert.match(component, /wss:\/\/fstream\.asterdex\.com\/ws\/btcusdt@markPrice@1s/);
  assert.match(component, /bollingerScore\(price, bollinger\.lower, bollinger\.upper\)/);
  assert.match(btcRoute, /const SYMBOL = "BTCUSDT"/);
  assert.match(btcRoute, /fapi\/v1\/klines/);
  assert.doesNotMatch(component, /mode=enrich|symbols=BTCUSDT|authenticatedRequest\("\/api\/markets\/aster"\)/);
  assert.doesNotMatch(component, /\/start|\/stop|\/close-all|\/positions\/close|snapshot-close-profitable/);
  assert.doesNotMatch(btcRoute, /leverage|positions|strategy2\/focus\/markets|close-all|strategy2\/start|strategy2\/stop/);
});

test("visual state keeps the existing transparent Portfolio Impact overlay above the movie", () => {
  assert.match(component, /PORTFOLIO IMPACT/);
  assert.match(component, /Open P&amp;L/);
  assert.match(component, /positionCount/);
  assert.match(component, /styles\.vignette/);
  assert.match(videoCss, /position:\s*absolute/);
  const side = css.match(/\.sidePanel\{[^}]+\}/)?.[0] || "";
  assert.match(side, /background:transparent!important/);
  assert.match(side, /backdrop-filter:none!important/);
  assert.match(side, /border:0!important/);
});

test("pressure bar remains visually embedded in the stone footer zone", () => {
  const footer = css.match(/\.battleFooter\{[^}]+\}/)?.[0] || "";
  const track = css.match(/\.balanceTrack\{[^}]+\}/)?.[0] || "";
  assert.match(footer, /bottom:\.72cqw/);
  assert.match(track, /background:rgba\(0,0,0,\.20\)/);
});
