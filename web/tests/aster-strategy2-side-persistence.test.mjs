import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

assert.match(source, /const persisted = \(state\.settings && typeof state\.settings === "object" \? state\.settings : \{\}\)/);
assert.match(source, /return \{\s*\.\.\.persisted,/);
assert.match(source, /entryMarginLongUsd:\s*longEntry/);
assert.match(source, /entryMarginShortUsd:\s*shortEntry/);
assert.doesNotMatch(source, /asymmetricHedgeModeEnabled:\s*false/);
assert.doesNotMatch(source, /shortStartMultiplier:\s*0/);

console.log("Strategy 2 side persistence contract OK");
