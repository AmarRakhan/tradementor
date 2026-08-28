import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const maker=readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
const trades=readFileSync(new URL("../components/aster-recent-trades.tsx",import.meta.url),"utf8");
const chart=readFileSync(new URL("../components/trading-chart.tsx",import.meta.url),"utf8");
const css=readFileSync(new URL("../components/aster-trade-center.module.css",import.meta.url),"utf8");

test("Focus Airbag is explicit opt-in and explains legacy compatibility",()=>{
  assert.match(maker,/Adaptieve Portfolio Airbag/);
  assert.match(maker,/focusAirbagEnabled:v\.focusAirbag/);
  assert.match(maker,/UIT · huidige Focus ongewijzigd/);
  assert.match(maker,/Lopende trades:/);
});

test("trade detail exposes transparent Airbag status and contribution",()=>{
  assert.match(trades,/PORTFOLIO AIRBAG/);
  assert.match(trades,/Hedge bijdrage/);
  assert.match(trades,/Volgende actie:/);
  assert.match(trades,/airbagTimeline/);
  assert.match(trades,/AIRBAG \/ HEDGE/);
  assert.match(trades,/BOT BEHEERT/);
  assert.match(trades,/livePositions = useMemo\(\(\) => \[\.\.\.allPositions\]/);
});

test("chart shows compact hedge markers without adding hedge price lines",()=>{
  assert.match(chart,/onlyHedge/);
  assert.doesNotMatch(chart,/\?"HEDGE \+":"HEDGE -"/);
  assert.match(chart,/airbagEvents/);
  assert.doesNotMatch(chart,/title:`HEDGE/);
});

test("Airbag card has responsive Fold and phone layout",()=>{
  assert.match(css,/\.airbagGrid\{display:grid;grid-template-columns:repeat\(4,1fr\)/);
  assert.match(css,/@media\(max-width:700px\).*\.airbagGrid\{grid-template-columns:repeat\(2,1fr\)/s);
  assert.match(css,/@media\(max-width:380px\)/);
});


test("Airbag click resolves to linked main position and next DCA is server-fed",()=>{
  assert.match(trades,/linkedMain/);
  assert.match(trades,/Je bekijkt de Airbag van/);
  assert.match(trades,/Volgende \{detailMainSide\} DCA/);
  assert.match(trades,/strategy2DcaLadder\?\.levels/);
});
