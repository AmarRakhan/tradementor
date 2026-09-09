import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Snapshot Alles sluiten follows approved modal reference and dedicated route", async () => {
  const [component, css, route] = await Promise.all([
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/positions/close-all/route.ts", import.meta.url), "utf8"),
  ]);
  assert.match(component, /file_00000000b4bc8210aa8f4c8e32f5e7dd/);
  assert.match(component, /Weet je zeker dat je alle actieve posities wilt sluiten\?/);
  assert.match(component, /Dit sluit alle open LONG- en SHORT-posities, ongeacht winst of verlies\./);
  assert.match(component, /Bezig met sluiten\.\.\./);
  assert.match(component, /Alle actieve posities zijn gesloten/);
  assert.match(component, /loadFullClosePreview/);
  assert.match(component, /\/api\/exchanges\/aster\/positions\/close-all/);
  assert.doesNotMatch(component, /legacy\.click\(\)/);
  assert.match(route, /\/v1\/me\/aster\/positions\/close-all/);
  assert.match(css, /\.aps-full-close-backdrop/);
  assert.match(css, /\.aps-full-close-modal/);
  assert.match(css, /\.aps-full-close-progress/);
  assert.match(css, /\.aps-full-close-success/);
});

test("existing profit close stays independent", async () => {
  const component = await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
  for (const value of ["Close Long", "Close Short", "Close All", "profitable-close-preview", "close-profitable"]) assert.match(component, new RegExp(value));
  assert.match(component, /minimumProfitUsd/);
});
