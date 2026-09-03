import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Markets navigation observer does not continuously reorder an already stable nav", async () => {
  const source = await readFile(new URL("../components/markets-navigation-bridge.tsx", import.meta.url), "utf8");
  assert.match(source, /visibleChildren/);
  assert.match(source, /visible\.some\(\(item, index\) => visibleChildren\[index\] !== item\)/);
  assert.doesNotMatch(source, /for \(const item of visible\) nav\.appendChild\(item\);\s*nav\.style/);
});

test("Markets navigation mutations are coalesced to one sync per animation frame", async () => {
  const source = await readFile(new URL("../components/markets-navigation-bridge.tsx", import.meta.url), "utf8");
  assert.match(source, /requestAnimationFrame\(\(\) => \{ frame = 0; sync\(\); \}\)/);
  assert.match(source, /if \(frame\) return/);
  assert.match(source, /label\.textContent !== "MARKETS"/);
});
