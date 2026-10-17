import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("daily realized calendar keeps wins and losses and starts a new local day at midnight", async () => {
  const source = await readFile(new URL("../lib/realized-calendar.ts", import.meta.url), "utf8");
  assert.match(source, /timeZone: "Europe\/Amsterdam"/);
  assert.match(source, /Intl\.DateTimeFormat/);
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


test("Dutch midnight boundary is independent of server locale and handles DST", async () => {
  const { localDayKey, realizedCalendar } = await import("../lib/realized-calendar.ts");
  assert.equal(localDayKey(new Date("2026-10-13T21:59:59Z")), "2026-10-13");
  assert.equal(localDayKey(new Date("2026-10-13T22:00:00Z")), "2026-10-14");
  assert.equal(localDayKey(new Date("2026-03-28T22:59:59Z")), "2026-03-28");
  assert.equal(localDayKey(new Date("2026-03-28T23:00:00Z")), "2026-03-29");
  assert.equal(localDayKey(new Date("2026-03-29T21:59:59Z")), "2026-03-29");
  assert.equal(localDayKey(new Date("2026-03-29T22:00:00Z")), "2026-03-30");
  const result = realizedCalendar([
    {closedAt:"2026-10-13T21:59:59Z",realizedPnlUsd:2},
    {closedAt:"2026-10-13T22:00:00Z",realizedPnlUsd:3},
  ],new Date("2026-10-13T22:00:01Z"));
  assert.equal(result.today.total, 3);
  assert.equal(result.today.trades, 1);
});
