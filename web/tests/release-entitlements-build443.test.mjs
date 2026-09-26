import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Build 443 exposes independent release entitlements without auto-enabling user settings", async () => {
  const [configurator, chart, snapshot, autoHedge, version] = await Promise.all([
    readFile(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
  ]);

  assert.match(version, /WEBAPP_BUILD_NUMBER = "443"/);
  assert.match(configurator, /feature\("margin_summary"\)\.enabled === true/);
  assert.match(configurator, /feature\("zone_soldiers"\)\.enabled === true/);
  assert.doesNotMatch(configurator, /ownerBeta && feature\("zone_soldiers"\)/);
  assert.match(configurator, /zone_command_center: "Zone Command Center"/);
  assert.match(configurator, /auto_hedge_v2: "Auto Hedge 2\.0"/);
  assert.match(configurator, /legacy_hedge_recovery: "Legacy Hedge Recovery"/);
  assert.match(configurator, /dependencies\?\.length/);

  assert.match(chart, /features\.zone_command_center/);
  assert.match(chart, /setCommandCenterTester\(commandAccess\)/);
  assert.doesNotMatch(chart, /const commandCenterTester=betaOwner===true/);
  assert.match(snapshot, /zoneCommandCenterEnabled/);

  assert.match(autoHedge, /features\.auto_hedge_v2\?\.enabled === true/);
  assert.match(autoHedge, /features\.legacy_hedge_recovery\?\.enabled === true/);
  assert.match(autoHedge, /status === "HEDGED" && scaleAvailable/);
});

test("Build 443 release UI does not silently submit unavailable Zone-Soldaten settings", async () => {
  const configurator = await readFile(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
  assert.match(configurator, /zoneSoldiersAvailable \? \{/);
  assert.match(configurator, /\} : \{\}\),/);
  assert.doesNotMatch(configurator, /\} : \{ zoneSoldiersEnabled: false, zoneSoldiersOptInVersion: 0 \}\),/);
});
