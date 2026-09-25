import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const view = readFileSync(new URL("../components/friends-view.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../components/friends-view.module.css", import.meta.url), "utf8");
const bridge = readFileSync(new URL("../components/friends-navigation-bridge.tsx", import.meta.url), "utf8");
const bridgeCss = readFileSync(new URL("../app/friends-bridge.css", import.meta.url), "utf8");
const layout = readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8");

test("friends view keeps four approved visual references", () => {
  for (const id of [
    "file_00000000482c820eb79648deaf26728b",
    "file_0000000020e881f7a6b8ed2dbcb30de1",
    "file_00000000c5d0820ea69cedf6cfd83029",
    "file_00000000ff74820bb4f33e59ac402422",
  ]) assert.match(view, new RegExp(id));
});

test("friends UI includes ranking, risk, profile settings and compare", () => {
  assert.match(view, /data-friends-screen="ranking"/);
  assert.match(view, /data-friends-screen="profile"/);
  assert.match(view, /data-friends-screen="compare"/);
  assert.match(view, /Risico afgeleid uit instellingen/);
  assert.match(view, /Vergelijk met jouw setup/);
  assert.match(view, /Geen risicometric is een/);
});

test("friends navigation has a real top-level destination", () => {
  assert.match(bridge, /dataset\.destination\s*=\s*"friends"/);
  assert.match(bridge, /FRIENDS/);
  assert.match(bridge, /tmView/);
});

test("friends mobile design has no horizontal overflow and responsive breakpoints", () => {
  assert.match(css, /max-width:380px/);
  assert.match(css, /min-width:560px/);
  assert.match(css, /width:min\(100%,760px\)/);
});

test("friends source never renders absolute portfolio value labels", () => {
  assert.doesNotMatch(view, /currentEquity|dayStartEquity|todayUsd|availableBalance|walletAddress|realizedPnlUsd/);
});


test("friends portal uses the same global isolation contract as working main views", () => {
  assert.match(bridge, /className="friends-portal"/);
  assert.match(bridgeCss, /\.content\[data-friends-active="true"\] > :not\(\.friends-portal\)\{display:none!important\}/);
  assert.match(bridgeCss, /\.content\[data-friends-active="true"\] > \.friends-portal\{display:block!important/);
  assert.match(layout, /import "\.\/friends-bridge\.css"/);
});
