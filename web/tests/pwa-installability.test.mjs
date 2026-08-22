import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Amar Crypto Bot 2026 has a standalone installable manifest", async () => {
  const manifest = JSON.parse(await readFile(new URL("../public/manifest.webmanifest", import.meta.url), "utf8"));
  assert.equal(manifest.name, "Amar Crypto Bot 2026");
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.scope, "/");
  assert.match(manifest.start_url, /source=pwa/);
  assert.ok(manifest.icons.some((icon) => icon.sizes === "192x192" && icon.purpose.includes("any")));
  assert.ok(manifest.icons.some((icon) => icon.sizes === "512x512" && icon.purpose.includes("maskable")));
});

test("service worker uses Samsung Internet native installation without an in-app prompt", async () => {
  const worker = await readFile(new URL("../public/sw.js", import.meta.url), "utf8");
  const registration = await readFile(new URL("../components/pwa-registration.tsx", import.meta.url), "utf8");
  assert.match(worker, /skipWaiting/);
  assert.match(worker, /clients\.claim/);
  assert.match(worker, /respondWith/);
  assert.match(worker, /offline\.html/);
  assert.doesNotMatch(registration, /beforeinstallprompt/);
  assert.match(registration, /serviceWorker\.register/);
  assert.match(registration, /updateViaCache: "none"/);
  assert.match(registration, /appVersion=\$\{WEBAPP_VERSION\}/);
  assert.match(worker, /request\.url\.includes\("\/api\/"\)/);
});

test("private staging fetches its manifest with the signed-in session", async () => {
  const layout = await readFile(new URL("../app/layout.tsx", import.meta.url), "utf8");
  const registration = await readFile(new URL("../components/pwa-registration.tsx", import.meta.url), "utf8");
  const version = await readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8");
  assert.match(layout, /rel="manifest"/);
  assert.match(layout, /crossOrigin="use-credentials"/);
  assert.match(layout, /manifest\.webmanifest\?v=\$\{WEBAPP_VERSION\}/);
  assert.doesNotMatch(layout, /manifest:\s*["']/);
  assert.match(registration, /sw\.js\?v=\$\{WEBAPP_VERSION\}&build=\$\{buildNumber\}/);
  assert.match(registration, /buildNumber/);
  assert.match(registration, /WEBAPP_VERSION/);
  assert.match(version, /WEBAPP_VERSION = "45"/);
});
