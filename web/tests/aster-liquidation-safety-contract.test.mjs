import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const component = readFileSync(new URL('../components/aster-liquidation-safety-enhancer.tsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../app/portfolio-liquidation-safety.css', import.meta.url), 'utf8');
test('Dynamic Hedge toggle uses server contract and explicit confirmation', () => {
  assert.match(component, /dynamic-hedge\/enabled/); assert.match(component, /enabled: next, confirm: true/); assert.match(component, /method: "PUT"/);
});
test('unreliable data blocks enabling but never traps an already-enabled controller', () => {
  assert.match(component, /disabled=\{!state \|\| busy \|\| \(!state\.enabled && safety === "DATA_ONBETROUWBAAR"\)\}/);
  assert.match(component, /Automatisch hedgebeheer stopt, maar bestaande LONG- en SHORT-posities blijven open/);
});
test('Available to Trade explicitly states it is not a liquidation meter', () => {
  assert.match(component, /Available is geen liquidatiemeter/); assert.match(component, /equity\/margin balance versus maintenance margin/);
});
test('mobile layouts collapse safely at phone widths', () => {
  assert.match(css, /@media\(max-width:640px\)/); assert.match(css, /@media\(max-width:420px\)/);
  assert.match(css, /\.als-summary-row\{grid-template-columns:1fr\}/);
  assert.match(css, /\.als-metrics-grid\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)\}/);
});
