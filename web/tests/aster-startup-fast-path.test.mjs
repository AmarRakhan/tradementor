import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const [hook, provider, page, version] = await Promise.all([
  readFile(new URL("../lib/use-exchange-data.ts", import.meta.url), "utf8"),
  readFile(new URL("../components/auth-provider.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
]);

test("Build 504 starts the authenticated Aster snapshot before session bootstrap finishes", () => {
  assert.match(hook, /if \(!uid\) return;[\s\S]{0,300}void refresh\("aster"\)/);
  assert.match(hook, /Startup fast path/);
  assert.match(hook, /function fetchAsterSnapshot\(uid: string, _generation: number\)[\s\S]*?const key = `\$\{uid\}:aster`/);
});

test("Build 504 starts Aster realtime from the authenticated Firebase user, not cloudReady", () => {
  const realtimeStart = hook.indexOf('authenticatedStream("/api/exchanges/aster/realtime"');
  assert.ok(realtimeStart > 0);
  const effectStart = hook.lastIndexOf("useEffect(() => {", realtimeStart);
  const effectPrefix = hook.slice(effectStart, realtimeStart);
  assert.match(effectPrefix, /if \(!uid\) return;/);
  assert.doesNotMatch(effectPrefix, /!cloudReady/);
});

test("startup network waits are bounded and action gate no longer waits on unrelated bootstrap", () => {
  assert.match(hook, /setTimeout\(\(\) => controller\.abort\(\), 6_000\)/);
  assert.match(provider, /fetch\("\/api\/session\/bootstrap"[\s\S]{0,500}controller\.signal/);
  assert.match(provider, /setTimeout\(\(\) => controller\.abort\(\), 6_000\)/);
  const helper = page.match(/function asterActionsAreFresh[\s\S]*?\n\}/)?.[0] ?? "";
  assert.match(helper, /snapshot\.serverConfirmed/);
  assert.doesNotMatch(helper, /cloudReady\s*&&/);
  assert.match(page, /fieldset className="aster-action-gate" disabled=\{!asterActionsEnabled\}/);
});

test("release metadata stays at or above the startup performance build", () => {
  const build = Number(version.match(/WEBAPP_BUILD_NUMBER = "(\d+)"/)?.[1] ?? "0");
  assert.ok(build >= 504);
});
