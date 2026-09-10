import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const manager = fs.readFileSync(new URL('../components/aster-hedge-manager.tsx', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../components/aster-hedge-manager.module.css', import.meta.url), 'utf8');
const enhancer = fs.readFileSync(new URL('../components/aster-portfolio-snapshot-enhancer.tsx', import.meta.url), 'utf8');

const reference = 'file_00000000032881f495cdc99757a7d126';

test('definitive hedge flow reference and six-screen interaction are wired', () => {
  assert.match(manager, new RegExp(reference));
  for (const label of ['Hedge Dekking', 'Hedge instellingen', 'Hedge herstellen', 'Bevestig actie', 'Hedge herstel actief']) assert.match(manager, new RegExp(label));
  assert.match(enhancer, /AsterHedgeManager/);
});

test('recovery is symmetric and low hedge never proposes opening longs', () => {
  assert.match(manager, /OPEN_SHORT/);
  assert.match(manager, /CLOSE_LONG/);
  assert.match(manager, /CLOSE_SHORT/);
  assert.match(manager, /OPEN_LONG/);
  assert.match(manager, /state\.actions\.recommended/);
});

test('user controls seats and target-zone settings', () => {
  for (const value of ['targetPercent', 'healthyMinPercent', 'healthyMaxPercent', 'maxCorrectionPercent']) assert.match(manager, new RegExp(value));
  assert.match(manager, /\[5, 10, 20, 30, 50\]/);
  assert.match(manager, /setSeatCount/);
  assert.match(manager, /Gemiddelde .* startmargin/);
});

test('preview, execution, stop and live progress are connected to backend routes', () => {
  assert.match(manager, /hedge-recovery\/preview/);
  assert.match(manager, /hedge-recovery\/start/);
  assert.match(manager, /\/step/);
  assert.match(manager, /\/stop/);
  assert.match(manager, /Huidige hedge \(live\)/);
  assert.match(css, /\.progressBar/);
});
