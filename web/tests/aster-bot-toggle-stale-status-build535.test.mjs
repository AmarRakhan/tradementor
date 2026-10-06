import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Build 535 recovers a stale Aster bot UI status without auto-toggling live trading", async () => {
  const maker = await readFile(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

  assert.match(maker, /if \(status\.pending\) \{/);
  assert.match(maker, /authenticatedRequest\("\/api\/exchanges\/aster", \{ cache: "no-store" \}\)/);
  assert.match(maker, /setConfirmedState\(latestStrategy2\)/);
  assert.match(maker, /onConfirmed\(latestStrategy2\)/);
  assert.match(maker, /status\.pending \? "Status ophalen"/);
  assert.match(maker, /disabled=\{busy\}/);

  const pendingStart = maker.indexOf("if (status.pending) {");
  const pendingEnd = maker.indexOf("if (enabled) return action", pendingStart);
  const pendingBlock = maker.slice(pendingStart, pendingEnd);
  assert.doesNotMatch(pendingBlock, /action\("start"\)/);
  assert.doesNotMatch(pendingBlock, /action\("stop"\)/);
  assert.doesNotMatch(pendingBlock, /checkReadiness\(true\)/);
});
