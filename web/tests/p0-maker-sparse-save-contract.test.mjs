import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
const route = readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts",import.meta.url),"utf8");

test("main configurator may use sparse settings only against server-confirmed values",()=>{
 assert.match(maker,/const confirmedSettings = persisted/);
 assert.match(maker,/seatChanged && !otherChanged/);
 assert.match(maker,/selectSparseBotEdit\\(confirmedSettings, settings, \\["maximumPositions"\\]\\)/);
});
test("main configurator keeps guarded full-save for complex changes",()=>{
 assert.match(maker,/const outgoingSettings = isolatedSave \\? seatPatch/);
 assert.match(maker,/await withLatestProfitLockSettings\(settings\)/);
 assert.doesNotMatch(maker,/selectSparseBotEdit\\(confirmedSettings, settings, \\["entryFilterMode"\\]/);
});
test("sparse route refuses unapproved keys and passes backend 409 and 422 unchanged",()=>{
 assert.match(route,/keys\.every\(\(key\) => isolatedEditKeys\.has\(key\)\)/);
 assert.match(route,/return proxyStrategy2Live\(request, "\/v1\/me\/aster\/strategy2\/settings", "PUT"\)/);
});

test("sparse confirmation checks effective sizing from full intended draft, not missing patch field",()=>{
 assert.match(maker,/const outgoingSizingMode = String\(settings\.entrySizingMode \|\| "margin"\)/);
 assert.doesNotMatch(maker,/const outgoingSizingMode = String\(outgoingSettings\.entrySizingMode/);
});
