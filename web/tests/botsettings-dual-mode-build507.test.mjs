import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const shell = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const legacy = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const v3 = fs.readFileSync(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8");
const proxy = fs.readFileSync(new URL("../app/api/preferences/bot-settings-ui/route.ts", import.meta.url), "utf8");
const backend = fs.readFileSync(new URL("../../cloud_api/main.py", import.meta.url), "utf8");

const slice = (source, start, end) => {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, "missing source block: " + start);
  return source.slice(a, b);
};

test("Build 507 exposes the exact dual-mode Botinstellingen rollout shell", () => {
  assert.match(shell, /file_00000000d63482109f11a4ef9574daf3/);
  assert.match(shell, /Oude instellingen/);
  assert.match(shell, /Klassieke weergave \(huidig\)/);
  assert.match(shell, /Nieuwe configurator/);
  assert.match(shell, /Vereenvoudigde configurator 3\.0/);
  assert.match(shell, /Beide versies gebruiken dezelfde instellingen en trading-engine/);
  assert.match(shell, /Je live bot en open posities blijven actief/);
});

test("tab switching only writes UI preference and never calls trading mutations", () => {
  const block = slice(shell, "const changeMode = async", "const fallback =");
  assert.match(block, /\/api\/preferences\/bot-settings-ui/);
  assert.match(block, /method: "PUT"/);
  assert.match(block, /\/api\/releases\/me/);
  assert.doesNotMatch(block, /strategy2\/settings/);
  assert.doesNotMatch(block, /strategy2\/start/);
  assert.doesNotMatch(block, /strategy2\/stop/);
  assert.doesNotMatch(block, /close/i);
});

test("legacy and configurator 3 remain two frontends on the same existing settings engine", () => {
  assert.match(shell, /<AsterStrategy2Maker \{\.\.\.props\} embedded \/>/);
  assert.match(shell, /<ConfiguratorV3 \{\.\.\.props\}/);
  assert.match(legacy, /embedded = false/);
  assert.match(v3, /\/api\/exchanges\/aster\/strategy2\/settings/);
  assert.match(legacy, /\/api\/exchanges\/aster\/strategy2\/\$\{route\}/);
});

test("normal users default to legacy while beta owner defaults to configurator3", () => {
  assert.match(backend, /default_mode = "configurator3" if _is_beta_owner\(user\) else "legacy"/);
  assert.match(backend, /mode: str = Field\(pattern="\^\(legacy\|configurator3\)\$"\)/);
});

test("configurator enrollment is sticky and switching back to legacy cannot disable live Zone Warriors", () => {
  assert.match(backend, /configurator3Enabled/);
  assert.match(backend, /enrolled = bool\(current\.get\("configurator3Enabled"\)\) or request\.mode == "configurator3" or _is_beta_owner\(user\)/);
  assert.match(backend, /if key == "zone_soldiers" and _bot_settings_configurator3_enrolled\(user\):\s+return True/);
  assert.match(backend, /if key == "zone_soldiers" and _bot_settings_configurator3_enrolled_for_uid\(uid\):\s+return True/);
});

test("new UI preference is user-scoped in cloud and proxied through the authenticated web API", () => {
  assert.match(proxy, /\/v1\/me\/preferences\/bot-settings-ui/);
  assert.match(backend, /user_reference\(user\)\.collection\("preferences"\)\.document\("botSettingsUi"\)/);
  assert.match(backend, /merge=True/);
});

test("Configurator 3 stays an explicit BETA UI while Zone Warriors requires a deliberate strategy save", () => {
  assert.match(v3, /data-rollout="opt-in-beta"/);
  assert.match(v3, /<span>BETA<\/span>/);
  assert.match(v3, /chooseStrategy\(true\)/);
  assert.match(v3, /zoneSoldiersOptInVersion: source\.zoneSoldiersEnabled \? 1 : 0/);
});
