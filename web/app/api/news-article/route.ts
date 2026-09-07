type DigestPayload = {
  title: string;
  source: string;
  sourceUrl: string;
  summary: string;
};

const entityMap: Record<string,string> = { amp:"&", quot:'"', apos:"'", lt:"<", gt:">", nbsp:" " };

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
  return clean(decodeHtml(value.replace(/<script\b[\s\S]*?<\/script>/gi, " ").replace(/<style\b[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " ")));
}

function safeUrl(value: string) {
  try {
    const url = new URL(value);
    if (!/^https?:$/.test(url.protocol)) return null;
    return url;
  } catch { return null; }
}

function extractArticleText(html: string) {
  const jsonBodies = Array.from(html.matchAll(/"articleBody"\s*:\s*"((?:\\.|[^"\\])*)"/gi)).map((match) => {
    try { return clean(JSON.parse(`"${match[1]}"`)); } catch { return clean(match[1]); }
  }).filter((value) => value.length > 180);
  if (jsonBodies.length) return jsonBodies.sort((a,b) => b.length - a.length)[0];

  const scope = html.match(/<article\b[\s\S]*?<\/article>/i)?.[0] || html.match(/<main\b[\s\S]*?<\/main>/i)?.[0] || html;
  const paragraphs = Array.from(scope.matchAll(/<p\b[^>]*>([\s\S]*?)<\/p>/gi))
    .map((match) => stripHtml(match[1]))
    .filter((value) => value.length >= 45 && value.length <= 900)
    .filter((value) => !/cookie|privacy policy|sign up|newsletter|advertis|subscribe/i.test(value));
  return clean(paragraphs.slice(0, 28).join(" "));
}

function splitSentences(text: string) {
  return clean(text).split(/(?<=[.!?])\s+(?=[A-Z0-9€$])/).map(clean).filter((value) => value.length >= 38 && value.length <= 420);
}

function keywords(title: string) {
  const stop = new Set(["the","and","for","with","from","that","this","naar","voor","van","het","een","met","zijn","haar","als","bij","over","onder"]);
  return new Set(clean(title).toLowerCase().replace(/[^a-z0-9áéëïöü-]+/gi," ").split(" ").filter((word) => word.length > 3 && !stop.has(word)));
}

function selectKeySentences(text: string, title: string) {
  const words = keywords(title);
  return splitSentences(text).map((sentence, index) => {
    const lower = sentence.toLowerCase();
    let score = Math.max(0, 9 - index) * .35;
    for (const word of words) if (lower.includes(word)) score += .8;
    if (/\b\d+(?:[.,]\d+)?%|[$€£]\s?\d|\b\d{2,}\b/.test(sentence)) score += 1.3;
    if (/announc|report|said|says|according|launch|approve|reject|hack|exploit|inflow|outflow|price|market|network|fund|sec|fed|etf/i.test(sentence)) score += .7;
    return { sentence, index, score };
  }).sort((a,b) => b.score - a.score).slice(0, 7).sort((a,b) => a.index - b.index).map((row) => row.sentence);
}

async function translateOne(text: string) {
  const source = clean(text).slice(0, 470);
  if (!source) return "";
  try {
    const url = new URL("https://api.mymemory.translated.net/get");
    url.searchParams.set("q", source);
    url.searchParams.set("langpair", "en|nl");
    const response = await fetch(url.toString(), { headers: { Accept:"application/json", "User-Agent":"CryptoBot2026-News-Digest/1.0" }, signal: AbortSignal.timeout(5500), cache:"no-store" });
    if (response.ok) {
      const payload = await response.json() as { responseData?: { translatedText?: string } };
      const value = clean(decodeHtml(String(payload.responseData?.translatedText || "")));
      if (value && value.toLowerCase() !== source.toLowerCase()) return value;
    }
  } catch {}
  try {
    const url = new URL("https://translate.googleapis.com/translate_a/single");
    url.searchParams.set("client","gtx"); url.searchParams.set("sl","en"); url.searchParams.set("tl","nl"); url.searchParams.set("dt","t"); url.searchParams.set("q",source);
    const response = await fetch(url.toString(), { headers:{ Accept:"application/json" }, signal: AbortSignal.timeout(5000), cache:"no-store" });
    if (response.ok) {
      const payload = await response.json() as unknown;
      if (Array.isArray(payload) && Array.isArray(payload[0])) return clean((payload[0] as unknown[]).map((segment) => Array.isArray(segment) ? String(segment[0] || "") : "").join(""));
    }
  } catch {}
  return source;
}

function simplifyDutch(value: string) {
  return clean(value)
    .replace(/te midden van/gi, "terwijl")
    .replace(/met betrekking tot/gi, "over")
    .replace(/in het licht van/gi, "door")
    .replace(/is van mening dat/gi, "denkt dat")
    .replace(/heeft aangekondigd dat/gi, "meldt dat")
    .replace(/open interest/gi, "openstaande posities")
    .replace(/exchange-traded fund/gi, "ETF")
    .replace(/cryptocurrency/gi, "crypto")
    .replace(/volatiliteit/gi, "sterke koersschommelingen");
}

function capWords(parts: string[], maxWords = 175) {
  const output: string[] = [];
  let count = 0;
  for (const part of parts) {
    const words = clean(part).split(/\s+/);
    if (count + words.length > maxWords) break;
    output.push(clean(part)); count += words.length;
  }
  return output;
}

export async function GET(request: Request) {
  const incoming = new URL(request.url);
  const sourceUrl = incoming.searchParams.get("url") || "";
  const title = clean(incoming.searchParams.get("title"));
  const source = clean(incoming.searchParams.get("source"));
  const fallbackSummary = clean(incoming.searchParams.get("summary"));
  const target = safeUrl(sourceUrl);

  let extracted = "";
  let finalUrl = sourceUrl;
  if (target) {
    try {
      const response = await fetch(target.toString(), {
        redirect: "follow",
        headers: { "User-Agent":"Mozilla/5.0 (compatible; CryptoBot2026/1.0; +news digest)", Accept:"text/html,application/xhtml+xml" },
        signal: AbortSignal.timeout(8500),
        cache: "no-store",
      });
      finalUrl = response.url || sourceUrl;
      if (response.ok && /text\/html|xhtml/i.test(response.headers.get("content-type") || "")) extracted = extractArticleText(await response.text());
    } catch {}
  }

  const basis = extracted.length >= 180 ? extracted : fallbackSummary;
  const selected = selectKeySentences(basis, title);
  const translated = await Promise.all(selected.slice(0, 6).map(translateOne));
  const facts = capWords(translated.map(simplifyDutch).filter(Boolean), 170);
  const paragraphs = facts.length ? [facts.slice(0,2).join(" "), facts.slice(2,4).join(" "), facts.slice(4,6).join(" ")].filter(Boolean) : [fallbackSummary || "Voor dit bericht kon geen extra brontekst worden opgehaald. De nieuwsimpact en tijdsvensteranalyse blijven wel beschikbaar in de app."];

  return Response.json({
    ok: true,
    source,
    sourceUrl: finalUrl,
    title,
    article: {
      label: "Duidelijk uitgelegd",
      intro: paragraphs[0] || fallbackSummary,
      paragraphs: paragraphs.slice(1),
      keyPoints: facts.slice(0, 4),
      basedOnFullSource: extracted.length >= 180,
      note: "Samengevat en vereenvoudigd door Crypto Bot 2026 op basis van de oorspronkelijke nieuwsbron.",
    },
  }, { headers: { "Cache-Control":"private, max-age=300" } });
}
