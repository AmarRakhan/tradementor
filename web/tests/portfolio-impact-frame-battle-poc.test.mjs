import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const component = readFileSync(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../components/portfolio-impact-battle.module.css", import.meta.url), "utf8");
const videoCss = readFileSync(new URL("../components/portfolio-impact-bull-bear-video.module.css", import.meta.url), "utf8");

test("Bull vs Bear battle uses one scrub-controlled master video with a neutral poster", () => {
  assert.match(component, /MASTER_SOURCE = "\/portfolio-impact-bull-bear-master\.mp4"/);
  assert.match(component, /POSTER_SOURCE = "\/portfolio-impact-bull-bear-neutral\.webp"/);
  assert.match(component, /<video ref=\{videoRef\}/);
  assert.match(component, /video\.currentTime = targetTime/);
  assert.match(component, /video\.pause\(\)/);
  assert.doesNotMatch(component, /autoPlay|loop=/);
  assert.match(videoCss, /object-fit:\s*cover/);
  assert.match(videoCss, /\.videoReady/);
});

test("Bull vs Bear motion is driven only by read-only BTC Bollinger market data", () => {
  assert.match(component, /symbols=BTCUSDT/);
  assert.match(component, /mode=enrich/);
  assert.match(component, /bbLower/);
  assert.match(component, /bbMiddle/);
  assert.match(component, /bbUpper/);
  assert.match(component, /bollingerScore\(price, lower, upper\)/);
  assert.doesNotMatch(component, /\/start|\/stop|\/close-all|\/positions\/close|snapshot-close-profitable/);
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
