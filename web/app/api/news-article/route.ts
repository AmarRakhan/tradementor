import { lookup } from "node:dns/promises";
import { isIP } from "node:net";

const entityMap: Record<string,string> = { amp:"&", quot:'"', apos:"'", lt:"<", gt:">", nbsp:" " };
const digestCache = new Map<string, { expiresAt: number; value: Record<string, unknown> }>();

function clean(value: unknown) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function decodeHtml(value: string) {
  return value
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&([a-z]+);/gi, (all, name) => entityMap[String(name).toLowerCase()] ?? all);
}

function stripHtml(value: string) {
  return clean(decodeHtml(value
    .replace(/<script\b[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[\s\S]*?<\/style>/gi, " ")
    .replace(/<noscript\b[\s\S]*?<\/noscript>/gi, " ")
    .replace(/<[^>]+>/g, " ")));
}

function privateIp(address: string) {
  const host = address.toLowerCase().replace(/^\[|\]$/g, "");
  if (isIP(host) === 4) {
    const octets = host.split(".").map(Number);
    if (octets[0] === 0 || octets[0] === 10 || octets[0] === 127) return true;
    if (octets[0] === 169 && octets[1] === 254) return true;
    if (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) return true;
    if (octets[0] === 192 && octets[1] === 168) return true;
    if (octets[0] >= 224) return true;
  }
  if (isIP(host) === 6) {
    if (host === "::1" || host === "::") return true;
    if (host.startsWith("fe80:") || host.startsWith("fc") || host.startsWith("fd")) return true;
  }
  return false;
}

function privateHost(hostname: string) {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (host === "localhost" || host === "metadata.google.internal" || host.endsWith(".localhost") || host.endsWith(".local") || host.endsWith(".internal")) return true;
  return isIP(host) !== 0 && privateIp(host);
}

function safeUrl(value: string, base?: URL) {
  try {
    const url = base ? new URL(value, base) : new URL(value);
    if (!/^https?:$/.test(url.protocol) || privateHost(url.hostname)) return null;
    return url;
  } catch { return null; }
}

async function validatePublicUrl(url: URL) {
  if (privateHost(url.hostname)) return false;
  if (isIP(url.hostname)) return !privateIp(url.hostname);
  try {
    const rows = await lookup(url.hostname, { all: true, verbatim: true });
    return rows.length > 0 && rows.every((row) => !privateIp(row.address));
  } catch {
    return false;
  }
}

async function fetchPublicHtml(initial: URL) {
  let current = initial;
  for (let hop = 0; hop < 5; hop += 1) {
    if (!(await validatePublicUrl(current))) return null;
    const response = await fetch(current.toString(), {
      redirect: "manual",
      headers: {
        "User-Agent":"Mozilla/5.0 (compatible; CryptoBot2026/1.2; +in-app-news-digest)",
        Accept:"text/html,application/xhtml+xml",
      },
      signal: AbortSignal.timeout(9_000),
      cache: "no-store",
    });
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get("location") || "";
      const next = safeUrl(location, current);
      if (!next || !(await validatePublicUrl(next))) return null;
      current = next;
      continue;
    }
    if (!response.ok || !/text\/html|xhtml/i.test(response.headers.get("content-type") || "")) return null;
    const html = await response.text();
    return { html: html.slice(0, 2_500_000), url: response.url || current.toString() };
  }
  return null;
}

function metaContent(html: string, key: string) {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const patterns = [
    new RegExp(`<meta\\b[^>]*(?:property|name)=["']${escaped}["'][^>]*content=["']([^"']+)["'][^>]*>`, "i"),
    new RegExp(`<meta\\b[^>]*content=["']([^"']+)["'][^>]*(?:property|name)=["']${escaped}["'][^>]*>`, "i"),
  ];
  for (const pattern of patterns) {
    const match = html.match(pattern);
    if (match?.[1]) return decodeHtml(match[1]);
  }
  return "";
}

function jsonLdString(html: string, key: string) {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = html.match(new RegExp(`"${escaped}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`, "i"));
  if (!match?.[1]) return "";
  try { return clean(JSON.parse(`"${match[1]}"`)); } catch { return clean(match[1]); }
}

function extractImage(html: string, pageUrl: URL, fallbackImage: string) {
  const candidates = [
    metaContent(html, "og:image"),
    metaContent(html, "twitter:image"),
    metaContent(html, "twitter:image:src"),
    jsonLdString(html, "image"),
    fallbackImage,
  ].filter(Boolean);
  for (const candidate of candidates) {
    const url = safeUrl(candidate, pageUrl);
    if (url) return url.toString();
  }
  return "";
}

function extractAuthor(html: string) {
  const direct = metaContent(html, "author") || metaContent(html, "article:author");
  if (direct) return stripHtml(direct).slice(0, 120);
  const match = html.match(/"author"\s*:\s*\{[^{}]*"name"\s*:\s*"((?:\\.|[^"\\])*)"/i);
  if (!match?.[1]) return "";
  try { return clean(JSON.parse(`"${match[1]}"`)).slice(0,120); } catch { return clean(match[1]).slice(0,120); }
}

function extractArticleText(html: string) {
  const jsonBodies = Array.from(html.matchAll(/"articleBody"\s*:\s*"((?:\\.|[^"\\])*)"/gi)).map((match) => {
    try { return clean(JSON.parse(`"${match[1]}"`)); } catch { return clean(match[1]); }
  }).filter((value) => value.length > 180);
  if (jsonBodies.length) return jsonBodies.sort((a,b) => b.length - a.length)[0].slice(0, 38_000);

  const scope = html.match(/<article\b[\s\S]*?<\/article>/i)?.[0] || html.match(/<main\b[\s\S]*?<\/main>/i)?.[0] || html;
  const seen = new Set<string>();
  const paragraphs = Array.from(scope.matchAll(/<p\b[^>]*>([\s\S]*?)<\/p>/gi))
    .map((match) => stripHtml(match[1]))
    .filter((value) => value.length >= 45 && value.length <= 1_300)
    .filter((value) => !/cookie|privacy policy|sign up|newsletter|advertis|subscribe|all rights reserved|terms of use/i.test(value))
    .filter((value) => {
      const key = value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  return clean(paragraphs.slice(0, 42).join(" ")).slice(0, 38_000);
}

function splitSentences(text: string) {
  const raw = clean(text).split(/(?<=[.!?])\s+(?=[A-Z0-9€$])/).map(clean);
  const seen = new Set<string>();
  return raw.filter((value) => value.length >= 35 && value.length <= 520).filter((value) => {
    const key = value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function keywords(title: string) {
  const stop = new Set(["the","and","for","with","from","that","this","naar","voor","van","het","een","met","zijn","haar","als","bij","over","onder","says","said"]);
  return new Set(clean(title).toLowerCase().replace(/[^a-z0-9áéëïöü-]+/gi," ").split(" ").filter((word) => word.length > 3 && !stop.has(word)));
}

function selectKeySentences(text: string, title: string, maxSentences = 15) {
  const words = keywords(title);
  const rows = splitSentences(text).map((sentence, index) => {
    const lower = sentence.toLowerCase();
    let score = Math.max(0, 13 - index) * .25;
    for (const word of words) if (lower.includes(word)) score += .75;
    if (/\b\d+(?:[.,]\d+)?%|[$€£]\s?\d|\b\d{2,}\b/.test(sentence)) score += 1.1;
    if (/announc|report|according|launch|approve|reject|hack|exploit|inflow|outflow|price|market|network|fund|sec|fed|etf|because|after|before|investor|volume/i.test(sentence)) score += .55;
    return { sentence, index, score };
  });
  const selected = rows.sort((a,b) => b.score - a.score).slice(0, maxSentences).sort((a,b) => a.index - b.index);
  return selected.map((row) => row.sentence);
}

function looksDutch(value: string) {
  const text = ` ${value.toLowerCase()} `;
  const nl = [" de "," het "," een "," van "," voor "," met "," naar "," omdat "," wordt "," zijn "," blijft "].reduce((n,w) => n + (text.includes(w) ? 1 : 0), 0);
  const en = [" the "," and "," with "," from "," because "," after "," before "," says "," said "," are "," is "].reduce((n,w) => n + (text.includes(w) ? 1 : 0), 0);
  return nl >= 2 && nl >= en;
}

async function metadataAccessToken() {
  try {
    const response = await fetch("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token", {
      headers: { "Metadata-Flavor": "Google" }, signal: AbortSignal.timeout(900), cache: "no-store",
    });
    if (!response.ok) return "";
    const payload = await response.json() as { access_token?: string };
    return payload.access_token || "";
  } catch { return ""; }
}

async function cloudTranslate(texts: string[]) {
  if (!texts.length) return [] as string[];
  try {
    const token = await metadataAccessToken();
    if (!token) return [];
    const response = await fetch("https://translation.googleapis.com/language/translate/v2", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ q: texts, source:"en", target:"nl", format:"text" }),
      signal: AbortSignal.timeout(8_000), cache: "no-store",
    });
    if (!response.ok) return [];
    const payload = await response.json() as { data?: { translations?: Array<{ translatedText?: string }> } };
    const translated = payload.data?.translations || [];
    if (translated.length !== texts.length) return [];
    return translated.map((row) => clean(decodeHtml(String(row.translatedText || ""))));
  } catch { return []; }
}

async function translateOne(text: string) {
  const source = clean(text).slice(0, 760);
  if (!source || looksDutch(source)) return source;
  try {
    const url = new URL("https://api.mymemory.translated.net/get");
    url.searchParams.set("q", source.slice(0, 470));
    url.searchParams.set("langpair", "en|nl");
    const response = await fetch(url.toString(), { headers: { Accept:"application/json", "User-Agent":"CryptoBot2026-News-Digest/1.2" }, signal: AbortSignal.timeout(5_500), cache:"no-store" });
    if (response.ok) {
      const payload = await response.json() as { responseData?: { translatedText?: string } };
      const value = clean(decodeHtml(String(payload.responseData?.translatedText || "")));
      if (value && value.toLowerCase() !== source.toLowerCase()) return value;
    }
  } catch {}
  try {
    const url = new URL("https://translate.googleapis.com/translate_a/single");
    url.searchParams.set("client","gtx"); url.searchParams.set("sl","en"); url.searchParams.set("tl","nl"); url.searchParams.set("dt","t"); url.searchParams.set("q",source.slice(0,760));
    const response = await fetch(url.toString(), { headers:{ Accept:"application/json" }, signal: AbortSignal.timeout(5_000), cache:"no-store" });
    if (response.ok) {
      const payload = await response.json() as unknown;
      if (Array.isArray(payload) && Array.isArray(payload[0])) return clean((payload[0] as unknown[]).map((segment) => Array.isArray(segment) ? String(segment[0] || "") : "").join(""));
    }
  } catch {}
  return source;
}

async function translateSentences(sentences: string[]) {
  const result = [...sentences];
  const unresolved: Array<{ index:number; source:string }> = [];
  sentences.forEach((sentence,index) => {
    if (!looksDutch(sentence)) unresolved.push({ index, source: sentence });
  });
  if (!unresolved.length) return result;
  for (let start = 0; start < unresolved.length; start += 40) {
    const batch = unresolved.slice(start, start + 40);
    const cloud = await cloudTranslate(batch.map((row) => row.source));
    if (cloud.length === batch.length) {
      batch.forEach((row,localIndex) => { if (cloud[localIndex]) result[row.index] = cloud[localIndex]; });
      continue;
    }
    for (let inner = 0; inner < batch.length; inner += 5) {
      const small = batch.slice(inner, inner + 5);
      const translated = await Promise.all(small.map((row) => translateOne(row.source)));
      small.forEach((row,localIndex) => { result[row.index] = translated[localIndex] || row.source; });
    }
  }
  return result;
}

function simplifyDutch(value: string) {
  return clean(value)
    .replace(/te midden van/gi, "terwijl")
    .replace(/met betrekking tot/gi, "over")
    .replace(/in het licht van/gi, "door")
    .replace(/is van mening dat/gi, "denkt dat")
    .replace(/heeft aangekondigd dat/gi, "meldt dat")
    .replace(/open interest/gi, "het totaal aan nog openstaande futuresposities")
    .replace(/exchange-traded fund/gi, "ETF")
    .replace(/cryptocurrency/gi, "crypto")
    .replace(/volatiliteit/gi, "sterke koersschommelingen")
    .replace(/\s+([,.;:!?])/g, "$1");
}

function capWords(parts: string[], maxWords = 520) {
  const output: string[] = [];
  let count = 0;
  for (const part of parts) {
    const words = clean(part).split(/\s+/).filter(Boolean);
    if (!words.length) continue;
    if (count + words.length > maxWords) break;
    output.push(clean(part));
    count += words.length;
  }
  return output;
}

function paragraphs(sentences: string[], perParagraph = 3) {
  const result: string[] = [];
  for (let i = 0; i < sentences.length; i += perParagraph) {
    const text = clean(sentences.slice(i, i + perParagraph).join(" "));
    if (text) result.push(text);
  }
  return result;
}

function point(value: string) {
  const text = clean(value);
  if (text.length <= 190) return text;
  const cut = text.slice(0, 187).replace(/\s+\S*$/, "");
  return `${cut}…`;
}

function watchFor(category: string, source: string, coin: string) {
  const items = new Set<string>();
  if (/security|beveilig|hack|exploit/i.test(category)) {
    items.add("Let op bevestiging van de omvang, getroffen fondsen en eventuele herstelmaatregelen.");
  }
  if (/regulat|etf/i.test(category)) {
    items.add("Let op officiële bevestiging en eventuele vervolgstappen van toezichthouders of fondsbeheerders.");
  }
  if (/macro/i.test(category)) {
    items.add("Let op nieuwe macro-economische cijfers en de reactie van rente, dollar en brede risicomarkten.");
  }
  if (coin) items.add(`Kijk of de koers en het handelsvolume van ${coin} de eerste reactie blijven bevestigen.`);
  items.add(`Controleer of ${source || "de nieuwsbron"} of andere betrouwbare bronnen later aanvullende feiten publiceren.`);
  items.add("Vergelijk de beweging met de bredere cryptomarkt om te zien of de reactie echt nieuws-specifiek is.");
  return Array.from(items).slice(0, 4);
}

function cachePut(key: string, value: Record<string, unknown>) {
  digestCache.set(key, { expiresAt: Date.now() + 6 * 60 * 60_000, value });
  if (digestCache.size > 250) {
    const first = digestCache.keys().next().value as string | undefined;
    if (first) digestCache.delete(first);
  }
}

export async function GET(request: Request) {
  const incoming = new URL(request.url);
  const sourceUrl = incoming.searchParams.get("url") || "";
  const title = clean(incoming.searchParams.get("title"));
  const source = clean(incoming.searchParams.get("source"));
  const fallbackSummary = clean(incoming.searchParams.get("summary"));
  const fallbackImage = clean(incoming.searchParams.get("image"));
  const coin = clean(incoming.searchParams.get("coin")).toUpperCase();
  const category = clean(incoming.searchParams.get("category"));
  const target = safeUrl(sourceUrl);
  const cacheKey = `${sourceUrl}|${title}`;
  const cached = digestCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) return Response.json(cached.value, { headers: { "Cache-Control":"private, max-age=900" } });

  let extracted = "";
  let finalUrl = sourceUrl;
  let imageUrl = fallbackImage;
  let author = "";
  let basedOnFullSource = false;
  if (target) {
    try {
      const result = await fetchPublicHtml(target);
      if (result) {
        finalUrl = result.url;
        const finalPage = safeUrl(result.url) || target;
        extracted = extractArticleText(result.html);
        imageUrl = extractImage(result.html, finalPage, fallbackImage);
        author = extractAuthor(result.html);
        basedOnFullSource = extracted.length >= 220;
      }
    } catch {}
  }

  const basis = basedOnFullSource ? extracted : fallbackSummary;
  const selected = selectKeySentences(basis, title, basedOnFullSource ? 15 : 7);
  const translated = await translateSentences(selected);
  const facts = capWords(translated.map(simplifyDutch).filter(Boolean), 520);

  const introParts = facts.slice(0, Math.min(2, facts.length));
  const remainder = facts.slice(introParts.length);
  const happened = remainder.slice(0, Math.min(5, remainder.length));
  const importance = remainder.slice(happened.length, happened.length + 4);
  const context = remainder.slice(happened.length + importance.length);
  const intro = clean(introParts.join(" ")) || fallbackSummary || "De bron geeft op dit moment weinig aanvullende tekst vrij. Hieronder staat wat wel betrouwbaar uit de beschikbare broninformatie kan worden gehaald.";

  const sections: Array<{ heading:string; paragraphs:string[] }> = [];
  const happenedParagraphs = paragraphs(happened, 2);
  if (happenedParagraphs.length) sections.push({ heading:"Wat is er gebeurd?", paragraphs:happenedParagraphs });
  const importanceParagraphs = paragraphs(importance, 2);
  if (importanceParagraphs.length) sections.push({ heading:"Waarom is dit belangrijk?", paragraphs:importanceParagraphs });
  const contextParagraphs = paragraphs(context, 2);
  if (contextParagraphs.length) sections.push({ heading:"Wat zegt de bron verder?", paragraphs:contextParagraphs });

  const keyPoints = facts.filter((_,index) => index === 0 || index === 2 || index === 4 || index === 7 || index === 10).slice(0,5).map(point);
  if (!keyPoints.length && fallbackSummary) keyPoints.push(point(fallbackSummary));
  const conclusionSeed = facts.length > 1 ? facts.at(-1)! : intro;
  const conclusion = clean(`Kortom: ${point(conclusionSeed)}`);
  const articleTextForCount = [intro, ...sections.flatMap((section) => section.paragraphs), ...keyPoints, ...watchFor(category,source,coin), conclusion].join(" ");
  const wordCount = articleTextForCount.split(/\s+/).filter(Boolean).length;

  const value: Record<string, unknown> = {
    ok: true,
    source,
    sourceUrl: finalUrl,
    title,
    article: {
      label: "Duidelijk uitgelegd",
      intro,
      paragraphs: sections.flatMap((section) => section.paragraphs),
      sections,
      keyPoints,
      watchFor: watchFor(category, source, coin),
      conclusion,
      imageUrl,
      imageFromSource: Boolean(imageUrl && imageUrl !== fallbackImage),
      author,
      wordCount,
      basedOnFullSource,
      note: basedOnFullSource
        ? "Samengevat en in eigen woorden vereenvoudigd door Crypto Bot 2026 op basis van de oorspronkelijke openbare nieuwsbron. De brontekst wordt niet integraal overgenomen."
        : "Samengevat en vereenvoudigd door Crypto Bot 2026 op basis van de beschikbare broninformatie. De bron gaf niet alle artikeltekst vrij.",
    },
  };
  cachePut(cacheKey, value);
  return Response.json(value, { headers: { "Cache-Control":"private, max-age=900" } });
}
