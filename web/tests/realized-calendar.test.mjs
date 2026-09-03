import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("daily realized calendar keeps wins and losses and starts a new local day at midnight", async () => {
  const source = await readFile(new URL("../lib/realized-calendar.ts", import.meta.url), "utf8");
  assert.match(source, /getFullYear\(\)/);
  assert.match(source, /getMonth\(\) \+ 1/);
  assert.match(source, /day\.total \+= pnl/);
  assert.match(source, /grouped\.get\(todayKey\).*total: 0/);
});

test("Aster dashboard exposes today's result without the retired performance calendar", async () => {
  const [page, styles] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /GESLOTEN RESULTAAT VANDAAG/);
  assert.match(page, /realized-trades/);
  assert.match(page, /TRADES GESLOTEN/);
  assert.match(styles, /\.metric\.realized-today\.positive \.realized-amount \{ color:var\(--green\)/);
  assert.match(styles, /\.metric\.realized-today\.negative \.realized-amount \{ color:var\(--danger\)/);
  assert.doesNotMatch(page, /setInterval\(\(\) => setNow\(new Date\(\)\), 1000\)/);
  assert.match(page, /nextDay\.setHours\(24, 0, 0, 50\)/);
  assert.match(page, /visibilitychange/);
  assert.doesNotMatch(page, /AsterPerformancePanel/);
  assert.doesNotMatch(page, /Kalender gesloten resultaat/);
  assert.doesNotMatch(page, /Geselecteerde dag/);
});
