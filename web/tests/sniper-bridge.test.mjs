import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const sniper = fs.readFileSync(new URL('../components/sniper-dashboard.tsx', import.meta.url), 'utf8');
const bridge = fs.readFileSync(new URL('../components/home-navigation-bridge.tsx', import.meta.url), 'utf8');
const layout = fs.readFileSync(new URL('../app/layout.tsx', import.meta.url), 'utf8');
const manifest = JSON.parse(fs.readFileSync(new URL('../public/manifest.webmanifest', import.meta.url), 'utf8'));
const sw = fs.readFileSync(new URL('../public/sw.js', import.meta.url), 'utf8');

test('SNIPER is exposed as an Aavansh main navigation view', () => {
  assert.match(bridge, /ensureButton\(nav, "sniper", "S", "SNIPER", "aster"\)/);
  assert.match(bridge, /<SniperDashboard snapshots=\{sniperSnapshots\} cloudReady=\{cloudReady\}/);
});

test('SNIPER has exactly the agreed five sections', () => {
  for (const label of ['Overzicht', 'Trades', 'Signalen', 'Prestaties', 'Instellingen']) {
    assert.match(sniper, new RegExp(`"${label}"`));
  }
});

test('SNIPER keeps the agreed hard defaults and four scan timeframes', () => {
  assert.match(sniper, /enabled: false/);
  assert.match(sniper, /simulation: true/);
  assert.match(sniper, /maxTradeSeconds: 180/);
  assert.match(sniper, /tpMinPercent: 0\.18/);
  assert.match(sniper, /tpMaxPercent: 0\.45/);
  assert.match(sniper, /maxLossUsd: 0\.10/);
  assert.match(sniper, /maxConcurrent: 3/);
  for (const timeframe of ['15s', '1m', '3m', '5m']) assert.match(sniper, new RegExp(timeframe));
});

test('SNIPER contains all twelve entry checks', () => {
  const checks = ['Bollinger Band locatie','Momentum','Trendfilter','Volume bevestiging','Orderflow','Orderboek','Liquiditeit','Spread check','Volatiliteit','Kosten check','Liquidatiebuffer','Historische edge'];
  for (const name of checks) assert.match(sniper, new RegExp(name));
});

test('SNIPER frontend cannot execute or close Aster positions', () => {
  assert.doesNotMatch(sniper, /authenticatedRequest/);
  assert.doesNotMatch(sniper, /PositionCloseControl/);
  assert.doesNotMatch(sniper, /\/api\/execution/);
  assert.doesNotMatch(sniper, /\/api\/exchanges\/aster\/.*close/);
});

test('bridge only reads shared account snapshots for SNIPER', () => {
  assert.match(bridge, /authenticatedRequest\("\/api\/exchanges\/hyperliquid"\)/);
  assert.match(bridge, /authenticatedRequest\("\/api\/exchanges\/aster"\)/);
  assert.doesNotMatch(bridge, /method:\s*"(POST|PUT|DELETE)"/);
});

test('Aavansh keeps a separate PWA identity', () => {
  assert.equal(manifest.name, 'Aavansh Trading');
  assert.equal(manifest.id, '/aavansh-trading-v1');
  assert.match(sw, /aavansh-trading-shell-v1/);
  assert.match(layout, /data-aavansh-trading="v1"/);
  assert.match(layout, />AAVANSH TRADING</);
});
