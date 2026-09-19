import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const card=await readFile(new URL("../components/portfolio-growth-card.tsx",import.meta.url),"utf8");
const route=await readFile(new URL("../app/api/exchanges/aster/portfolio-growth/daily/route.ts",import.meta.url),"utf8");
const page=await readFile(new URL("../app/page.tsx",import.meta.url),"utf8");
const exchangeData=await readFile(new URL("../lib/use-exchange-data.ts",import.meta.url),"utf8");

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


test("daily portfolio growth follows each confirmed Aster account snapshot",()=>{
  assert.match(card,/refreshKey\?: number \| null/);
  assert.match(card,/const loadDaily = useCallback/);
  assert.match(card,/portfolio-growth\/daily", \{ cache: "no-store" \}/);
  assert.match(card,/\[loadDaily, refreshKey\]/);
  assert.match(exchangeData,/serverUpdatedAt\?: number \| null/);
  assert.match(exchangeData,/serverUpdatedAt: updatedAt/);
  assert.match(page,/dailyRefreshKey=\{snapshot\.serverUpdatedAt \?\? null\}/);
  assert.match(page,/PortfolioGrowthCard onChanged=\{onChanged\} refreshKey=\{dailyRefreshKey\}/);
});
