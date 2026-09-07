type NewsCategory = "Belangrijk" | "Koers" | "Analyse" | "Partnerships" | "Regulatie" | "Listing" | "ETF" | "Macro" | "Security" | "Exchange" | "Tokenomics" | "Ecosysteem";

type NewsArticle = {
  id: string;
  externalId: string;
  source: string;
  sourceUrl: string;
  title: string;
  summary: string;
  imageUrl: string;
  publishedAt: string;
  fetchedAt: string;
  coins: string[];
  categories: NewsCategory[];
  importance: "high" | "normal";
  sentiment: "bullish" | "bearish" | "neutral";
  sentimentScore: number;
  confidence: number;
};

const COIN_ALIASES: Record<string, string[]> = {
  BTC: ["bitcoin", "btc"], ETH: ["ethereum", "ether", "eth"], SOL: ["solana", "sol"], BNB: ["bnb", "bnb chain", "binance coin"],
  HYPE: ["hyperliquid", "hype"], XRP: ["xrp", "ripple"], DOGE: ["dogecoin", "doge"], ADA: ["cardano", "ada"],
  AVAX: ["avalanche", "avax"], LINK: ["chainlink", "$link", "link token"], ZEC: ["zcash", "zec"], DOT: ["polkadot", "dot"], SUI: ["sui"], AAVE: ["aave"],
  NEAR: ["near protocol", "near"], BCH: ["bitcoin cash", "bch"], LTC: ["litecoin", "ltc"], TRX: ["tron", "trx"],
  UNI: ["uniswap", "uni"], TON: ["toncoin", "the open network", "ton"], XLM: ["stellar", "xlm"], SHIB: ["shiba inu", "shib"],
  ATOM: ["cosmos", "atom"], ARB: ["arbitrum", "arb"], OP: ["optimism", "op"], INJ: ["injective", "inj"],
  FIL: ["filecoin", "fil"], RENDER: ["render", "rndr"], SEI: ["sei"], TIA: ["celestia", "tia"], ASTER: ["aster", "asterdex"],
};

const POSITIVE = ["surge", "rally", "rise", "rises", "gain", "gains", "record inflow", "approval", "approved", "adoption", "partnership", "integrat", "launch", "breakout", "accumulat", "buy", "bullish", "growth", "upgrade", "record high", "new high", "expands"];
const NEGATIVE = ["drop", "falls", "fall", "plunge", "selloff", "sell-off", "hack", "exploit", "outflow", "lawsuit", "ban", "crackdown", "liquidat", "bearish", "fraud", "breach", "attack", "reject", "rejected", "investigation", "delist"];
const IMPORTANT = ["sec ", "cftc", "federal reserve", " fed ", "ecb", "interest rate", "inflation", "cpi", "pce", "etf", "hack", "exploit", "lawsuit", "regulation", "regulator", "approval", "approved", "ban", "stablecoin", "bankruptcy", "record inflow"];

function stripPair(value: string) {
  return value.toUpperCase().trim().replace(/[^A-Z0-9]/g, "").replace(/(USDT|USDC|USD|PERP)$/i, "").replace(/^1000(?=[A-Z])/, "");
}

function decodeXml(value: string) {
  return value
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"")
    .replace(/&#39;|&apos;/g, "'").replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)));
}

function stripHtml(value: string) {
  return decodeXml(value).replace(/<style\b[\s\S]*?<\/style>/gi, " ").replace(/<script\b[\s\S]*?<\/script>/gi, " ").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function field(block: string, tag: string) {
  const safe = tag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = block.match(new RegExp(`<${safe}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${safe}>`, "i"));
  return match ? decodeXml(match[1]).trim() : "";
}

function attr(block: string, tag: string, name: string) {
  const safeTag = tag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const safeName = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = block.match(new RegExp(`<${safeTag}\\b[^>]*\\b${safeName}=["']([^"']+)["'][^>]*>`, "i"));
  return match ? decodeXml(match[1]).trim() : "";
}

function hash(value: string) {
  let h = 2166136261;
  for (let i = 0; i < value.length; i += 1) { h ^= value.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(36);
}

function normalizeTitle(value: string) {
  return stripHtml(value).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function splitGoogleTitle(value: string, fallbackSource: string) {
  const clean = stripHtml(value);
  const index = clean.lastIndexOf(" - ");
  if (index < 0) return { title: clean, source: fallbackSource };
  const source = clean.slice(index + 3).trim();
  const title = clean.slice(0, index).trim();
  return { title: title || clean, source: source || fallbackSource };
}

function parseRss(xml: string, fallbackSource: string, google = false) {
  const blocks = xml.match(/<item\b[\s\S]*?<\/item>/gi) || [];
  return blocks.flatMap((block) => {
    const rawTitle = field(block, "title");
    const link = field(block, "link") || field(block, "guid");
    if (!rawTitle || !link) return [];
    const parsedTitle = google ? splitGoogleTitle(rawTitle, fallbackSource) : { title: stripHtml(rawTitle), source: fallbackSource };
    const rawDescription = field(block, "description") || field(block, "content:encoded") || field(block, "content");
    const summary = stripHtml(rawDescription).slice(0, 1200);
    const publishedRaw = field(block, "pubDate") || field(block, "dc:date") || field(block, "date");
    const published = Date.parse(publishedRaw);
    const imageUrl = attr(block, "media:content", "url") || attr(block, "media:thumbnail", "url") || attr(block, "enclosure", "url");
    return [{
      externalId: field(block, "guid") || link,
      source: parsedTitle.source,
      sourceUrl: link,
      title: parsedTitle.title,
      summary,
      imageUrl,
      publishedAt: Number.isFinite(published) ? new Date(published).toISOString() : new Date().toISOString(),
    }];
  });
}

function includesWord(text: string, alias: string) {
  const escaped = alias.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`, "i").test(text);
}

function detectCoins(text: string, universe: string[]) {
  const lower = text.toLowerCase();
  return universe.filter((symbol) => {
    const aliases = COIN_ALIASES[symbol] || [symbol.toLowerCase()];
    return aliases.some((alias) => alias.length <= 3 ? includesWord(lower, alias.toLowerCase()) : lower.includes(alias.toLowerCase()));
  });
}

function classify(text: string) {
  const lower = ` ${text.toLowerCase()} `;
  const categories = new Set<NewsCategory>();
  if (/\b(sec|cftc|regulat|law|court|mica|compliance|ban)\b/i.test(lower)) categories.add("Regulatie");
  if (/\b(etf|exchange.traded fund)\b/i.test(lower)) categories.add("ETF");
  if (/\b(partner|collaborat|integrat|alliance)\b/i.test(lower)) categories.add("Partnerships");
  if (/\b(listing|listed|delist|exchange listing)\b/i.test(lower)) categories.add("Listing");
  if (/\b(hack|exploit|breach|attack|vulnerability|stolen)\b/i.test(lower)) categories.add("Security");
  if (/\b(exchange|binance|coinbase|kraken|bybit|okx|aster|hyperliquid)\b/i.test(lower)) categories.add("Exchange");
  if (/\b(burn|supply|tokenomics|unlock|staking|airdrop)\b/i.test(lower)) categories.add("Tokenomics");
  if (/\b(defi|ecosystem|network|developer|protocol|mainnet|testnet)\b/i.test(lower)) categories.add("Ecosysteem");
  if (/\b(federal reserve|\bfed\b|ecb|inflation|\bcpi\b|\bpce\b|interest rate|jobs report|payroll|treasury|dollar)\b/i.test(lower)) categories.add("Macro");
  if (/\b(price|rally|surge|breakout|drop|fall|gain|high|low|support|resistance)\b/i.test(lower)) categories.add("Koers");
  if (/\b(analysis|outlook|forecast|technical|on.chain|whale|trend|momentum)\b/i.test(lower)) categories.add("Analyse");
  if (!categories.size) categories.add("Analyse");

  let score = 0;
  for (const key of POSITIVE) if (lower.includes(key)) score += 1;
  for (const key of NEGATIVE) if (lower.includes(key)) score -= 1;
  score = Math.max(-5, Math.min(5, score));
  const sentimentScore = score / 5;
  const sentiment = score >= 1 ? "bullish" : score <= -1 ? "bearish" : "neutral";
  const importance = IMPORTANT.some((key) => lower.includes(key)) || categories.has("Security") ? "high" : "normal";
  if (importance === "high") categories.add("Belangrijk");
  const confidence = Math.min(0.92, 0.52 + Math.abs(score) * 0.08 + (importance === "high" ? 0.08 : 0));
  return { categories: Array.from(categories), sentiment, sentimentScore, importance, confidence } as const;
}

async function fetchFeed(url: string, source: string, google = false) {
  try {
    const response = await fetch(url, {
      headers: { "User-Agent": "CryptoBot2026-News/1.0 (+https://github.com/AmarRakhan/tradementor)", Accept: "application/rss+xml, application/xml, text/xml, */*" },
      signal: AbortSignal.timeout(7_000),
      cache: "no-store",
    });
    if (!response.ok) return [];
    return parseRss(await response.text(), source, google);
  } catch {
    return [];
  }
}

function googleNewsUrl(query: string) {
  const q = encodeURIComponent(query);
  return `https://news.google.com/rss/search?q=${q}&hl=en-US&gl=US&ceid=US:en`;
}

function rangeDays(raw: string) {
  if (raw === "1d") return 1;
  if (raw === "7d") return 7;
  if (raw === "90d") return 90;
  return 30;
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const days = rangeDays(url.searchParams.get("range") || "30d");
  const limit = Math.max(20, Math.min(180, Number(url.searchParams.get("limit") || 120) || 120));
  const rawSymbols = (url.searchParams.get("symbols") || "BTC,ETH,SOL,BNB,HYPE,XRP,DOGE,ADA,AVAX,LINK").split(",");
  const universe = Array.from(new Set(rawSymbols.map(stripPair).filter(Boolean))).slice(0, 60);
  const when = `when:${days}d`;
  const chunks: string[][] = [];
  for (let i = 0; i < universe.length; i += 10) chunks.push(universe.slice(i, i + 10));

  const requests: Array<Promise<ReturnType<typeof parseRss>>> = [
    fetchFeed("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk"),
    fetchFeed("https://decrypt.co/feed", "Decrypt"),
    fetchFeed("https://cointelegraph.com/rss", "Cointelegraph"),
    fetchFeed(googleNewsUrl(`cryptocurrency OR bitcoin OR ethereum ${when}`), "Google News", true),
    fetchFeed(googleNewsUrl(`("Federal Reserve" OR SEC OR inflation OR "interest rates") (crypto OR bitcoin) ${when}`), "Google News", true),
    ...chunks.map((chunk) => fetchFeed(googleNewsUrl(`(${chunk.map((symbol) => `"${symbol}" crypto`).join(" OR ")}) ${when}`), "Google News", true)),
  ];

  const settled = await Promise.all(requests);
  const cutoff = Date.now() - days * 86_400_000;
  const dedupe = new Map<string, NewsArticle>();
  for (const item of settled.flat()) {
    const published = Date.parse(item.publishedAt);
    if (Number.isFinite(published) && published < cutoff) continue;
    const text = `${item.title} ${item.summary}`;
    const coins = detectCoins(text, universe);
    const classification = classify(text);
    if (!coins.length && !classification.categories.includes("Macro") && !classification.categories.includes("Regulatie") && !classification.categories.includes("Security")) continue;
    const normalized = normalizeTitle(item.title);
    if (!normalized) continue;
    const key = normalized.replace(/\b(the|a|an|to|of|and|for|in|on|with|as|at|by)\b/g, " ").replace(/\s+/g, " ").trim();
    if (dedupe.has(key)) continue;
    const article: NewsArticle = {
      id: `news_${hash(`${item.sourceUrl}|${item.title}`)}`,
      externalId: item.externalId,
      source: item.source,
      sourceUrl: item.sourceUrl,
      title: item.title,
      summary: item.summary || "Open het bronartikel voor de volledige inhoud.",
      imageUrl: item.imageUrl,
      publishedAt: item.publishedAt,
      fetchedAt: new Date().toISOString(),
      coins,
      categories: classification.categories,
      importance: classification.importance,
      sentiment: classification.sentiment,
      sentimentScore: classification.sentimentScore,
      confidence: classification.confidence,
    };
    dedupe.set(key, article);
  }

  const items = Array.from(dedupe.values()).sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt)).slice(0, limit);
  return Response.json({
    ok: true,
    generatedAt: new Date().toISOString(),
    rangeDays: days,
    universe,
    count: items.length,
    items,
    note: "Nieuws is beslissingsondersteuning en voert nooit automatisch trades uit.",
  }, { headers: { "Cache-Control": "public, max-age=120, stale-while-revalidate=300" } });
}
