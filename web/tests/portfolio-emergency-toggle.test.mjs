import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Portfolio Noodhedge UI remains globally disabled behind an inert compatibility shim", async () => {
  const source = await readFile(new URL("../components/aster-portfolio-emergency-hedge.tsx", import.meta.url), "utf8");

  assert.match(source, /P0 2026-09-16 — Portfolio Noodhedge is globally disabled/);
  assert.match(source, /export function AsterPortfolioEmergencyHedge\(\)/);
  assert.match(source, /return null;/);
  assert.doesNotMatch(source, /refresh\(|setOpen\(|setDraftEnabled\(|authenticatedRequest|fetch\(/);
});
