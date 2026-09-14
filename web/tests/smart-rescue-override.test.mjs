import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const overlay = await readFile(new URL("../components/aster-pair-settings-overlay.tsx", import.meta.url), "utf8");
const smart = await readFile(new URL("../components/aster-smart-rescue-override.tsx", import.meta.url), "utf8");
const getRoute = await readFile(new URL("../app/api/exchanges/aster/strategy2/smart-rescue/[symbol]/route.ts", import.meta.url), "utf8");
const extendRoute = await readFile(new URL("../app/api/exchanges/aster/strategy2/smart-rescue/[symbol]/extend/route.ts", import.meta.url), "utf8");

test("trade-detail pencil branches to Smart Rescue Override only for persisted Smart Rescue cycles", () => {
  assert.match(overlay, /AsterSmartRescueOverride/);
  assert.match(overlay, /multiBbPositions/);
  assert.match(overlay, /smartRescue/);
  assert.match(overlay, /PAIR OVERRIDE/);
});

test("Smart Rescue modal contains only active-cycle extension controls", () => {
  assert.match(smart, /SMART RESCUE OVERRIDE/);
  assert.match(smart, /Huidige Smart Rescue status/);
  assert.match(smart, /Nieuw totaal DCA/);
  assert.match(smart, /Nieuw rescue bereik/);
  assert.match(smart, /Ordergroei vanaf volgende stap/);
  assert.match(smart, /Uitbreiding opslaan/);
  assert.match(smart, /Bekijk volledige ladder/);
  assert.doesNotMatch(smart, /Instapmargin/);
  assert.doesNotMatch(smart, /Minimum leverage/);
  assert.doesNotMatch(smart, /SHORT start-multiplier/);
});

test("Smart Rescue modal carries the approved visual reference and no-order copy", () => {
  assert.match(smart, /file_000000005a14820a846ec59dfd9fc5a1/);
  assert.match(smart, /Opslaan plaatst geen order/);
  assert.match(smart, /Bestaande fills blijven ongewijzigd/);
});

test("authenticated browser routes proxy only Smart Rescue status and extension", () => {
  assert.match(getRoute, /strategy2\/smart-rescue/);
  assert.match(getRoute, /"GET"/);
  assert.match(extendRoute, /strategy2\/smart-rescue/);
  assert.match(extendRoute, /\/extend/);
  assert.match(extendRoute, /"PUT"/);
});
