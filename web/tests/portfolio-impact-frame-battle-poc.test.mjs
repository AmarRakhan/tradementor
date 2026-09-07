import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const component = readFileSync(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../components/portfolio-impact-battle.module.css", import.meta.url), "utf8");

test("Bulls battle is a continuous frame loop over one fixed premium background", () => {
  assert.match(component, /const BATTLE_LOOP_FRAMES = 50/);
  assert.match(component, /const BATTLE_FPS = 20/);
  assert.match(component, /BATTLE_SOURCE = "\/portfolio-impact-premium-reference\.webp"/);
  assert.match(component, /src=\{BATTLE_SOURCE\}/);
  assert.doesNotMatch(component, /eraserOpacity|fill="#00140b"|fill="#180306"/);
  assert.match(component, /function BattleArtwork/);
  assert.match(component, /data-battle-animation-frame/);
  assert.match(component, /battleShift = pressure \* 24/);
  assert.match(component, /const intensity = Math\.min\(1, 0\.28 \+ Math\.abs\(pressure\) \* 1\.18\)/);
  assert.match(component, /longFrontLegMask/);
  assert.match(component, /shortFrontLegMask/);
  assert.match(component, /longRearLegMask/);
  assert.match(component, /shortRearLegMask/);
  assert.match(component, /impactSparks/);
  assert.match(component, /battleDust/);
  assert.match(css, /\.battleScene\{/);
});

test("Bulls intensity rises with dominance without changing trading logic", () => {
  assert.match(component, /dustCount = 12 \+ Math\.round\(intensity \* 12\)/);
  assert.match(component, /sparkCount = 10 \+ Math\.round\(intensity \* 12\)/);
  assert.match(component, /legAmplitude = 2\.4 \+ intensity \* 7\.0/);
  assert.match(component, /authenticatedRequest\(`\/api\/markets\/aster\/pressure\?/);
  assert.doesNotMatch(component, /\/start|\/stop|\/close-all|\/positions\/close/);
});

test("no video player and no opaque side HUD blocks are introduced", () => {
  assert.doesNotMatch(component, /<video|\.mp4|video\/mp4/i);
  const side = css.match(/\.sidePanel\{[^}]+\}/)?.[0] || "";
  assert.match(side, /background:transparent!important/);
  assert.match(side, /backdrop-filter:none!important/);
  assert.match(side, /border:0!important/);
  assert.doesNotMatch(css, /leftSmoke|rightSmoke/);
});

test("pressure bar remains visually embedded in the stone footer zone", () => {
  const footer = css.match(/\.battleFooter\{[^}]+\}/)?.[0] || "";
  const track = css.match(/\.balanceTrack\{[^}]+\}/)?.[0] || "";
  assert.match(footer, /bottom:\.72cqw/);
  assert.match(track, /background:rgba\(0,0,0,\.20\)/);
});
