import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Build 657 (Amar 24-10): Auto Hedge-scherm opgeruimd volgens zijn voorbeeld. Alleen opmaak: elke knop, schakelaar en
// elk veld moet blijven bestaan met dezelfde actie. Deze test telt ze, zodat een volgende opmaakwijziging er geen kwijtraakt.
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), "utf8");
const bridge = read("components/aster-position-loss-auto-hedge-bridge.tsx");
const card = read("components/short-recovery-card.tsx");
const preview = read("components/hedge-preview.tsx");
const css = read("app/position-loss-auto-hedge.css");
const count = (src, re) => (src.match(re) || []).length;

test("alle bedieningselementen van het Auto Hedge-scherm blijven bestaan", () => {
  for (const label of ["Auto Hedge hoofdschakelaar", "LONG-posities beschermen", "SHORT-posities beschermen", "Hedge mag groter dan positie",
    "Auto Hedge verliesgrens LONG", "Auto Hedge verliesgrens SHORT", "Max hedge in procent bij een LONG-positie",
    "Max hedge in procent bij een SHORT-positie", "Filter gehedgde coins"]) assert.ok(bridge.includes(`"${label}"`), label);
  assert.match(bridge, /id="plah-threshold-number"/);
  assert.match(bridge, /id="plah-threshold-short-number"/);
  assert.match(bridge, /Terug naar Dashboard/);
  assert.match(bridge, /"AUTO_HEDGE_CHECK"/);
  assert.equal(count(bridge, /hedgeSide="(SHORT|LONG)"/g), 2);
  assert.equal(count(bridge, /touched\.current = true/g), 9);
  for (const label of ["Totale ${move} voor afbouw", "Aantal afbouwstappen", "Terugkopen na aantal stappen", "Terughedgen in procent", "Noodrem in procent"])
    assert.ok(card.includes(label), label);
  assert.match(card, /onClick=\{\(\) => setDist\(d\.key\)\}/);
  assert.match(card, /onClick=\{\(\) => void save\(\)\}/);
  assert.match(card, /-hedge afbouwen aan of uit/);
  for (const label of ["Inleg voor mijn instellingen", "Instellingen voor mijn inleg", "Neem deze instellingen over", "Inleg per trade", "Hefboom"])
    assert.ok(preview.includes(label), label);
  assert.match(preview, /setScenario\(s\.key\)/);
  assert.match(preview, /setGoal\(g\.key\)/);
});

test("nieuwe indeling: LONG en SHORT naast elkaar, tegels, voorbeeld en advies naast elkaar", () => {
  assert.ok(bridge.indexOf('className="plah-sides"') < bridge.indexOf('hedgeSide="SHORT"'), "beschermkaarten boven de afbouwkaarten");
  assert.match(bridge, /plah-side plah-side-long/);
  assert.match(bridge, /plah-side plah-side-short/);
  assert.match(bridge, /className="plah-above-card"/);
  assert.match(card, /plah-unwind-top/);
  assert.match(card, /plah-unwind-row3/);
  assert.equal(count(card, /className="plah-tile3 (down|up|stop)"/g), 3);
  assert.match(preview, /className="hp-main"/);
  assert.match(css, /\.plah-sides\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(css, /@media\(max-width:359px\)\{\n  \.plah-sides,\.plah-unwind-top\.on,\.plah-unwind-card \.hp\{grid-template-columns:minmax\(0,1fr\)\}/);
});
