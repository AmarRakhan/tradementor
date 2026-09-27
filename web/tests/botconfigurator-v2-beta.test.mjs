import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const shell = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const v2 = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("unreleased path keeps the legacy configurator and V2 is lazy loaded", () => {
  assert.match(shell, /if \(!releaseEnabled\) return <AsterStrategy2Maker/);
  assert.match(shell, /lazy\(\(\) => import\("@\/components\/aster-bot-configurator-v2"\)/);
  assert.match(page, /AsterStrategy2Entry as AsterStrategy2Maker/);
});

test("V2 uses the approved visual reference and one-page step structure", () => {
  assert.match(v2, /file_000000007b288243acf4cc791b0258dd/);
  for (const id of ["markt", "posities", "instap", "grootte", "dca", "winst", "bescherming", "controle"]) {
    assert.match(v2, new RegExp("v2-step-" + id));
  }
  assert.match(v2, /BETA · alleen zichtbaar voor jou/);
  assert.match(v2, /const zoneSoldiersAvailable = feature\("zone_soldiers"\)\.enabled === true/);
  assert.doesNotMatch(v2, /ownerBeta && feature\("zone_soldiers"\)/);
});

test("release center keeps approval separate from publish and supports rollback", () => {
  assert.match(v2, /Getest en akkoord/);
  assert.match(v2, /Vrijgeven aan alle gebruikers/);
  assert.match(v2, /Terug naar BETA/);
});

test("V2 seat bars show live occupancy against each side capacity", () => {
  assert.match(v2, /report\.activeLong/);
  assert.match(v2, /report\.activeShort/);
  assert.match(v2, /slotFill\(activeLong, totals\.longSlots\)/);
  assert.match(v2, /slotFill\(activeShort, totals\.shortSlots\)/);
  assert.match(v2, /Bezet \/ capaciteit/);
  assert.doesNotMatch(v2, /totals\.longSlots \/ totals\.totalSlots/);
  assert.doesNotMatch(v2, /totals\.shortSlots \/ totals\.totalSlots/);
});

test("Build 455 keeps price-zone seats an explicit persistent entitlement opt-in", () => {
  assert.match(v2, /zoneSoldiersEnabled: settings\.zoneSoldiersEnabled === true && n\(settings\.zoneSoldiersOptInVersion, 0\) >= 1/);
  assert.match(v2, /Prijszone-stoelen/);
  assert.match(v2, /Expliciete opt-in/);
  assert.match(v2, /zoneSoldiersOptInVersion: draft\.zoneSoldiersEnabled \? 1 : 0/);
  assert.match(v2, /STRATEGIE · TRADITIONEEL/);
  assert.match(v2, /ZONEPOSITIES AFBOUWEN/);
});

test("Build 455 shows the active price-zone strategy outside settings", () => {
  assert.match(page, /aster-strategy-mode/);
  assert.match(page, /STRATEGIE · PRIJSZONE-STOELEN/);
  assert.match(page, /PRICE_ZONE_SEATS/);
  assert.match(page, /STRATEGIE · TRADITIONEEL/);
  assert.match(page, /Portfolio Koers is informatief/);
});


test("Build 455 keeps safe 3L/3S price-zone defaults when legacy settings do not contain seat fields", () => {
  assert.match(v2, /zoneLongSeats: textValue\(settings\.zoneBaseLongSoldiers, 3\)/);
  assert.match(v2, /zoneShortSeats: textValue\(settings\.zoneBaseShortSoldiers, 3\)/);
  assert.match(v2, /zoneBaseLongSoldiers: zoneLongSeats/);
  assert.match(v2, /zoneBaseShortSoldiers: zoneShortSeats/);
  assert.match(v2, /zoneEntryGrowthPercent: nDefault\(persisted\.zoneEntryGrowthPercent, 2\)/);
  assert.match(v2, /zoneEntryMaxMultiplier: nDefault\(persisted\.zoneEntryMaxMultiplier, 1\.2\)/);
});
