import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
assert.match(source, /const persisted = state\.settings/);
assert.match(source, /return \{\s*\.\.\.persisted,/);
console.log("Strategy 2 side persistence contract OK");
