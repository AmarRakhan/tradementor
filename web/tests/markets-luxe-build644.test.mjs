import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  buildMarketRows, compactVolume, filterMarkets, marketCategory, ownershipBySymbol, signedPercent, sortMarkets, tradeMarkersFromEvents, iconAsset,
} from "../lib/markets-universe.mjs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const info = { symbols: [
  { symbol: "BTCUSDT", baseAsset: "BTC", quoteAsset: "USDT", status: "TRADING", contractType: "PERPETUAL", symbolType: 0, underlyingSubType: ["Top"], pricePrecision: 1 },
  { symbol: "XAUUSD1", baseAsset: "XAU", quoteAsset: "USD1", status: "TRADING", contractType: "PERPETUAL", symbolType: 1, name: "Gold", underlyingSubType: ["Commodities", "AOS2", "USD1-RWA"], pricePrecision: 2 },
  { symbol: "SKHYNIXUSD1", baseAsset: "SKHYNIX", quoteAsset: "USD1", status: "TRADING", contractType: "PERPETUAL", symbolType: 1, underlyingSubType: ["STOCK", "AOS2"], pricePrecision: 2 },
  { symbol: "BTCUSDC", baseAsset: "BTC", quoteAsset: "USDC", status: "TRADING", contractType: "PERPETUAL", symbolType: 0, underlyingSubType: [], pricePrecision: 1 },
  { symbol: "OLDUSDT", baseAsset: "OLD", quoteAsset: "USDT", status: "SETTLING", contractType: "PERPETUAL" },
  { symbol: "NEWUSDT", baseAsset: "NEW", quoteAsset: "USDT", status: "PENDING_TRADING", contractType: "" },
] };
const tickers = [
  { symbol: "BTCUSDT", lastPrice: "81341.3", priceChangePercent: "-0.13", quoteVolume: "311710000", highPrice: "82035", lowPrice: "81063.5" },
  { symbol: "XAUUSD1", lastPrice: "4004.39", priceChangePercent: "-0.81", quoteVolume: "347840000" },
  { symbol: "SKHYNIXUSD1", lastPrice: "953.7", priceChangePercent: "6.27", quoteVolume: "60420000" },
  { symbol: "BTCUSDC", lastPrice: "81340", priceChangePercent: "-0.1", quoteVolume: "1000" },
  { symbol: "OLDUSDT", lastPrice: "1", priceChangePercent: "0", quoteVolume: "9" },
];

test("Build 644: Markets lists every tradable Aster perpetual, not only USDT", () => {
  const rows = buildMarketRows(info, tickers);
  assert.deepEqual(rows.map((row) => row.symbol), ["XAUUSD1", "BTCUSDT", "SKHYNIXUSD1", "BTCUSDC"]);
  assert.deepEqual(rows.map((row) => row.quoteAsset), ["USD1", "USDT", "USD1", "USDC"]);
  assert.equal(rows[1].high24h, 82035);
  assert.equal(rows[0].name, "Gold");
});

test("Build 644: categories come from Aster's own labels", () => {
  assert.equal(marketCategory(info.symbols[0]), "crypto");
  assert.equal(marketCategory(info.symbols[1]), "commodity");
  assert.equal(marketCategory(info.symbols[2]), "stock");
  assert.equal(marketCategory({ symbolType: 1, underlyingSubType: ["pre-launch"] }), "stock");
});

test("Build 644: BOT and MANUAL labels follow ownership in the account snapshot", () => {
  const own = ownershipBySymbol([
    { symbol: "BTCUSDT", side: "LONG", strategyId: "aster-strategy-2", quantity: 1 },
    { symbol: "BTCUSDT", side: "SHORT", strategyId: "", positionLossAutoHedge: { status: "HEDGED" }, quantity: 1 },
    { symbol: "SOLUSDT", side: "LONG", strategyId: "", quantity: 2 },
    { symbol: "ETHUSDT", side: "LONG", strategyId: "", quantity: 0 },
  ]);
  assert.deepEqual(own.get("BTCUSDT"), { bot: true, manual: false });
  assert.deepEqual(own.get("SOLUSDT"), { bot: false, manual: true });
  assert.equal(own.has("ETHUSDT"), false);
});

test("Build 644: filters and sorting match the chips and columns", () => {
  const rows = buildMarketRows(info, tickers).map((row, index) => ({ ...row, bbStatus: ["above", "between", "below", null][index] }));
  const ownership = new Map([["BTCUSDT", { bot: true, manual: false }], ["SKHYNIXUSD1", { bot: false, manual: true }]]);
  assert.deepEqual(filterMarkets(rows, { owner: "free", ownership }).map((row) => row.symbol), ["XAUUSD1", "BTCUSDC"]);
  assert.deepEqual(filterMarkets(rows, { owner: "bot", ownership }).map((row) => row.symbol), ["BTCUSDT"]);
  assert.deepEqual(filterMarkets(rows, { owner: "manual", ownership }).map((row) => row.symbol), ["SKHYNIXUSD1"]);
  assert.deepEqual(filterMarkets(rows, { category: "stock" }).map((row) => row.symbol), ["SKHYNIXUSD1"]);
  assert.deepEqual(filterMarkets(rows, { query: "gold" }).map((row) => row.symbol), ["XAUUSD1"]);
  assert.deepEqual(sortMarkets(rows, "change", "desc").map((row) => row.symbol), ["SKHYNIXUSD1", "BTCUSDC", "BTCUSDT", "XAUUSD1"]);
  assert.deepEqual(sortMarkets(rows, "volume", "desc").map((row) => row.symbol)[0], "XAUUSD1");
  assert.deepEqual(sortMarkets(rows, "bb", "desc").map((row) => row.symbol), ["XAUUSD1", "BTCUSDT", "SKHYNIXUSD1", "BTCUSDC"]);
  assert.deepEqual(sortMarkets(rows, "symbol", "asc").map((row) => row.baseAsset), ["BTC", "BTC", "SKHYNIX", "XAU"]);
});

test("Build 644: numbers read like the design", () => {
  assert.equal(compactVolume(109_700_000), "109.70M");
  assert.equal(compactVolume(9_830_000), "9.83M");
  assert.equal(compactVolume(952_310), "952.31K");
  assert.equal(signedPercent(254.63), "+254.63%");
  assert.equal(signedPercent(-0.13), "-0.13%");
  assert.equal(iconAsset("1000PEPE"), "pepe");
});

test("Build 644: your fills become chart labels; a close above the average entry is a TP", () => {
  const markers = tradeMarkersFromEvents([
    { side: "LONG", action: "increase", price: 100, quantity: 1, timestampMs: 1_000_000 },
    { side: "LONG", action: "increase", price: 90, quantity: 1, timestampMs: 1_100_000 },
    { side: "LONG", action: "close", price: 110, quantity: 2, timestampMs: 2_000_000 },
    { side: "SHORT", action: "increase", price: 110, quantity: 1, timestampMs: 2_000_000 },
    { side: "SHORT", action: "close", price: 115, quantity: 1, timestampMs: 2_800_000 },
  ], [900, 1800, 2700]);
  assert.deepEqual(markers.map((marker) => marker.text), ["2× LONG", "TP +$30.00", "SHORT", "UIT SHORT -$5.00"]);
  assert.equal(markers[1].color, "#ffc320");
});

test("Build 644: server reads Aster's public universe and keeps the old route as fallback", () => {
  const route = read("../app/api/markets/aster/route.ts");
  assert.match(route, /fapi\/v1\/exchangeInfo/);
  assert.match(route, /fapi\/v1\/ticker\/24hr/);
  assert.match(route, /buildMarketRows/);
  assert.match(route, /account-fallback-usdt/);
  assert.doesNotMatch(route, /\/\^\[A-Z0-9\]\+USDT\$\//);
  const candles = read("../app/api/market-data/route.ts");
  assert.match(candles, /searchParams\.get\("market"\)/);
});

test("Build 644: Markets page matches the design and flips on double tap", () => {
  const page = read("../components/markets-page.tsx");
  for (const label of ["Alles", "Vrij", "In positie", "BOT", "MANUAL", "Alle", "Crypto", "Aandelen", "Grondstoffen", "SYMBOL", "24H VOL", "24H", "Zoek munt of symbool"]) assert.ok(page.includes(label), label);
  assert.match(page, /BB \(\{bbLabel\}\)/);
  assert.match(page, /UPPER[\s\S]*BINNEN[\s\S]*LOWER/);
  assert.match(page, /DOUBLE_TAP_MS/);
  assert.match(page, /<MarketsCoinFlip/);
  assert.doesNotMatch(page, /openMarket|open-aster-market/);
  assert.match(page, /subscribeAsterPositions/);
  const flip = read("../components/markets-coin-flip.tsx");
  assert.match(flip, /portfolio-koers-card portfolio-koers-ui41/);
  assert.match(flip, /PORTFOLIO_KOERS_TIMEFRAMES/);
  assert.match(flip, /bollinger20x2/);
  assert.match(flip, /trade-events\?symbol=/);
  assert.match(flip, /axisDoubleClickReset: false/);
  assert.match(flip, /rotateY\(180deg\)/);
  assert.match(flip, /createPortal/);
  const main = read("../app/page.tsx");
  assert.match(main, /publishAsterPositions\(positions\)/);
});

test("Build 645: on Home, Markets, Nieuws and Vrienden the Aster Tradecentrum and Botinstellingen stay hidden", () => {
  const css = read("../app/markets-bridge.css");
  for (const tab of ["markets", "news", "friends", "home"]) assert.ok(css.includes(`[data-${tab}-active="true"]`), tab);
  for (const portal of [".markets-portal", '[data-news-portal="true"]', ".friends-portal", ".tm-home-portal"]) assert.ok(css.includes(portal), portal);
  assert.match(css, /section\[aria-label="Aster Tradecentrum"\]/);
  assert.match(css, /\.dashboard-grid/);
});
