import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const panel = fs.readFileSync(new URL('../components/aster-profit-lock-ladder-panel.tsx', import.meta.url), 'utf8');

test('Profit Lock Ladder host spans the complete Botsettings grid on mobile', () => {
  assert.match(panel, /#profit-lock-ladder-settings-host\{grid-column:1\/-1!important;width:100%!important/);
  assert.match(panel, /justify-self:stretch!important/);
  assert.match(panel, /\.pll-settings\{width:100%;min-width:0;grid-column:1\/-1/);
});

test('Profit Lock Ladder mobile ladder columns remain usable instead of collapsing', () => {
  assert.match(panel, /@media\(max-width:520px\)/);
  assert.match(panel, /grid-template-columns:34px minmax\(0,1\.25fr\) minmax\(0,\.9fr\) 74px/);
  assert.match(panel, /\.pll-tr label input\{width:100%!important;min-width:0!important/);
});
