import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const profitPotBridge = await readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx", import.meta.url), "utf8");
const settingsBridge = await readFile(new URL("../components/aster-profit-sweep-settings-bridge.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/profit-pot-snapshot.css", import.meta.url), "utf8");
const route = await readFile(new URL("../app/api/exchanges/aster/profit-sweep-settings/route.ts", import.meta.url), "utf8");
const layout = await readFile(new URL("../app/layout.tsx", import.meta.url), "utf8");

test("Profit Pot settings support percentage plus persistent transfer threshold", () => {
  assert.match(settingsBridge, /const PRESETS = \[5, 10, 25, 50\]/);
  assert.match(settingsBridge, /role="switch"/);
  assert.match(settingsBridge, /minimumTransfer/);
  assert.match(settingsBridge, /Huidig opgespaard/);
  assert.match(settingsBridge, /Minimale transfer/);
  assert.match(settingsBridge, /JSON\.stringify\(\{ enabled, sweepPercent: next, minimumTransfer: threshold, transferAsset \}\)/);
  assert.match(settingsBridge, /Alleen positieve winsttrades/);
  assert.match(settingsBridge, /Kleine bedragen opsparen/);
  assert.match(settingsBridge, /Opnieuw proberen bij mislukte transfer/);
});

test("Portfolio Snapshot Profit Pot shows today's transferred amount plus current pending savings", () => {
  assert.match(profitPotBridge, /payload\.todayTransferred/);
  assert.match(profitPotBridge, /payload\.pendingSavings/);
  assert.match(profitPotBridge, /profitPotTodayDisplay/);
  assert.match(profitPotBridge, /todayTransferred \+ pendingSavings/);
  assert.match(profitPotBridge, />Vandaag<\/em>/);
  assert.match(profitPotBridge, /aster-profit-pot-open/);
  assert.match(profitPotBridge, /onClick=/);
  assert.doesNotMatch(profitPotBridge, /existingProfitPotValue/);
  assert.doesNotMatch(profitPotBridge, /spot-balance/);
  assert.match(css, /\.aps-profit-pot-card\{[\s\S]*pointer-events:auto/);
  assert.match(css, /@keyframes apsProfitPotFlipIn/);
  assert.match(layout, /AsterProfitSweepSettingsBridge/);
});

test("settings card exposes buffer, today's transfers and live USDC Spot balance separately", () => {
  assert.match(settingsBridge, /pendingSavings/);
  assert.match(settingsBridge, /todayTransferred/);
  assert.match(settingsBridge, /Spot saldo \(USDC\)/);
  assert.match(settingsBridge, /spotUsdcBalance/);
  assert.match(settingsBridge, /\/api\/exchanges\/aster\/spot-balance\?asset=USDC/);
  assert.match(settingsBridge, /transferInFlight/);
  assert.match(settingsBridge, /aster-profit-sweep-settings-updated/);
  assert.match(settingsBridge, /één drempelbedrag automatisch naar Spot overgezet/);
});

test("Profit Sweep settings proxy exposes only GET and PUT configuration calls", () => {
  assert.match(route, /export async function GET/);
  assert.match(route, /export async function PUT/);
  assert.match(route, /\/v1\/me\/aster\/profit-sweep-settings/);
  assert.doesNotMatch(route, /export async function POST/);
  assert.doesNotMatch(route, /export async function DELETE/);
});
