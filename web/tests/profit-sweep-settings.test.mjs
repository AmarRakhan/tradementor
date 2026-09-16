import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const profitPotBridge = await readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx", import.meta.url), "utf8");
const settingsBridge = await readFile(new URL("../components/aster-profit-sweep-settings-bridge.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/profit-pot-snapshot.css", import.meta.url), "utf8");
const route = await readFile(new URL("../app/api/exchanges/aster/profit-sweep-settings/route.ts", import.meta.url), "utf8");
const layout = await readFile(new URL("../app/layout.tsx", import.meta.url), "utf8");

test("each user can enable Profit sparen and choose 5, 10, 25, 50 or a custom percentage", () => {
  assert.match(settingsBridge, /const PRESETS = \[5, 10, 25, 50\]/);
  assert.match(settingsBridge, /role="switch"/);
  assert.match(settingsBridge, /min="0" max="100"/);
  assert.match(settingsBridge, /JSON\.stringify\(\{ enabled, sweepPercent: next \}\)/);
  assert.match(settingsBridge, /nieuwe positieve gerealiseerde nettowinst/);
  assert.match(settingsBridge, /Inleg, positieomvang, margin en ongerealiseerde PnL tellen niet mee/);
});

test("existing Profit Pot value tile stays strictly read-only and settings are isolated", () => {
  assert.match(profitPotBridge, /<article className="aps-profit-pot-card"/);
  assert.match(profitPotBridge, /aster-profit-sweep-settings-host/);
  assert.doesNotMatch(profitPotBridge, /authenticatedRequest|onClick=|method: "PUT"/);
  assert.match(settingsBridge, /<button className="aps-profit-save-card"/);
  assert.match(css, /\.aps-profit-pot-card\{[^}]*pointer-events:none/);
  assert.match(css, /\.aps-profit-save-card\{/);
  assert.match(layout, /AsterProfitSweepSettingsBridge/);
});

test("configuration is explicit that automatic money movement is not active yet", () => {
  assert.match(settingsBridge, /automatische Futures → Spot-transfer is in deze build nog niet actief/i);
  assert.match(settingsBridge, /alleen per gebruiker opgeslagen/i);
});

test("Profit Sweep settings proxy exposes only GET and PUT configuration calls", () => {
  assert.match(route, /export async function GET/);
  assert.match(route, /export async function PUT/);
  assert.match(route, /\/v1\/me\/aster\/profit-sweep-settings/);
  assert.doesNotMatch(route, /export async function POST/);
  assert.doesNotMatch(route, /export async function DELETE/);
});
