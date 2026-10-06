import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const v3 = fs.readFileSync(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8");
const v2 = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const shell = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const version = fs.readFileSync(new URL("../lib/app-version.ts", import.meta.url), "utf8");
const history = fs.readFileSync(new URL("../lib/release-history.ts", import.meta.url), "utf8");

test("Build 544 is the live single-surface AsterBot release", () => {
  assert.match(version, /WEBAPP_BUILD_NUMBER = "544"/);
  assert.match(shell, /AsterStrategy2Maker/);
  assert.doesNotMatch(shell, /ConfiguratorV3|Nieuwe configurator|Oude instellingen/);
  assert.match(maker, /Prijszone-stoelen/);
});

test("retained Configurator 3.1 source keeps its historical references but is not routed live", () => {
  assert.match(v3, /file_0000000064fc8210b631ce0a8caebb42/);
  assert.match(v3, /file_000000003b5081f4bee8a56187006a03/);
  assert.match(v3, /data-rollout="opt-in-beta"/);
  assert.doesNotMatch(shell, /aster-bot-configurator-v3/);
  assert.match(history, /id: "v46-build-459-botconfigurator-v31"/);
});

test("retained V2 and V3 editors cannot create a second live settings route", () => {
  assert.match(v2, /Botconfigurator V2/);
  assert.match(v3, /\/api\/exchanges\/aster\/strategy2\/settings/);
  assert.doesNotMatch(shell, /aster-bot-configurator-v2|aster-bot-configurator-v3/);
  assert.match(maker, /\/api\/exchanges\/aster\/strategy2\/\$\{route\}/);
});

test("classic live surface keeps independent LONG SHORT entry and DCA values", () => {
  for (const key of ["entryMarginLong","entryMarginShort","longDcaAmount","shortDcaAmount"]) {
    assert.match(maker, new RegExp(key));
  }
  assert.match(maker, /LONG per prijszone/);
  assert.match(maker, /SHORT per prijszone/);
});
