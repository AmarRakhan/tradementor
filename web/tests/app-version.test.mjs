import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("webapp version 46 and canonical build 375 stay visible throughout app startup", async () => {
  const [versionSource, layout, registration, control, history] = await Promise.all([
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/pwa-registration.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/app-version-control.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/release-history.ts", import.meta.url), "utf8"),
  ]);

  assert.match(versionSource, /WEBAPP_VERSION = "46"/);
  assert.match(versionSource, /WEBAPP_BUILD_NUMBER = "375"/);
  assert.match(versionSource, /webappVersionLabel/);
  assert.match(versionSource, /Webapp versie/);

  assert.match(layout, /WEBAPP_BUILD_NUMBER/);
  assert.match(layout, /data-webapp-build=\{WEBAPP_BUILD_NUMBER\}/);
  assert.match(layout, /<AppVersionControl \/>/);
  assert.match(layout, /<PwaRegistration \/>/);
  assert.match(layout, /<ReleaseHistoryControl \/>/);
  assert.match(layout, /<AuthProvider>\{children\}<\/AuthProvider>/);
  assert.ok(layout.indexOf("<ReleaseHistoryControl />") < layout.indexOf("<AuthProvider>"));
  assert.match(layout, /STRATEGY 2-RUNTIME/);
  assert.doesNotMatch(layout, /STRATEGY 3-RUNTIME LIVE/);
  assert.match(layout, /manifest\.webmanifest\?v=\$\{WEBAPP_VERSION\}&build=\$\{WEBAPP_BUILD_NUMBER\}/);
  assert.doesNotMatch(layout, /process\.env\.WEBAPP_BUILD_NUMBER/);

  assert.match(registration, /WEBAPP_BUILD_NUMBER/);
  assert.match(registration, /WEBAPP_VERSION/);
  assert.doesNotMatch(registration, /pwaVersion =/);
  assert.match(control, /registration\?\.update\(\)/);
  assert.match(control, /cache: "no-store"/);
  assert.match(control, /WEBAPP_BUILD_NUMBER/);
  assert.match(control, /data-webapp-build/);

  assert.match(history, /build: WEBAPP_BUILD_NUMBER/);
  assert.match(history, /version: WEBAPP_VERSION/);
});
