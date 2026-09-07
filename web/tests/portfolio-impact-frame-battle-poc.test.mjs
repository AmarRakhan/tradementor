import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const component = readFileSync(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../components/portfolio-impact-battle.module.css", import.meta.url), "utf8");

test("Bulls battle uses a fixed background plus a continuously rendered foreground battle", () => {
  assert.match(component, /const BATTLE_LOOP_FRAMES = 50/);
  assert.match(component, /const BATTLE_FPS = 20/);
  assert.match(component, /function BattleArtwork/);
  assert.match(component, /data-battle-animation-frame/);
  assert.match(component, /battleShift = Math\.max\(-42, Math\.min\(42, \(longShare - 50\) \* 1\.4\)\)/);
  assert.match(component, /longFrontLegMask/);
  assert.match(component, /shortFrontLegMask/);
  assert.match(component, /longRearLegMask/);
  assert.match(component, /shortRearLegMask/);
  assert.match(component, /impactSparks/);
  assert.match(component, /battleDust/);
  assert.match(css, /portfolio-impact-premium-clean\.webp/);
  assert.match(css, /\.battleScene\{/);
});

test("Bulls battle remains presentation-only and no video player is introduced", () => {
  assert.doesNotMatch(component, /<video|\.mp4|video\/mp4/i);
  assert.match(component, /authenticatedRequest\(`\/api\/markets\/aster\/pressure\?/);
  assert.doesNotMatch(component, /\/start|\/stop|\/close-all|\/positions\/close/);
});

test("live LONG SHORT panels remain transparent DOM overlays", () => {
  const side = css.match(/\.sidePanel\{[^}]+\}/)?.[0] || "";
  const long = css.match(/\.longPanel\{[^}]+\}/)?.[0] || "";
  const short = css.match(/\.shortPanel\{[^}]+\}/)?.[0] || "";
  assert.match(side, /background:transparent!important/);
  assert.match(side, /backdrop-filter:none!important/);
  assert.match(long, /background:transparent!important/);
  assert.match(short, /background:transparent!important/);
});
