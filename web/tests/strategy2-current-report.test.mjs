import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("strategy maker ignores a scan report from an older settings version", () => {
  assert.match(maker, /rawReport\.configVersion/);
  assert.match(maker, /reportVersion !== settingsVersion \? \{\} : rawReport/);
});

test("strategy and account position scopes are explicit", () => {
  assert.match(maker, /Botposities:/);
  assert.match(maker, /dashboard telt alle Aster-posities/);
});
