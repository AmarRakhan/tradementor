import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("webapp version 44 is sourced once and stays visible throughout app startup", async () => {
  const [versionSource, layout, registration, control] = await Promise.all([
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/pwa-registration.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/app-version-control.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(versionSource, /WEBAPP_VERSION = "44"/);
  assert.match(versionSource, /Webapp versie/);
  assert.match(layout, /<AppVersionControl \/>/);
  assert.match(layout, /<AuthProvider>\{children\}<\/AuthProvider>/);
  assert.ok(layout.indexOf("<AppVersionControl />") < layout.indexOf("<AuthProvider>"));
  assert.match(layout, /manifest\.webmanifest\?v=\$\{WEBAPP_VERSION\}/);
  assert.match(registration, /WEBAPP_VERSION/);
  assert.doesNotMatch(registration, /pwaVersion =/);
  assert.match(control, /registration\?\.update\(\)/);
  assert.match(control, /cache: "no-store"/);
  assert.match(control, /Versie \$\{WEBAPP_VERSION\} is actueel/);
});
