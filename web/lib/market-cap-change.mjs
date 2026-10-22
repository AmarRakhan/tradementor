// Build 607: totale crypto market cap en de 24-uurs verandering, zoals CoinMarketCap die
// linksboven op coinmarketcap.com toont ("Market cap $2.74T ▼2.98%").
// Alleen weergave; geen invloed op trading.

export const CMC_PUBLIC_GLOBAL_METRICS_URL = "https://pro-api.coinmarketcap.com/public-api/v1/global-metrics/quotes/latest?convert=USD";
export const CMC_WEBSITE_GLOBAL_METRICS_URL = "https://api.coinmarketcap.com/data-api/v3/global-metrics/quotes/latest";

function finite(value) {
  const number = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  return typeof number === "number" && Number.isFinite(number) ? number : null;
}

function record(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}

function changeFrom(current, yesterday) {
  return current !== null && yesterday !== null && yesterday > 0 ? ((current - yesterday) / yesterday) * 100 : null;
}

/**
 * Leest de 24u-verandering uit een CoinMarketCap global-metrics antwoord.
 * Ondersteunt de keyless public API (snake_case) en de website-API (camelCase).
 * Geeft null als het antwoord geen betrouwbaar getal bevat.
 */
export function parseMarketCapChange(payload) {
  const data = record(record(payload)?.data);
  if (!data) return null;

  // Keyless public API / Pro API: data.quote.USD
  const usd = record(record(data.quote)?.USD);
  if (usd) {
    const marketCap = finite(usd.total_market_cap);
    const yesterday = finite(usd.total_market_cap_yesterday);
    const change = finite(usd.total_market_cap_yesterday_percentage_change) ?? changeFrom(marketCap, yesterday);
    if (change !== null) return { changePercent: change, marketCapUsd: marketCap, updatedAt: typeof usd.last_updated === "string" ? usd.last_updated : null };
  }

  // Website-API: data.quotes[0]
  const quote = Array.isArray(data.quotes) ? record(data.quotes[0]) : null;
  if (quote) {
    const marketCap = finite(quote.totalMarketCap);
    const yesterday = finite(quote.totalMarketCapYesterday);
    const change = finite(quote.totalMarketCapYesterdayPercentageChange) ?? changeFrom(marketCap, yesterday);
    if (change !== null) return { changePercent: change, marketCapUsd: marketCap, updatedAt: typeof quote.lastUpdated === "string" ? quote.lastUpdated : null };
  }
  return null;
}

/** "+2,98%", "−2,98%" of "0,00%"; "—" als er geen getal is. */
export function formatMarketCapChange(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const rounded = Math.round(value * 100) / 100;
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "";
  return `${sign}${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(rounded))}%`;
}

/** Groen bij plus, rood bij min, neutraal bij 0,00% of onbekend. */
export function marketCapChangeTone(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "neutral";
  const rounded = Math.round(value * 100) / 100;
  return rounded > 0 ? "positive" : rounded < 0 ? "negative" : "neutral";
}

/** "$2.74T" zoals op CoinMarketCap. */
export function formatMarketCapUsd(value) {
  if (value === null || value === undefined || !Number.isFinite(value) || value <= 0) return "";
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  return `$${Math.round(value).toLocaleString("en-US")}`;
}
