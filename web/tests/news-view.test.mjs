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

test("News overview keeps the approved compact density and Dutch timeframe controls", async () => {
  const [view, css] = await Promise.all([read("../components/news-view.tsx"), read("../components/news-view.module.css")]);
  for (const timeframe of ["1m", "5m", "15m", "1u", "4u", "24u"]) assert.match(view, new RegExp(`\\"${timeframe}\\"`));
  assert.match(view, /Zoek nieuws, munt of onderwerp/);
  assert.match(view, /Samenwerkingen/);
  assert.match(view, /Advies per tijdsvenster/);
  assert.match(view, /Nieuwsmeldingen/);
  assert.doesNotMatch(view, />Breaking news</);
  assert.doesNotMatch(view, /coin-universe/);
  assert.match(css, /min-height:70px/);
  assert.match(css, /rotateY\(180deg\)/);
  assert.match(css, /grid-template-columns:\s*repeat\(6/);
});

test("News uses live sources, Dutch translation and never sends trading mutations", async () => {
  const [view, route, dutchRoute] = await Promise.all([
    read("../components/news-view.tsx"),
    read("../app/api/news/route.ts"),
    read("../app/api/news-nl/route.ts"),
  ]);
  assert.match(route, /news\.google\.com\/rss\/search/);
  assert.match(route, /coindesk\.com\/arc\/outboundfeeds\/rss/);
  assert.match(route, /decrypt\.co\/feed/);
  assert.match(route, /cointelegraph\.com\/rss/);
  assert.match(route, /dedupe/);
  assert.match(route, /LINK:\s*\["chainlink", "\$link", "link token"\]/);
  assert.match(route, /ZEC:\s*\["zcash", "zec"\]/);
  assert.doesNotMatch(route, /LINK:\s*\["chainlink", "link"\]/);
  assert.match(dutchRoute, /translation\.googleapis\.com\/language\/translate\/v2/);
  assert.match(dutchRoute, /api\.mymemory\.translated\.net\/get/);
  assert.match(dutchRoute, /translate\.googleapis\.com\/translate_a\/single/);
  assert.match(view, /\/api\/news-nl/);
  assert.match(view, /universeTopN/);
  assert.match(view, /strategy2\/focus\/markets/);
  assert.doesNotMatch(view, /method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/i);
  assert.doesNotMatch(view, /\/start|\/stop|\/close-position|\/orders/i);
});

test("Opened News builds an expanded source-based article inside the app", async () => {
  const [view, digestRoute, expanded, detailCss, expandedCss] = await Promise.all([
    read("../components/news-view.tsx"),
    read("../app/api/news-article/route.ts"),
    read("../components/news-article-expanded.tsx"),
    read("../components/news-article-detail.module.css"),
    read("../components/news-article-expanded.module.css"),
  ]);
  assert.match(view, /\/api\/news-article/);
  assert.match(view, /NewsArticleExpanded/);
  assert.match(view, /image:selected\.imageUrl/);
  assert.match(view, /coin:selected\.coins\[0\]/);
  assert.match(expanded, /Kort uitgelegd/);
  assert.match(expanded, /Wat is er gebeurd\?/);
  assert.match(expanded, /Belangrijkste punten/);
  assert.match(expanded, /Waar moet je op letten\?/);
  assert.match(expanded, /Conclusie/);
  assert.match(digestRoute, /extractArticleText/);
  assert.match(digestRoute, /sections/);
  assert.match(digestRoute, /watchFor/);
  assert.match(digestRoute, /conclusion/);
  assert.match(digestRoute, /extractImage/);
  assert.match(digestRoute, /capWords\(translated.*520/);
  assert.match(digestRoute, /lookup\(url\.hostname/);
  assert.match(digestRoute, /redirect:\s*"manual"/);
  assert.match(digestRoute, /De brontekst wordt niet integraal overgenomen/);
  assert.match(detailCss, /\.sourceLink/);
  assert.match(detailCss, /font-size:\s*8\.5px/);
  assert.match(expandedCss, /\.hero\[data-source-image="false"\]/);
  assert.doesNotMatch(view, /Lees volledig artikel/);
});

test("News detail measures factual Aster price impact separately from expected sentiment", async () => {
  const [expanded, impactRoute] = await Promise.all([
    read("../components/news-article-expanded.tsx"),
    read("../app/api/news-impact/route.ts"),
  ]);
  assert.match(expanded, /KOERSREACTIE/);
  assert.match(expanded, /\/api\/news-impact/);
  assert.match(expanded, /Nieuws gepubliceerd/);
  assert.match(expanded, /Nog niet beschikbaar/);
  assert.match(expanded, /Verwachte nieuwsimpact/);
  assert.match(expanded, /Gemeten reactie/);
  assert.match(expanded, /Mogelijk ingeprijsd/);
  assert.match(impactRoute, /fapi\.asterdex\.com\/fapi\/v1\/klines/);
  for (const timeframe of ["1m", "5m", "15m", "1u", "4u", "24u"]) assert.match(impactRoute, new RegExp(`\\"${timeframe}\\"`));
  assert.match(impactRoute, /publicationPrice/);
  assert.match(impactRoute, /currentPrice/);
  assert.match(impactRoute, /highPercent/);
  assert.match(impactRoute, /lowPercent/);
  assert.match(impactRoute, /pricedIn/);
  assert.doesNotMatch(impactRoute, /method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/i);
  assert.doesNotMatch(impactRoute, /\/start|\/stop|\/close-position|\/orders/i);
});

test("Detail double tap reverses the 3D flip without treating scroll or controls as taps", async () => {
  const view = await read("../components/news-view.tsx");
  assert.match(view, /handleDetailPointerDown/);
  assert.match(view, /handleDetailPointerUp/);
  assert.match(view, /handleDetailDoubleClick/);
  assert.match(view, /movement > 14/);
  assert.match(view, /data-no-doubletap/);
  assert.match(view, /setFlipped\(false\)/);
  assert.match(view, /680/);
  assert.match(view, /className=\{styles\.backButton\} onClick=\{closeDetail\}/);
  assert.doesNotMatch(view, /onDoubleClick=\{\(\) => setSelected\(null\)\}/);
});
