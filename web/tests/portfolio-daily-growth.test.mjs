import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const card=await readFile(new URL("../components/portfolio-growth-card.tsx",import.meta.url),"utf8");
const route=await readFile(new URL("../app/api/exchanges/aster/portfolio-growth/daily/route.ts",import.meta.url),"utf8");

test("daily portfolio growth is compact inside the existing card",()=>{
  assert.match(card,/portfolio-growth-daily/);
  assert.match(card,/Vandaag/);
  assert.match(card,/Gemiddeld per dag/);
  assert.match(card,/Sinds 23 augustus 2026/);
  assert.doesNotMatch(card,/article className=.{0,40}daily-growth/);
});

test("daily portfolio growth uses the isolated read-only backend route",()=>{
  assert.match(route,/portfolio-growth\/daily/);
  assert.match(route,/"GET"/);
});
