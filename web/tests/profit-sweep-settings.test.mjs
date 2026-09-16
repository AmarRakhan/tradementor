import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const bridge = await readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx", import.meta.url), "utf8");
const route = await readFile(new URL("../app/api/exchanges/aster/profit-sweep-settings/route.ts", import.meta.url), "utf8");

test("Profit Pot lets each user choose a savings percentage", () => {
  assert.match(bridge, /const PRESETS = \[5, 10, 25, 50\]/);
  assert.match(bridge, /min="0" max="100"/);
  assert.match(bridge, /Spaarpercentage/);
  assert.match(bridge, /sweepPercent: next/);
  assert.match(bridge, /nieuwe positieve gerealiseerde nettowinst/);
  assert.match(bridge, /Inleg, positieomvang en ongerealiseerde PnL tellen niet mee/);
});

test("Profit Pot UI is explicit that money movement is not active yet", () => {
  assert.match(bridge, /Automatische Futures → Spot-transfer is nog niet actief/);
  assert.match(bridge, /Deze stap slaat nu alleen jouw percentage veilig op/);
});

test("Profit Sweep settings proxy exposes only GET and PUT configuration calls", () => {
  assert.match(route, /export async function GET/);
  assert.match(route, /export async function PUT/);
  assert.match(route, /\/v1\/me\/aster\/profit-sweep-settings/);
  assert.doesNotMatch(route, /export async function POST/);
  assert.doesNotMatch(route, /export async function DELETE/);
});
