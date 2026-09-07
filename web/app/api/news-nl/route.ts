type NewsItem = {
  id: string;
  title: string;
  summary: string;
  [key: string]: unknown;
};

type NewsPayload = {
  items?: NewsItem[];
  [key: string]: unknown;
};

const TARGET_LANGUAGE = "nl";
const translationCache = new Map<string, string>();

function clean(value: unknown) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function decodeHtml(value: string) {
  return value
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">");
}

function looksDutch(value: string) {
  const text = ` ${value.toLowerCase()} `;
  const dutchWords = [" de ", " het ", " een ", " van ", " voor ", " met ", " naar ", " op ", " als ", " bij ", " en ", " niet ", " blijft ", " stijgt ", " daalt ", " nieuws ", " markt "];
  const englishWords = [" the ", " and ", " with ", " says ", " after ", " amid ", " from ", " into ", " on ", " for ", " is ", " are ", " could ", " market "];
  const nl = dutchWords.reduce((score, word) => score + (text.includes(word) ? 1 : 0), 0);
  const en = englishWords.reduce((score, word) => score + (text.includes(word) ? 1 : 0), 0);
  return nl >= 2 && nl > en;
}

function usableTranslation(source: string, translated: string) {
  const cleanSource = clean(source).toLowerCase();
  const cleanTranslated = clean(translated);
  if (!cleanTranslated) return false;
  if (cleanTranslated.toLowerCase() === cleanSource) return false;
  return /[a-záéëïöüàèìòùç]/i.test(cleanTranslated);
}

async function metadataAccessToken() {
  try {
    const response = await fetch("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token", {
      headers: { "Metadata-Flavor": "Google" },
      signal: AbortSignal.timeout(900),
      cache: "no-store",
    });
    if (!response.ok) return "";
    const payload = await response.json() as { access_token?: string };
    return payload.access_token || "";
  } catch {
    return "";
  }
}

async function cloudTranslate(texts: string[]) {
  if (!texts.length) return [] as string[];
  try {
    const token = await metadataAccessToken();
    if (!token) return [];
    const response = await fetch("https://translation.googleapis.com/language/translate/v2", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ q: texts, source: "en", target: TARGET_LANGUAGE, format: "text" }),
      signal: AbortSignal.timeout(8_000),
      cache: "no-store",
    });
    if (!response.ok) return [];
    const payload = await response.json() as { data?: { translations?: Array<{ translatedText?: string }> } };
    const translated = payload.data?.translations || [];
    if (translated.length !== texts.length) return [];
    return translated.map((row) => clean(decodeHtml(String(row.translatedText || ""))));
  } catch {
    return [];
  }
}

async function myMemoryTranslate(text: string) {
  try {
    const source = clean(text).slice(0, 460);
    if (!source) return "";
    const url = new URL("https://api.mymemory.translated.net/get");
    url.searchParams.set("q", source);
    url.searchParams.set("langpair", "en|nl");
    const response = await fetch(url.toString(), {
      headers: { Accept: "application/json", "User-Agent": "CryptoBot2026-News-NL/1.1" },
      signal: AbortSignal.timeout(6_000),
      cache: "no-store",
    });
    if (!response.ok) return "";
    const payload = await response.json() as { responseStatus?: number | string; responseData?: { translatedText?: string } };
    if (Number(payload.responseStatus || 200) >= 400) return "";
    return clean(decodeHtml(String(payload.responseData?.translatedText || "")));
  } catch {
    return "";
  }
}

async function publicGoogleTranslate(text: string) {
  try {
    const source = clean(text).slice(0, 900);
    if (!source) return "";
    const url = new URL("https://translate.googleapis.com/translate_a/single");
    url.searchParams.set("client", "gtx");
    url.searchParams.set("sl", "en");
    url.searchParams.set("tl", "nl");
    url.searchParams.set("dt", "t");
    url.searchParams.set("q", source);
    const response = await fetch(url.toString(), {
      headers: { Accept: "application/json", "User-Agent": "CryptoBot2026-News-NL/1.1" },
      signal: AbortSignal.timeout(5_000),
      cache: "no-store",
    });
    if (!response.ok) return "";
    const payload = await response.json() as unknown;
    if (!Array.isArray(payload) || !Array.isArray(payload[0])) return "";
    return clean((payload[0] as unknown[]).map((segment) => Array.isArray(segment) ? String(segment[0] || "") : "").join(""));
  } catch {
    return "";
  }
}

async function translateOne(text: string) {
  const source = clean(text);
  if (!source || looksDutch(source)) return source;
  const cached = translationCache.get(source);
  if (cached) return cached;

  const myMemory = await myMemoryTranslate(source);
  if (usableTranslation(source, myMemory)) {
    translationCache.set(source, myMemory);
    return myMemory;
  }

  const google = await publicGoogleTranslate(source);
  if (usableTranslation(source, google)) {
    translationCache.set(source, google);
    return google;
  }

  return source;
}

async function translateTexts(texts: string[]) {
  const sources = texts.map(clean);
  const result = [...sources];
  const unresolved: Array<{ index: number; source: string }> = [];

  sources.forEach((source, index) => {
    if (!source || looksDutch(source)) return;
    const cached = translationCache.get(source);
    if (cached) result[index] = cached;
    else unresolved.push({ index, source });
  });
  if (!unresolved.length) return result;

  for (let start = 0; start < unresolved.length; start += 60) {
    const batch = unresolved.slice(start, start + 60);
    const cloud = await cloudTranslate(batch.map((row) => row.source));
    if (cloud.length === batch.length) {
      batch.forEach((row, localIndex) => {
        const translated = cloud[localIndex];
        if (usableTranslation(row.source, translated)) {
          translationCache.set(row.source, translated);
          result[row.index] = translated;
        }
      });
    }
  }

  const remaining = unresolved.filter((row) => result[row.index] === row.source);
  for (let start = 0; start < remaining.length; start += 6) {
    const batch = remaining.slice(start, start + 6);
    const translations = await Promise.all(batch.map((row) => translateOne(row.source)));
    batch.forEach((row, localIndex) => { result[row.index] = translations[localIndex] || row.source; });
  }

  if (translationCache.size > 1500) {
    const keys = Array.from(translationCache.keys()).slice(0, translationCache.size - 1100);
    keys.forEach((key) => translationCache.delete(key));
  }
  return result;
}

export async function GET(request: Request) {
  const incoming = new URL(request.url);
  const upstream = new URL(request.url);
  upstream.pathname = "/api/news";

  const response = await fetch(upstream.toString(), {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(14_000),
    cache: "no-store",
  });
  if (!response.ok) return new Response(await response.text(), { status: response.status, headers: { "Content-Type": response.headers.get("Content-Type") || "application/json" } });

  const payload = await response.json() as NewsPayload;
  const items = Array.isArray(payload.items) ? payload.items : [];
  const sourceTexts = items.flatMap((item) => [clean(item.title), clean(item.summary).slice(0, 460)]);
  const translated = await translateTexts(sourceTexts);
  let translatedCount = 0;

  const translatedItems = items.map((item, index) => {
    const titleSource = clean(item.title);
    const summarySource = clean(item.summary);
    const title = translated[index * 2] || titleSource;
    const summary = translated[index * 2 + 1] || summarySource;
    if (usableTranslation(titleSource, title) || looksDutch(titleSource)) translatedCount += 1;
    return { ...item, title, summary, language: TARGET_LANGUAGE };
  });

  return Response.json({
    ...payload,
    items: translatedItems,
    language: TARGET_LANGUAGE,
    translated: translatedCount === translatedItems.length,
    translatedCount,
    requestedPath: incoming.pathname,
  }, { headers: { "Cache-Control": "no-store" } });
}
