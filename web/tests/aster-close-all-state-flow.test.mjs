import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Alles sluiten exposes confirmation, busy and exchange-confirmed success states", async () => {
  const growth = await readFile(new URL("../components/portfolio-growth-card.tsx", import.meta.url), "utf8");

  assert.match(growth, /Alles sluiten bevestigen/);
  assert.match(growth, /Bezig met sluiten\.\.\./);
  assert.match(growth, /Alles sluiten voltooid/);
  assert.match(growth, /Alle posities en open orders zijn door Aster bevestigd gesloten/);
  assert.match(growth, /String\(result\.status \|\| ""\)\.toUpperCase\(\) !== "COMPLETED"/);
  assert.match(growth, /closeRequest\.current\.quoteId !== quoteId/);
  assert.match(growth, /idempotency_key: closeRequest\.current\.key/);
  assert.match(growth, /if \(!busy\) setConfirm\(false\)/);
});

test("Alles sluiten backend remains fail-closed until Aster confirms flat exposure", async () => {
  const backend = await readFile(new URL("../../cloud_api/main.py", import.meta.url), "utf8");

  assert.match(backend, /\/v1\/me\/aster\/automation\/close-all/);
  assert.match(backend, /AsterCloseAllRequest/);
  assert.match(backend, /position_risk\(\)/);
  assert.match(backend, /if remaining:/);
  assert.match(backend, /CLOSE_ALL_CONFIRMED_FLAT/);
  assert.match(backend, /PARTIAL_FAIL_CLOSED/);
  assert.match(backend, /FAILED_BEFORE_CLOSE/);
  assert.match(backend, /closeLock/);
  assert.match(backend, /status!="RESERVED"/);
});
