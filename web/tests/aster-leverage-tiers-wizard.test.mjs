import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const route = readFileSync(new URL("../app/api/exchanges/aster/strategy2/leverage-tiers/route.ts", import.meta.url), "utf8");

test("manual coin picker loads server-authoritative Aster leverage tiers", () => {
  assert.match(maker, /strategy2\/leverage-tiers/);
  assert.match(maker, /Aster leverage tiers/);
  assert.match(maker, /Volgende daling/);
  assert.match(maker, /Geschat aantal DCA's tot volgende tier/);
  assert.match(route, /proxyStrategy2Live/);
});

test("wizard warns that the whole position changes leverage and bot continues", () => {
  assert.match(maker, /de hele positie/);
  assert.match(maker, /automatisch de leverage/);
  assert.doesNotMatch(maker, /HYPE boven \$3000/);
});
