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
const SEP = "\nZZZCB2026NEWSSEPZZZ\n";
const translationCache = new Map<string, string>();

function clean(value: unknown) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function looksDutch(value: string) {
  const text = ` ${value.toLowerCase()} `;
  const dutchWords = [" de ", " het ", " een ", " van ", " voor ", " met ", " naar ", " op ", " als ", " bij ", " en ", " niet ", " blijft ", " stijgt ", " daalt "];
  const englishWords = [" the ", " and ", " with ", " says ", " after ", " as ", " amid ", " from ", " into ", " on ", " for ", " is ", " are "];
  const nl = dutchWords.reduce((score, word) => score + (text.includes(word) ? 1 : 0), 0);
  const en = englishWords.reduce((score, word) => score + (text.includes(word) ? 1 : 0), 0);
  return nl >= 2 && nl > en;
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
      body: JSON.stringify({ q: texts, target: TARGET_LANGUAGE, format: "text" }),
      signal: AbortSignal.timeout(8_000),
      cache: "no-store",
    });
    if (!response.ok) return [];
    const payload = await response.json() as { data?: { translations?: Array<{ translatedText?: string }> } };
    const translated = payload.data?.translations || [];
    if (translated.length !== texts.length) return [];
    return translated.map((row) => clean(row.translatedText));
  } catch {
    return [];
  }
}

async function publicTranslate(text: string) {
  try {
    const response = await fetch("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=nl&dt=t", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": "CryptoBot2026-News-NL/1.0" },
      body: new URLSearchParams({ q: text }).toString(),
      signal: AbortSignal.timeout(6_000),
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

function makeBatches(texts: string[], maxChars = 2800) {
  const batches: Array<{ indices: number[]; joined: string }> = [];
  let indices: number[] = [];
  let parts: string[] = [];
  let size = 0;
  const flush = () => {
    if (!indices.length) return;
    batches.push({ indices, joined: parts.join(SEP) });
    indices = [];
    parts = [];
    size = 0;
  };
  texts.forEach((text, index) => {
    const extra = text.length + (parts.length ? SEP.length : 0);
    if (parts.length && size + extra > maxChars) flush();
    indices.push(index);
    parts.push(text);
    size += extra;
  });
  flush();
  return batches;
}

async function translateTexts(texts: string[]) {
  const result = [...texts];
  const missingIndices: number[] = [];
  const missingTexts: string[] = [];

  texts.forEach((text, index) => {
    const source = clean(text);
    if (!source || looksDutch(source)) {
      result[index] = source;
      return;
    }
    const cached = translationCache.get(source);
    if (cached) {
      result[index] = cached;
      return;
    }
    missingIndices.push(index);
    missingTexts.push(source);
  });

  if (!missingTexts.length) return result;

  for (let start = 0; start < missingTexts.length; start += 80) {
    const chunk = missingTexts.slice(start, start + 80);
    const cloud = await cloudTranslate(chunk);
    if (cloud.length === chunk.length) {
      cloud.forEach((translated, localIndex) => {
        const source = chunk[localIndex];
        const targetIndex = missingIndices[start + localIndex];
        const value = translated || source;
        translationCache.set(source, value);
        result[targetIndex] = value;
      });
      continue;
    }

    const batches = makeBatches(chunk);
    for (let i = 0; i < batches.length; i += 6) {
      const group = batches.slice(i, i + 6);
      const translatedGroup = await Promise.all(group.map((batch) => publicTranslate(batch.joined)));
      translatedGroup.forEach((translated, groupIndex) => {
        const batch = group[groupIndex];
        const split = translated ? translated.split("ZZZCB2026NEWSSEPZZZ").map(clean) : [];
        batch.indices.forEach((chunkIndex, splitIndex) => {
          const source = chunk[chunkIndex];
          const targetIndex = missingIndices[start + chunkIndex];
          const value = split.length === batch.indices.length && split[splitIndex] ? split[splitIndex] : source;
          translationCache.set(source, value);
          result[targetIndex] = value;
        });
      });
    }
  }

  if (translationCache.size > 1200) {
    const keys = Array.from(translationCache.keys()).slice(0, translationCache.size - 900);
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
  const sourceTexts = items.flatMap((item) => [clean(item.title), clean(item.summary).slice(0, 700)]);
  const translated = await translateTexts(sourceTexts);

  const translatedItems = items.map((item, index) => ({
    ...item,
    title: translated[index * 2] || clean(item.title),
    summary: translated[index * 2 + 1] || clean(item.summary),
    language: TARGET_LANGUAGE,
  }));

  return Response.json({
    ...payload,
    items: translatedItems,
    language: TARGET_LANGUAGE,
    translated: true,
    requestedPath: incoming.pathname,
  }, { headers: { "Cache-Control": "no-store" } });
}
