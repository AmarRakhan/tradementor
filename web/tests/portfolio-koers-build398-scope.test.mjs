import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

const forbidden=new Set([
  "web/app/layout.tsx",
  "web/components/auth-provider.tsx",
  "web/components/auth-gate.tsx",
  "web/components/pwa-registration.tsx",
  "web/public/sw.js",
  "web/public/manifest.webmanifest",
]);

function currentBuild(){
  const source=readFileSync(fileURLToPath(new URL("../lib/app-version.ts",import.meta.url)),"utf8");
  return source.match(/WEBAPP_BUILD_NUMBER = "(\d+)"/)?.[1]||"";
}

test("Build 398 visual release does not modify startup/auth/PWA scope",(t)=>{
  if(currentBuild()!=="398")return t.skip("Build-specific guard");
  const eventPath=process.env.GITHUB_EVENT_PATH;
  if(!eventPath||!existsSync(eventPath))return t.skip("GitHub event metadata unavailable");
  const event=JSON.parse(readFileSync(eventPath,"utf8"));
  const base=event.pull_request?.base?.sha||event.before;
  if(!base||/^0+$/.test(base))return t.skip("No comparable base SHA");
  try{execFileSync("git",["fetch","--quiet","--depth=1","origin",base],{stdio:"ignore"});}catch{}
  const changed=execFileSync("git",["diff","--name-only",base,"HEAD"],{encoding:"utf8"})
    .split(/\r?\n/).filter(Boolean);
  const touched=changed.filter((path)=>forbidden.has(path));
  assert.deepEqual(touched,[],`Forbidden visual-release scope changed: ${touched.join(", ")}`);
});
