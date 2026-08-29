import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");

test("Focus preserves the existing Strategy-2 execution mode for legacy management",()=>{
  assert.match(maker,/mode:v\.mode,tradingMode:v\.tradingMode/);
  assert.doesNotMatch(maker,/mode:v\.tradingMode==="focus"\?"paper":v\.mode/);
  assert.match(maker,/Focus is optioneel en vereist dezelfde expliciete live-bevestiging en safety checks/);
  assert.match(maker,/focusWaitUntilFlat:v\.focusWaitFlat/);
  const focus=maker.slice(maker.indexOf(" const focusSteps=["),maker.indexOf(" const steps=",maker.indexOf(" const focusSteps=[")));
  assert.doesNotMatch(focus,/Bestaande Strategy-2-posities/);
});
