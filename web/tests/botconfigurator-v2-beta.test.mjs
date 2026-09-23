import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const shell = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const v2 = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("stable path keeps the legacy configurator and beta is lazy loaded", () => {
  assert.match(shell, /if \(!betaEnabled\) return <AsterStrategy2Maker/);
  assert.match(shell, /lazy\(\(\) => import\("@\/components\/aster-bot-configurator-v2"\)/);
  assert.match(page, /AsterStrategy2Entry/);
});

test("V2 uses the approved visual reference and one-page step structure", () => {
  assert.match(v2, /file_000000003e34820a9d0c8dc22b84ac47/);
  for (const id of ["markt", "posities", "instap", "grootte", "dca", "winst", "bescherming", "controle"]) {
    assert.match(v2, new RegExp("v2-step-" + id));
  }
  assert.match(v2, /BETA · alleen zichtbaar voor jou/);
});

test("release center keeps approval separate from publish and supports rollback", () => {
  assert.match(v2, /Getest en akkoord/);
  assert.match(v2, /Vrijgeven aan alle gebruikers/);
  assert.match(v2, /Terug naar BETA/);
});
