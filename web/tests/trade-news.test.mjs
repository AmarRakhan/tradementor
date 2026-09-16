import test from "node:test";
import assert from "node:assert/strict";
import {
  activityEventsForItem,
  buildTradeNews,
  filterTradeNews,
  recoveryFromCandles,
  timeframeStart,
  weightedAverageEntry,
} from "../lib/trade-news.mjs";

test("24h only includes closed winners inside the selected window", () => {
  const now = Date.parse("2026-09-14T18:00:00Z");
  const history = {
    closedTrades: [
      { exchangeTradeId: "new", symbol: "HYPEUSDT", side: "LONG", realizedPnlUsd: 12.63, closedAt: "2026-09-14T17:00:00Z", exitPrice: 44.91 },
      { exchangeTradeId: "old", symbol: "BNBUSDT", side: "LONG", realizedPnlUsd: 8, closedAt: "2026-09-12T17:00:00Z", exitPrice: 620 },
    ],
  };
  const items = buildTradeNews({ account: {}, history, timeframe: "24h", now });
  const winners = filterTradeNews(items, "wins");
  assert.equal(winners.length, 1);
  assert.equal(winners[0].symbol, "HYPEUSDT");
  assert.equal(winners[0].pnlUsd, 12.63);
});

test("under pressure is derived from real position entry, mark and pnl", () => {
  const now = Date.parse("2026-09-14T18:00:00Z");
  const account = {
    positions: [{ symbol: "ASTERUSDT", side: "LONG", quantity: 100, entryPrice: 1.5, markPrice: 1.48, unrealizedPnl: -7.6, leverage: 50 }],
  };
  const items = buildTradeNews({ account, history: {}, timeframe: "15m", now });
  const pressure = filterTradeNews(items, "pressure");
  assert.equal(pressure.length, 1);
  assert.equal(pressure[0].symbol, "ASTERUSDT");
  assert.ok(pressure[0].roiPct < -1.3);
});

test("stable positions do not generate pressure news", () => {
  const account = {
    positions: [{ symbol: "BNBUSDT", side: "LONG", quantity: 1, entryPrice: 600, markPrice: 599.5, unrealizedPnl: -0.5 }],
  };
  const items = buildTradeNews({ account, history: {}, timeframe: "15m", now: Date.now() });
  assert.equal(filterTradeNews(items, "pressure").length, 0);
});

test("recovery uses actual candle low and remains silent below materiality threshold", () => {
  const position = { symbol: "BNBUSDT", side: "LONG", entryPrice: 520, markPrice: 515, unrealizedPnl: -2.3 };
  const now = Date.parse("2026-09-14T18:00:00Z");
  const candles = [
    { time: Date.parse("2026-09-14T17:30:00Z") / 1000, open: 515, high: 516, low: 510, close: 511 },
    { time: Date.parse("2026-09-14T17:45:00Z") / 1000, open: 511, high: 516, low: 511, close: 515 },
  ];
  const item = recoveryFromCandles(position, candles, "1h", now);
  assert.ok(item);
  assert.ok(item.roiPct > 0.9);

  const tiny = recoveryFromCandles({ ...position, markPrice: 512 }, candles, "1h", now);
  assert.equal(tiny, null);
});

test("activity reconstruction only labels confirmed entry rows as entry/DCA", () => {
  const history = {
    recentTradeActivity: {
      entries: [
        { id: "e1", symbol: "HYPEUSDT", side: "LONG", quantity: 2, averagePrice: 43.82, timestampMs: 1000 },
        { id: "e2", symbol: "HYPEUSDT", side: "LONG", quantity: 1, averagePrice: 43.20, timestampMs: 2000 },
      ],
      exits: [],
    },
  };
  const item = { id: "x", symbol: "HYPEUSDT", side: "LONG", openedAt: 1000, closedAt: null };
  const events = activityEventsForItem(item, history);
  assert.equal(events.length, 2);
  assert.equal(events[0].kind, "entry");
  assert.equal(events[1].kind, "dca");
  assert.equal(events[1].price, 43.2);
  assert.equal(weightedAverageEntry(events), (2 * 43.82 + 1 * 43.2) / 3);
});

test("today uses the local browser/server day boundary", () => {
  const now = new Date(2026, 8, 14, 21, 0, 0).getTime();
  const start = timeframeStart("today", now);
  const date = new Date(start);
  assert.equal(date.getHours(), 0);
  assert.equal(date.getMinutes(), 0);
});
