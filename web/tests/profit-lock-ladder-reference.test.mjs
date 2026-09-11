import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const files = [
  "../components/aster-profit-lock-ladder-panel.tsx",
  "../components/aster-profit-lock-ladder-bridge.tsx",
];

for (const file of files) {
  test(`${file} uses approved Profit Lock reference`, () => {
    const text = fs.readFileSync(new URL(file, import.meta.url), "utf8");
    assert.match(text, /file_00000000e8dc82108202dd2e1397c131/);
  });
}
