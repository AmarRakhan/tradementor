import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const chart=fs.readFileSync(new URL("../components/trading-chart.tsx",import.meta.url),"utf8");
const cockpit=fs.readFileSync(new URL("../components/aster-recent-trades.tsx",import.meta.url),"utf8");

test("Focus 2.0 chart labels recovery stages as quantity releases",()=>{
  assert.match(chart,/HERSTEL/);
  assert.match(chart,/RELEASE/);
  assert.match(chart,/LONG BREAK-EVEN/);
  assert.doesNotMatch(chart,/SHORT RELEASE · \$\{Math\.round/);
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
