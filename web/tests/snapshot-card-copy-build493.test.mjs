import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Build 493 keeps Snapshot subcopy inside Auto Hedge, Profit Sparen and Portfolio Cyclus cards", async () => {
  const [autoHedgeCss, profitCss, version] = await Promise.all([
    readFile(new URL("../app/position-loss-auto-hedge.css", import.meta.url), "utf8"),
    readFile(new URL("../app/profit-pot-snapshot.css", import.meta.url), "utf8"),
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
  ]);

  assert.match(version, /WEBAPP_BUILD_NUMBER = "493"/);

  assert.match(autoHedgeCss, /Build 493 — Snapshot row copy-fit polish/);
  assert.match(autoHedgeCss, /#aster-position-loss-auto-hedge-host \.plah-tile\{[\s\S]*grid-template-columns:17px minmax\(0,1fr\)[\s\S]*padding:6px 5px/);
  assert.match(autoHedgeCss, /#aster-position-loss-auto-hedge-host \.plah-tile-copy em\{[\s\S]*font-size:5\.45px/);

  assert.match(profitCss, /Build 493 — mobile Snapshot row copy-fit polish/);
  assert.match(profitCss, /\.aps-profit-save-card\{[\s\S]*padding:6px 6px/);
  assert.match(profitCss, /\.aps-profit-save-card em\{[\s\S]*font-size:5\.15px/);
  assert.match(profitCss, /\.aps-portfolio-cycle-card\.is-inactive,[\s\S]*grid-template-columns:17px minmax\(0,1fr\)[\s\S]*padding:6px 5px/);
  assert.match(profitCss, /\.aps-cycle-inactive-copy em\{[\s\S]*font-size:5\.3px/);
});
