import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const bridge = await readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/profit-pot-snapshot.css", import.meta.url), "utf8");
const route = await readFile(new URL("../app/api/exchanges/aster/profit-sweep-settings/route.ts", import.meta.url), "utf8");

test("each user can enable Profit sparen and choose 5, 10, 25, 50 or a custom percentage", () => {
  assert.match(bridge, /const PRESETS = \[5, 10, 25, 50\]/);
  assert.match(bridge, /role="switch"/);
  assert.match(bridge, /min="0" max="100"/);
  assert.match(bridge, /JSON\.stringify\(\{ enabled, sweepPercent: next \}\)/);
  assert.match(bridge, /nieuwe positieve gerealiseerde nettowinst/);
  assert.match(bridge, /Inleg, positieomvang, margin en ongerealiseerde PnL tellen niet mee/);
});

test("the existing Profit Pot value tile remains read-only and settings use a separate button", () => {
  assert.match(bridge, /<article className="aps-profit-pot-card"/);
  assert.match(bridge, /<button className="aps-profit-save-card"/);
  assert.match(css, /\.aps-profit-pot-card\{[^}]*pointer-events:none/);
  assert.match(css, /\.aps-profit-save-card\{/);
});

test("configuration is explicit that automatic money movement is not active yet", () => {
  assert.match(bridge, /automatische Futures → Spot-transfer is in deze build nog niet actief/i);
  assert.match(bridge, /alleen per gebruiker opgeslagen/i);
});

test("Profit Sweep settings proxy exposes only GET and PUT configuration calls", () => {
  assert.match(route, /export async function GET/);
  assert.match(route, /export async function PUT/);
  assert.match(route, /\/v1\/me\/aster\/profit-sweep-settings/);
  assert.doesNotMatch(route, /export async function POST/);
  assert.doesNotMatch(route, /export async function DELETE/);
});
