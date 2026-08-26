import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");

test("Focus preserves the existing Strategy-2 execution mode for legacy management",()=>{
  assert.match(maker,/mode:v\.mode,tradingMode:v\.tradingMode/);
  assert.doesNotMatch(maker,/mode:v\.tradingMode==="focus"\?"paper":v\.mode/);
  assert.match(maker,/Bestaande posities blijven via de huidige Multi-pair beheerlogica TP\/DCA\/recovery ontvangen/);
  assert.match(maker,/Focus is optioneel en vereist dezelfde expliciete live-bevestiging en safety checks/);
});
