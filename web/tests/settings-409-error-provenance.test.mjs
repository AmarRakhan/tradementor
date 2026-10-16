import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const client = readFileSync(new URL("../lib/cloud-client.ts", import.meta.url), "utf8");
const settingsRoute = readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");

test("409 error from Strategy-2 safe guard remains visible instead of generic HTTP 409", () => {
  assert.match(settingsRoute, /status:409/);
  assert.match(settingsRoute, /error:"Filterinstellingen niet verifieerbaar/);
  assert.match(client, /\[payload\.detail, payload\.error\]\.find/);
  assert.match(client, /typeof serverMessage === "string" \? serverMessage/);
});

test("non-descriptive HTTP 409 names request method and path", () => {
  assert.match(client, /bij \$\{method\} \$\{path\}/);
});

test("settings guard still rejects unverifiable legacy spike configuration", () => {
  assert.match(settingsRoute, /missingSpikeMode \? safeFailure\(\) : request/);
  assert.match(settingsRoute, /if \(preserved instanceof Response\) return preserved/);
});

test("successful Strategy-2 settings PUT invalidates cached status before readback", () => {
  assert.match(client, /if \(method === "PUT" && path === "\/api\/exchanges\/aster\/strategy2\/settings"\) \{/);
  assert.match(client, /clearSharedAsterRequest\(\);/);
  assert.match(client, /if \(!response\.ok\) \{/);
});
