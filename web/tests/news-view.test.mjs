import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("News is mounted without changing the trading page destination model", async () => {
  const [layout, page, bridge, marketsBridge] = await Promise.all([
    read("../app/layout.tsx"),
    read("../app/page.tsx"),
    read("../components/news-navigation-bridge.tsx"),
    read("../components/markets-navigation-bridge.tsx"),
  ]);
  assert.match(layout, /NewsNavigationBridge/);
  assert.match(bridge, /\["markets", "aster", "news", "journey", "wallet"\]/);
  assert.match(marketsBridge, /\["markets", "aster", "news", "journey", "wallet"\]/);
  assert.match(bridge, /createPortal/);
  assert.doesNotMatch(page, /type Destination = [^;]*"news"/);
});

test("Mijn Nieuws overview is personal trade news with the approved filters and time windows", async () => {
  const [view, css, tradeNews] = await Promise.all([
    read("../components/news-view.tsx"),
    read("../components/news-view.module.css"),
    read("../lib/trade-news.mjs"),
  ]);

  assert.match(view, /<h1>Mijn Nieuws<\/h1>/);
  assert.match(view, /Jouw trades\. Jouw verhaal\. Automatisch gegenereerd\./);
  assert.match(view, /TRADE_NEWS_FILTERS/);
  assert.match(view, /TRADE_NEWS_TIMEFRAMES/);
  assert.match(view, /Portfolio/);
  assert.match(view, /Open PnL/);
  assert.match(view, /Actieve posities/);
  assert.match(view, /Geen materiële update in dit tijdsvenster/);

  for (const timeframe of ["15m", "1h", "4h", "today", "24h", "cycle"]) {
    assert.match(tradeNews, new RegExp(`key:\\s*\\"${timeframe}\\"`));
  }
  for (const filter of ["all", "wins", "pressure", "updates", "portfolio"]) {
    assert.match(tradeNews, new RegExp(`key:\\s*\\"${filter}\\"`));
  }

  assert.match(css, /@media\(max-width:620px\)/);
  assert.match(css, /\.filters/);
  assert.match(css, /\.card/);
  assert.match(css, /\.detailBackdrop/);
});

test("Mijn Nieuws uses authenticated Aster portfolio data and never sends trading mutations", async () => {
  const view = await read("../components/news-view.tsx");

  assert.match(view, /authenticatedRequest\("\/api\/exchanges\/aster"/);
  assert.match(view, /authenticatedRequest\("\/api\/exchanges\/aster\/closed-trades"/);
  assert.match(view, /authenticatedRequest\(`\/api\/exchanges\/aster\/trade-events\?/);
  assert.match(view, /fetch\(`\/api\/market-data\?/);
  assert.match(view, /LIVE · echte Aster-data/);
  assert.match(view, /Geen extern cryptonieuws/);

  assert.doesNotMatch(view, /method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/i);
  assert.doesNotMatch(view, /\/start|\/stop|\/close-position|\/orders/i);
  assert.doesNotMatch(view, /\/api\/news-nl|\/api\/news-article/);
});

test("Opened Mijn Nieuws item builds an in-app trade story from confirmed fills and candles", async () => {
  const view = await read("../components/news-view.tsx");

  assert.match(view, /function DetailView/);
  assert.match(view, /VOLLEDIGE TRADE STORY/);
  assert.match(view, /ACTIEVE POSITIE/);
  assert.match(view, /Het verhaal van deze trade/);
  assert.match(view, /Execution timeline/);
  assert.match(view, /Trade summary/);
  assert.match(view, /Bevestigde fills en koersdata laden/);
  assert.match(view, /activityEventsForItem/);
  assert.match(view, /weightedAverageEntry/);
  assert.match(view, /<TradeMiniChart item=\{item\} candles=\{candles\} events=\{events\} large\/>/);
  assert.match(view, /Werkelijke koersgrafiek en fills/);
  assert.match(view, /Initial entry/);
  assert.match(view, /DCA \$\{event\.dcaNumber/);
  assert.match(view, /Exit/);
});

test("Mijn Nieuws materiality logic stays in the dedicated trade-news module", async () => {
  const tradeNews = await read("../lib/trade-news.mjs");

  assert.match(tradeNews, /function buildTradeNews|export function buildTradeNews/);
  assert.match(tradeNews, /recoveryFromCandles/);
  assert.match(tradeNews, /dcaUpdateFromEvents/);
  assert.match(tradeNews, /activityEventsForItem/);
  assert.match(tradeNews, /filterTradeNews/);
  assert.match(tradeNews, /weightedAverageEntry/);
});

test("Mijn Nieuws detail closes explicitly without the retired generic-news 3D flip contract", async () => {
  const [view, css] = await Promise.all([
    read("../components/news-view.tsx"),
    read("../components/news-view.module.css"),
  ]);

  assert.match(view, /role="dialog"/);
  assert.match(view, /aria-modal="true"/);
  assert.match(view, /aria-label="Sluiten"/);
  assert.match(view, /if \(event\.currentTarget === event\.target\) onClose\(\)/);
  assert.doesNotMatch(view, /handleDetailPointerDown|handleDetailPointerUp|handleDetailDoubleClick/);
  assert.doesNotMatch(css, /rotateY\(180deg\)/);
});
