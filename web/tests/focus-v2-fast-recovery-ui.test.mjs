import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const chart=fs.readFileSync(new URL("../components/trading-chart.tsx",import.meta.url),"utf8");
const cockpit=fs.readFileSync(new URL("../components/aster-recent-trades.tsx",import.meta.url),"utf8");

test("Focus 2.0 v5 chart uses directional DCA and hedge-release labels",()=>{
  assert.match(chart,/DCA \/ SHORT FILL/);
  assert.match(chart,/SHORT LOS/);
  assert.match(chart,/className="breakeven">BE /);
  assert.doesNotMatch(chart,/HERSTELTRIGGER/);
  assert.doesNotMatch(chart,/RE-HEDGE/);
});

test("Focus 2.0 chart allows horizontal and vertical interaction",()=>{
  assert.match(chart,/pressedMouseMove:true/);
  assert.match(chart,/horzTouchDrag:true/);
  assert.match(chart,/vertTouchDrag:true/);
  assert.match(chart,/axisPressedMouseMove:true/);
});

test("Focus 2.0 cockpit exposes fast recovery protection state",()=>{
  for(const token of ["Recovery stage","Low → break-even","Totaal vrijgegeven","armedRehedgeQty","targetShortNotional","nextShortReleaseQty"]){
    assert.match(cockpit,new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")));
  }
});
