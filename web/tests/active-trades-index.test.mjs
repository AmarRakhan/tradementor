import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("Aster dashboard embeds active trades index inside trades-closed cell", () => {
  assert.match(page, /className="metric realized-trades"[\s\S]*?<ActiveTradesIndex/);
  assert.match(page, /ACTIEVE TRADES INDEX/);
  assert.match(page, /Open Actieve Trades Index fullscreen/);
});

test("active trades index uses side-aware margin-weighted live positions", () => {
  assert.match(page, /p\.side\.toLowerCase\(\)==="short"\?-1:1/);
  assert.match(page, /p\.leverage>0\?p\.size\/p\.leverage:p\.size/);
  assert.match(page, /contribution:r\.returnPct\*\(r\.weight\/total\)/);
  assert.match(page, /TOTAAL DCA/);
  assert.match(page, /BREADTH/);
});

test("active trades index fullscreen is mobile responsive and exposes six ranges", () => {
  for (const range of ["15m","1u","4u","12u","24u","7d"]) assert.match(page, new RegExp(`\\"${range}\\"`));
  assert.match(css, /\.ati-modal/);
  assert.match(css, /@media\(max-width:640px\)[\s\S]*?\.ati-kpis\{grid-template-columns:repeat\(2,1fr\)\}/);
});
