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

test("News overview keeps the approved compact density and timeframe controls", async () => {
  const [view, css] = await Promise.all([read("../components/news-view.tsx"), read("../components/news-view.module.css")]);
  for (const timeframe of ["1m", "5m", "15m", "1u", "4u", "24u"]) assert.match(view, new RegExp(`\\"${timeframe}\\"`));
  assert.match(view, /Zoek nieuws, coin of onderwerp/);
  assert.match(view, /Opgeslagen/);
  assert.match(view, /Advies op timeframe/);
  assert.match(css, /min-height:66px/);
  assert.match(css, /rotateY\(180deg\)/);
  assert.match(css, /grid-template-columns:repeat\(6/);
});

test("News uses live sources and never sends trading mutations", async () => {
  const [view, route] = await Promise.all([read("../components/news-view.tsx"), read("../app/api/news/route.ts")]);
  assert.match(route, /news\.google\.com\/rss\/search/);
  assert.match(route, /coindesk\.com\/arc\/outboundfeeds\/rss/);
  assert.match(route, /decrypt\.co\/feed/);
  assert.match(route, /cointelegraph\.com\/rss/);
  assert.match(route, /dedupe/);
  assert.match(view, /universeTopN/);
  assert.match(view, /strategy2\/focus\/markets/);
  assert.doesNotMatch(view, /method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/i);
  assert.doesNotMatch(view, /\/start|\/stop|\/close-position|\/orders/i);
});
