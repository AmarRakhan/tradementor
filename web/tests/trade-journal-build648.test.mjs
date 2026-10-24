import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  readTradeHistoryCache, writeTradeHistoryCache, tradeHistoryCacheKey, tradeHistoryFileName,
  tradeHistoryFileContent, syncProgressLabel, tradeRowKey, TRADE_HISTORY_CACHE_MAX_ROWS,
} from "../lib/trade-journal.mjs";

class MemoryStorage {
  constructor() { this.map = new Map(); }
  getItem(key) { return this.map.has(key) ? this.map.get(key) : null; }
  setItem(key, value) { this.map.set(key, String(value)); }
}

test("remembered list is per account, capped and survives bad storage", () => {
  const storage = new MemoryStorage();
  const rows = Array.from({ length: TRADE_HISTORY_CACHE_MAX_ROWS + 5 }, (_, i) => ({ id: `t${i}`, symbol: "BTCUSDT" }));
  assert.equal(writeTradeHistoryCache(storage, "uid-a", rows, "journal", 123), true);
  const cached = readTradeHistoryCache(storage, "uid-a");
  assert.equal(cached.rows.length, TRADE_HISTORY_CACHE_MAX_ROWS);
  assert.equal(cached.source, "journal");
  assert.equal(cached.savedAt, 123);
  assert.equal(readTradeHistoryCache(storage, "uid-b"), null);
  assert.equal(readTradeHistoryCache(storage, ""), null);
  storage.setItem(tradeHistoryCacheKey("uid-c"), "{not json");
  assert.equal(readTradeHistoryCache(storage, "uid-c"), null);
  const throwing = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(readTradeHistoryCache(throwing, "uid-a"), null);
  assert.equal(writeTradeHistoryCache(throwing, "uid-a", rows, "legacy"), false);
});

test("export file name, content and progress text", () => {
  assert.equal(tradeHistoryFileName(new Date(2026, 9, 24, 9, 5)), "tradementor-trade-historie-2026-10-24-0905.json");
  const content = JSON.parse(tradeHistoryFileContent({ schema: "tradementor.trade-journal.v1", app: { build: "abc" }, trades: [] }, "648"));
  assert.equal(content.schema, "tradementor.trade-journal.v1");
  assert.deepEqual(content.app, { build: "abc", webappBuild: "648" });
  assert.equal(syncProgressLabel({ progress: { percent: 41.6 } }), "Historie ophalen… 42%");
  assert.equal(syncProgressLabel(null), "Historie ophalen…");
  assert.equal(tradeRowKey({ id: "x" }), "x");
  assert.equal(tradeRowKey({ exchangeTradeId: "9" }), "9");
});

test("card: remembered list first, journal refresh, download button under the close button", async () => {
  const card = await readFile(new URL("../components/closed-trades-flip.tsx", import.meta.url), "utf8");
  assert.match(card, /readTradeHistoryCache\(storage\(\), uid\)/);
  assert.match(card, /useState\(!cached\)/);                                   // no "Trades laden…" when remembered
  assert.match(card, /\/api\/exchanges\/aster\/trade-journal\/recent/);
  assert.match(card, /\/api\/exchanges\/aster\/trade-journal\/sync/);
  assert.match(card, /\/api\/exchanges\/aster\/trade-journal\/export/);
  assert.match(card, /\/api\/exchanges\/aster\/closed-trades/);                 // old list while the journal is built
  const actions = card.indexOf('className="aps-closed-actions"');
  const close = card.indexOf('aria-label="Terug"', actions);
  const download = card.indexOf("data-trade-history-download", actions);
  assert.ok(actions > 0 && close > actions && download > close, "download sits under ×");
  assert.match(card, /Alleen beschikbare gegevens · ontbrekende velden worden niet geschat/);
});

test("proxy routes, sign-out cleanup and background sync are wired", async () => {
  const [recent, sync, exp, auth, enhancer, hook] = await Promise.all([
    readFile(new URL("../app/api/exchanges/aster/trade-journal/recent/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/trade-journal/sync/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/trade-journal/export/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../components/auth-provider.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/trade-journal-background-sync.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(recent, /\/v1\/me\/aster\/trade-journal\/recent\?limit=/);
  assert.match(sync, /"\/v1\/me\/aster\/trade-journal\/sync", "POST"/);
  assert.match(exp, /"\/v1\/me\/aster\/trade-journal\/export", "GET"/);
  assert.match(auth, /tradementor\.tradeHistory\.v1\./);
  assert.match(enhancer, /useTradeJournalBackgroundSync\(\);/);
  assert.match(hook, /document\.visibilityState !== "visible"/);
});
