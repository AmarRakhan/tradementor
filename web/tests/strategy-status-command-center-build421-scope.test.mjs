import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

const allowed=new Set([
  "web/app/portfolio-koers-chart.css",
  "web/components/aster-portfolio-snapshot-enhancer.tsx",
  "web/components/portfolio-koers-chart.tsx",
  "web/lib/app-version.ts",
  "web/lib/release-history.ts",
  "web/lib/strategy-status-command-center.mjs",
  "web/tests/strategy-status-command-center.test.mjs",
  "web/tests/strategy-status-command-center-ui.test.mjs",
  "web/tests/strategy-status-command-center-build421-scope.test.mjs",
]);

function currentBuild(){
  const source=readFileSync(fileURLToPath(new URL("../lib/app-version.ts",import.meta.url)),"utf8");
  return source.match(/WEBAPP_BUILD_NUMBER = "(\d+)"/)?.[1]||"";
}

test("Build 421 is owner-only presentation and touches no trading API backend auth or PWA files",(t)=>{
  if(currentBuild()!=="421")return t.skip("Build-specific guard");
  const eventPath=process.env.GITHUB_EVENT_PATH;
  if(!eventPath||!existsSync(eventPath))return t.skip("GitHub event metadata unavailable");
  const event=JSON.parse(readFileSync(eventPath,"utf8"));
  const base=event.pull_request?.base?.sha||event.before;
  if(!base||/^0+$/.test(base))return t.skip("No comparable base SHA");
  try{execFileSync("git",["fetch","--quiet","--depth=1","origin",base],{stdio:"ignore"});}catch{}
  const changed=execFileSync("git",["diff","--name-only",base,"HEAD"],{encoding:"utf8"}).split(/\r?\n/).filter(Boolean);
  const unexpected=changed.filter((file)=>!allowed.has(file));
  assert.deepEqual(unexpected,[],`Build 421 touched non-display scope: ${unexpected.join(", ")}`);
});
