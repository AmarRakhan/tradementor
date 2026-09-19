import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("release history is mobile-first, persistent and tied to canonical build 374", async () => {
  const [version, history, control, layout, css, workflow] = await Promise.all([
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/release-history.ts", import.meta.url), "utf8"),
    readFile(new URL("../components/release-history-control.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/release-history.css", import.meta.url), "utf8"),
    readFile(new URL("../../.github/workflows/deploy-shared-v44-testapp.yml", import.meta.url), "utf8"),
  ]);

  assert.match(version, /WEBAPP_VERSION = "46"/);
  assert.match(version, /WEBAPP_BUILD_NUMBER = "374"/);
  assert.match(history, /build: WEBAPP_BUILD_NUMBER/);
  assert.match(history, /version: WEBAPP_VERSION/);
  assert.match(history, /v\$\{WEBAPP_VERSION\}-build-\$\{WEBAPP_BUILD_NUMBER\}-release-history/);

  assert.match(layout, /<ReleaseHistoryControl \/>/);
  assert.doesNotMatch(layout, /<span className="runtime-name">CRYPTO BOT 2026<\/span>/);
  assert.match(layout, /data-webapp-build=\{WEBAPP_BUILD_NUMBER\}/);
  assert.match(layout, /<AppVersionControl \/>/);
  assert.match(layout, /<PwaRegistration \/>/);

  assert.match(control, /Versiegeschiedenis/);
  assert.match(control, /amar\.releaseHistory\.lastReadBuild\.v1/);
  assert.match(control, /localStorage\.setItem\(READ_BUILD_KEY/);
  assert.match(control, /unreadCount/);
  assert.match(control, /Zoek in versiegeschiedenis/);
  assert.match(control, /Versiegeschiedenis sluiten/);
  assert.match(control, /Probleem/);
  assert.match(control, /Oorzaak/);
  assert.match(control, /Oplossing/);
  assert.match(control, /Voorheen/);

  assert.match(css, /\.release-history-overlay\{position:fixed/);
  assert.match(css, /@media\(max-width:420px\)/);
  assert.match(css, /@media\(max-width:350px\)/);
  assert.match(css, /grid-template-columns:1fr/);

  assert.match(workflow, /Verify canonical release-history contract/);
  assert.match(workflow, /web\/lib\/app-version\.ts/);
  assert.match(workflow, /web\/lib\/release-history\.ts/);
  assert.match(workflow, /candidate <= current/);
  assert.doesNotMatch(workflow, /WEBAPP_BUILD_NUMBER=\$\{GITHUB_RUN_NUMBER\}/);
  assert.match(workflow, /WEBAPP_BUILD_NUMBER=\$\{WEBAPP_BUILD_NUMBER\}/);
});

test("history includes confirmed Git baseline and reconstructed pre-Git milestones without inventing missing builds", async () => {
  const history = await readFile(new URL("../lib/release-history.ts", import.meta.url), "utf8");

  assert.match(history, /d8dae028f79cb831e6f23d209ba220b3f7c253e6/);
  assert.match(history, /version: "2\.39"/);
  assert.match(history, /build: "207"/);
  assert.match(history, /releasedAt: "2026-08-05T19:56:29\+02:00"/);

  assert.match(history, /version: "0\.1\.0-dev"/);
  assert.match(history, /build: "1"/);
  assert.match(history, /releasedAt: "2026-07-28"/);

  assert.match(history, /version: "001"/);
  assert.match(history, /build: null/);
  assert.match(history, /confidence: "reconstructed"/);
  assert.match(history, /exacte .*buildnummers/i);
});
