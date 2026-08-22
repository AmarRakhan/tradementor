import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workflow = await readFile(new URL("../../.github/workflows/deploy-shared-v44-testapp.yml", import.meta.url), "utf8");
const proxy = await readFile(new URL("../lib/cloud-proxy.ts", import.meta.url), "utf8");
const asterRoute = await readFile(new URL("../app/api/exchanges/aster/route.ts", import.meta.url), "utf8");
const serviceWorker = await readFile(new URL("../public/sw.js", import.meta.url), "utf8");

test("shared V45 testapp has one canonical Cloud Run service", () => {
  assert.match(workflow, /CLOUD_RUN_SERVICE: amar-bot-v44-direct-install/);
  assert.match(workflow, /GCP_PROJECT_ID: tradementor-production/);
  assert.match(workflow, /--to-revisions "\$CANDIDATE_REVISION=100"/);
  assert.match(workflow, /--no-traffic/);
  assert.match(workflow, /Verify candidate before traffic/);
  assert.match(workflow, /Rollback canonical traffic on failed post-promotion verification/);
  assert.match(workflow, /docker build --tag "\$IMAGE" web/);
  assert.match(workflow, /docker push "\$IMAGE"/);
  assert.match(workflow, /--image "\$IMAGE"/);
  assert.doesNotMatch(workflow, /--source web/);
});

test("shared V45 testapp reads the production Aster status directly", () => {
  assert.match(proxy, /https:\/\/tradementor-api-604335232956\.europe-west4\.run\.app/);
  assert.match(asterRoute, /proxyCloud\(request, "\/v1\/me\/aster\/status", "GET"\)/);
  assert.doesNotMatch(asterRoute, /strategy3|mergeAsterProjectStatus|proxyStrategy3Live/i);
});

test("shared V45 PWA contract stays pinned to version 45", () => {
  assert.match(serviceWorker, /amar-bot-shell-v45/);
});
