import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Alles sluiten exposes emergency confirmation, busy and exchange-confirmed success states", async () => {
  const growth = await readFile(new URL("../components/portfolio-growth-card.tsx", import.meta.url), "utf8");

  assert.match(growth, /Alle posities sluiten\?/);
  assert.match(growth, /NOODSTOP WORDT UITGEVOERD/);
  assert.match(growth, /NOODSTOP UITGEVOERD/);
  assert.match(growth, /Aster en Sniper blijven uit/);
  assert.match(growth, /String\(result\.status \|\| ""\)\.toUpperCase\(\) !== "COMPLETED"/);
  assert.doesNotMatch(growth, /quote_id:data\.quoteId/);
  assert.match(growth, /idempotency_key: closeRequest\.current\.key/);
  assert.match(growth, /JA, ALLES STOPPEN EN SLUITEN/);
  assert.match(growth, /if \(!busy\) setConfirm\(false\)/);
});

test("Alles sluiten backend is baseline-independent and fail-closed until Aster confirms flat exposure", async () => {
  const backend = await readFile(new URL("../../cloud_api/main.py", import.meta.url), "utf8");

  assert.match(backend, /\/v1\/me\/aster\/automation\/close-all/);
  assert.match(backend, /AsterCloseAllRequest/);
  assert.match(backend, /quote_id: str \| None/);
  assert.match(backend, /emergency":True/);
  assert.match(backend, /for order in client\.open_orders\(\)/);
  assert.match(backend, /position_risk\(\)/);
  assert.match(backend, /if remaining:/);
  assert.match(backend, /if remaining_orders:/);
  assert.match(backend, /CLOSE_ALL_CONFIRMED_FLAT/);
  assert.match(backend, /PARTIAL_FAIL_CLOSED/);
  assert.match(backend, /FAILED_BEFORE_CLOSE/);
  assert.match(backend, /closeLock/);
  assert.match(backend, /status!="RESERVED"/);
  assert.match(backend, /_acquire_aster_account_coordination\(uid,"EMERGENCY","CLOSE_ALL"\)/);
});
