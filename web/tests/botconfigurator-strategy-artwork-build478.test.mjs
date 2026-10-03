import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Build 478 artwork remains intact in Build 479 without touching card behavior", async () => {
  const [component, version, zone, classic] = await Promise.all([
    readFile(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
    readFile(new URL("../public/zone-warriors-card-ref1-20260930.webp", import.meta.url)),
    readFile(new URL("../public/classic-dca-card-ref8-20260930.webp", import.meta.url)),
  ]);

  assert.match(version, /WEBAPP_BUILD_NUMBER = "488"/);
  const start = component.indexOf("{currentStep===1");
  const end = component.indexOf("{currentStep===2", start);
  assert.ok(start > 0 && end > start);
  const strategyScreen = component.slice(start, end);

  assert.match(strategyScreen, /\/zone-warriors-card-ref1-20260930\.webp/);
  assert.match(strategyScreen, /\/classic-dca-card-ref8-20260930\.webp/);
  assert.doesNotMatch(strategyScreen, /zone-warriors-icon-ref1\.svg/);
  assert.doesNotMatch(strategyScreen, /classic-dca-icon-ref10\.svg/);
  assert.match(component, /\.v3-strategy-card img\{[^}]*object-fit:contain;object-position:center/);

  assert.equal(zone.subarray(0, 4).toString("ascii"), "RIFF");
  assert.equal(zone.subarray(8, 12).toString("ascii"), "WEBP");
  assert.equal(classic.subarray(0, 4).toString("ascii"), "RIFF");
  assert.equal(classic.subarray(8, 12).toString("ascii"), "WEBP");
});