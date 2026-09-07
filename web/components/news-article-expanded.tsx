"use client";

import { useEffect, useMemo, useState } from "react";
import styles from "./news-article-expanded.module.css";

type Timeframe = "1m" | "5m" | "15m" | "1u" | "4u" | "24u";

type NewsArticleLike = {
  id: string;
  source: string;
  sourceUrl: string;
  title: string;
  summary: string;
  imageUrl: string;
  publishedAt: string;
  coins: string[];
  sentiment: "bullish" | "bearish" | "neutral";
  importance: "high" | "normal";
};

type Digest = {
  sourceUrl: string;
  article: {
    label: string;
    intro: string;
    paragraphs?: string[];
    sections?: Array<{ heading: string; paragraphs: string[] }>;
    keyPoints: string[];
    watchFor?: string[];
    conclusion?: string;
    imageUrl?: string;
    imageFromSource?: boolean;
    author?: string;
    wordCount?: number;
    basedOnFullSource: boolean;
    note: string;
  };
};

type ImpactWindow = { available: boolean; changePercent: number | null; price: number | null; label: string };
type Impact = {
  ok: boolean;
  available: boolean;
  symbol?: string;
  market?: string;
  source?: string;
  reason?: string;
  publishedAt?: string;
  observationCappedAt24h?: boolean;
  publicationPrice?: number;
  currentPrice?: number;
  changePercent?: number;
  highPrice?: number;
  highPercent?: number;
  lowPrice?: number;
  lowPercent?: number;
  expectedImpact?: string;
  measuredReaction?: string;
  momentum?: string;
  volatility?: string;
  volume?: string;
  volumeRatio?: number | null;
  pricedIn?: string;
  windows?: Record<Timeframe, ImpactWindow>;
  chart?: Array<{ time: number; close: number | null }>;
};

type Props = {
  article: NewsArticleLike;
  digest: Digest | null;
  loading: boolean;
  error: string;
  timeframe: Timeframe;
};

const IMPACT_CACHE_KEY = "tradementor.news.impact.v1";
const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1u", "4u", "24u"];

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function readImpactCache(articleId: string): Impact | null {
  try {
    const root = record(JSON.parse(window.localStorage.getItem(IMPACT_CACHE_KEY) || "{}"));
    const row = record(root[articleId]);
    const savedAt = Number(row.savedAt || 0);
    if (!savedAt || Date.now() - savedAt > 2 * 60_000) return null;
    const value = row.value;
    return value && typeof value === "object" ? value as Impact : null;
  } catch { return null; }
}

function persistImpactCache(articleId: string, value: Impact) {
  try {
    const root = record(JSON.parse(window.localStorage.getItem(IMPACT_CACHE_KEY) || "{}"));
    const next: Record<string, unknown> = { ...root, [articleId]: { savedAt: Date.now(), value } };
    const keys = Object.keys(next);
    while (keys.length > 80) delete next[keys.shift()!];
    window.localStorage.setItem(IMPACT_CACHE_KEY, JSON.stringify(next));
  } catch { /* De kaart werkt ook zonder lokale cache. */ }
}

function coinLogo(symbol: string) {
  return symbol ? `https://assets.coincap.io/assets/icons/${symbol.toLowerCase()}@2x.png` : "";
}

function fmtPrice(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return "—";
  const digits = value >= 1000 ? 2 : value >= 1 ? 4 : value >= .01 ? 5 : 7;
  return `$${value.toLocaleString("nl-NL", { maximumFractionDigits: digits })}`;
}

function fmtPct(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

function tone(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value) || Math.abs(value) < .15) return "neutral";
  return value > 0 ? "positive" : "negative";
}

function impactExplanation(impact: Impact | null, symbol: string) {
  if (!impact?.available) return "Er is nog geen betrouwbare koersreactie beschikbaar om naast de nieuwsinhoud te leggen.";
  const expected = impact.expectedImpact || "Gemengd";
  const measured = impact.measuredReaction || "Onbekend";
  if (expected === measured) {
    return `De inhoud van het nieuws en de gemeten koersreactie wijzen voorlopig dezelfde kant op (${expected.toLowerCase()}). Dat is geen bewijs dat het nieuws de beweging heeft veroorzaakt; controleer ook volume en de bredere markt.`;
  }
  if (measured === "Neutraal") {
    return `De nieuwsinhoud wordt als ${expected.toLowerCase()} beoordeeld, maar ${symbol || "de koers"} heeft tot nu toe nauwelijks een duidelijke richting gekozen. De markt kan het nieuws nog verwerken of andere factoren kunnen zwaarder wegen.`;
  }
  return `De nieuwsinhoud wordt als ${expected.toLowerCase()} beoordeeld, terwijl de gemeten koersreactie ${measured.toLowerCase()} is. Dat verschil is belangrijk: andere marktontwikkelingen kunnen momenteel sterker zijn dan dit nieuwsbericht.`;
}

type DetailAdvice = { status: string; detail: string; tone: "positive" | "negative" | "caution" | "neutral" };

function detailAdvice(article: NewsArticleLike, timeframe: Timeframe, impact: Impact | null): DetailAdvice {
  const row = impact?.windows?.[timeframe];
  const expected = article.sentiment === "bullish" ? 1 : article.sentiment === "bearish" ? -1 : 0;
  const expectedWord = expected > 0 ? "positief" : expected < 0 ? "negatief" : "gemengd";

  if (impact?.available && row && !row.available) {
    return { status:"Nog te vroeg", detail:`Het ${timeframe}-venster is nog niet verstreken. Wacht op echte koersdata voordat je dit tijdsvenster beoordeelt.`, tone:"neutral" };
  }

  if (impact?.available && row?.available && row.changePercent !== null) {
    const measured = row.changePercent;
    const measuredDirection = Math.abs(measured) < .15 ? 0 : measured > 0 ? 1 : -1;
    if (expected === 0) {
      if (measuredDirection === 0) return { status:"Afwachten", detail:`De nieuwsinhoud is gemengd en de gemeten ${timeframe}-reactie is ${fmtPct(measured)}. Er is nog geen duidelijke richting.`, tone:"neutral" };
      return { status:"Voorzichtig", detail:`De nieuwsinhoud is gemengd, maar de koers bewoog op ${timeframe} ${fmtPct(measured)}. Behandel die beweging als marktreactie, niet automatisch als gevolg van dit bericht.`, tone:"caution" };
    }
    if (measuredDirection === expected) {
      if (/grotendeels ingeprijsd/i.test(impact.pricedIn || "")) return { status:"Waarschijnlijk verwerkt", detail:`De ${timeframe}-reactie van ${fmtPct(measured)} sluit aan bij de ${expectedWord}e nieuwsinhoud, maar de totale reactie lijkt inmiddels grotendeels verwerkt.`, tone:"caution" };
      return { status:expected > 0 ? "Positief bevestigd" : "Negatief bevestigd", detail:`De gemeten ${timeframe}-reactie is ${fmtPct(measured)} en sluit voorlopig aan bij de ${expectedWord}e nieuwsinhoud. Controleer of volume en marktstructuur dit blijven bevestigen.`, tone:expected > 0 ? "positive" : "negative" };
    }
    if (measuredDirection === 0) return { status:"Afwachten", detail:`De nieuwsinhoud is ${expectedWord}, maar de gemeten ${timeframe}-reactie is slechts ${fmtPct(measured)}. De koers bevestigt de richting nog niet.`, tone:"neutral" };
    return { status:"Tegenstrijdig", detail:`De nieuwsinhoud is ${expectedWord}, maar de koers reageerde op ${timeframe} met ${fmtPct(measured)} in de andere richting. Andere marktontwikkelingen kunnen zwaarder wegen.`, tone:"caution" };
  }

  if (article.importance === "high" && (timeframe === "1m" || timeframe === "5m")) {
    return { status:"Voorzichtig", detail:"Dit is nieuws met hoge impact. Op zeer korte tijdsvensters kunnen snelle uitschieters en omkeringen optreden; gemeten koersbevestiging ontbreekt nog.", tone:"caution" };
  }
  if (expected === 0) return { status:"Afwachten", detail:"De inhoud geeft geen sterke richting en er is geen betrouwbare koersreactie beschikbaar om die beoordeling aan te scherpen.", tone:"neutral" };
  return { status:expected > 0 ? "Inhoud positief" : "Inhoud negatief", detail:`De inhoud is ${expectedWord}, maar er is nog geen betrouwbare gemeten koersreactie beschikbaar. Gebruik dit niet als zelfstandige koop- of verkoopbeslissing.`, tone:expected > 0 ? "positive" : "negative" };
}

function MiniChart({ impact }: { impact: Impact }) {
  const points = useMemo(() => (impact.chart || []).filter((point) => point.close !== null && Number.isFinite(point.close)), [impact.chart]);
  if (points.length < 2) return <div className={styles.chartEmpty}>Niet genoeg koerspunten voor een grafiek.</div>;
  const values = points.map((point) => Number(point.close));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, Math.abs(max) * .0001, 1e-9);
  const width = 620;
  const height = 150;
  const padX = 8;
  const padY = 12;
  const x = (index: number) => padX + (index / Math.max(1, points.length - 1)) * (width - padX * 2);
  const y = (value: number) => padY + (1 - (value - min) / span) * (height - padY * 2);
  const path = points.map((point, index) => `${x(index).toFixed(1)},${y(Number(point.close)).toFixed(1)}`).join(" ");
  const published = Date.parse(impact.publishedAt || "");
  let markerIndex = 0;
  if (Number.isFinite(published)) {
    let distance = Number.POSITIVE_INFINITY;
    points.forEach((point,index) => {
      const next = Math.abs(point.time - published);
      if (next < distance) { distance = next; markerIndex = index; }
    });
  }
  return <div className={styles.chartWrap} data-no-doubletap="true">
    <svg className={styles.chart} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Koersreactie rond publicatie">
      <line className={styles.gridLine} x1="0" x2={width} y1={height * .33} y2={height * .33} />
      <line className={styles.gridLine} x1="0" x2={width} y1={height * .66} y2={height * .66} />
      <line className={styles.publishLine} x1={x(markerIndex)} x2={x(markerIndex)} y1="0" y2={height} />
      <polyline className={styles.priceLine} points={path} fill="none" />
      <circle className={styles.publishDot} cx={x(markerIndex)} cy={y(Number(points[markerIndex].close))} r="4" />
      <circle className={styles.nowDot} cx={x(points.length - 1)} cy={y(Number(points.at(-1)!.close))} r="4" />
    </svg>
    <div className={styles.chartLegend}><span>▼ Nieuws gepubliceerd</span><span>● Laatste punt</span></div>
  </div>;
}

export function NewsArticleExpanded({ article, digest, loading, error, timeframe }: Props) {
  const symbol = article.coins[0] || "";
  const [impact, setImpact] = useState<Impact | null>(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
    const cached = readImpactCache(article.id);
    if (cached) { setImpact(cached); return; }
    if (!symbol) { setImpact({ ok:true, available:false, reason:"Voor dit bericht is geen enkele munt als koersreferentie beschikbaar." }); return; }
    let cancelled = false;
    const controller = new AbortController();
    setImpactLoading(true);
    const params = new URLSearchParams({ symbol, publishedAt:article.publishedAt, sentiment:article.sentiment });
    fetch(`/api/news-impact?${params.toString()}`, { signal:controller.signal, cache:"no-store" })
      .then(async (response) => response.json() as Promise<Impact>)
      .then((value) => { if (!cancelled) { setImpact(value); persistImpactCache(article.id, value); } })
      .catch(() => { if (!cancelled) setImpact({ ok:true, available:false, reason:"Koersreactie is tijdelijk niet beschikbaar." }); })
      .finally(() => { if (!cancelled) setImpactLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [article.id, article.publishedAt, article.sentiment, symbol]);

  const sourceImage = digest?.article.imageUrl || article.imageUrl || "";
  const fallbackLogo = coinLogo(symbol);
  const displayImage = !imageFailed && sourceImage ? sourceImage : fallbackLogo;
  const sections = digest?.article.sections?.length
    ? digest.article.sections
    : digest?.article.paragraphs?.length
      ? [{ heading:"Wat is er gebeurd?", paragraphs:digest.article.paragraphs }]
      : [];
  const currentAdvice = detailAdvice(article, timeframe, impact);

  return <>
    <div className={styles.hero} data-source-image={Boolean(sourceImage && !imageFailed)}>
      {displayImage ? <img src={displayImage} alt={sourceImage && !imageFailed ? `Afbeelding bij ${article.title}` : `${symbol}-logo`} onError={() => setImageFailed(true)} /> : <div className={styles.heroFallback}>◎ {symbol || "Nieuws"}</div>}
      {digest?.article.imageFromSource && !imageFailed && <span className={styles.imageBadge}>Afbeelding uit bron</span>}
    </div>

    <section className={styles.article} aria-label="Uitgebreid Nederlands nieuwsartikel">
      <div className={styles.articleTopline}><span>Crypto Bot 2026 · duidelijk uitgelegd</span>{digest?.article.wordCount ? <small>± {digest.article.wordCount} woorden</small> : null}</div>
      {loading && <div className={styles.loading}><i /> Artikel wordt samengesteld…</div>}
      {!loading && digest && <>
        <h3>Kort uitgelegd</h3>
        <p className={styles.lead}>{digest.article.intro}</p>
        {sections.map((section,index) => <section className={styles.textSection} key={`${article.id}-section-${index}`}>
          <h3>{section.heading}</h3>
          {section.paragraphs.map((paragraph,pIndex) => <p key={`${article.id}-section-${index}-${pIndex}`}>{paragraph}</p>)}
        </section>)}
        {!!digest.article.keyPoints?.length && <section className={styles.points}><h3>Belangrijkste punten</h3>{digest.article.keyPoints.map((item,index) => <p key={`${article.id}-point-${index}`}>• {item}</p>)}</section>}
        {!!digest.article.watchFor?.length && <section className={styles.watch}><h3>Waar moet je op letten?</h3>{digest.article.watchFor.map((item,index) => <p key={`${article.id}-watch-${index}`}>• {item}</p>)}</section>}
        {digest.article.conclusion && <section className={styles.conclusion}><h3>Conclusie</h3><p>{digest.article.conclusion}</p></section>}
        <small className={styles.note}>{digest.article.note}{digest.article.author ? ` Auteur volgens de bron: ${digest.article.author}.` : ""}</small>
      </>}
      {!loading && !digest && <><p className={styles.lead}>{article.summary || "De bron geeft hierover geen aanvullende details."}</p>{error && <small className={styles.note}>{error}</small>}</>}
    </section>

    <section className={styles.impact} aria-label="Gemeten koersreactie">
      <div className={styles.impactHeader}><div><span>KOERSREACTIE</span><h3>{symbol ? `${symbol} rond publicatie` : "Marktreactie"}</h3></div>{impact?.source && <small>{impact.source}</small>}</div>
      {impactLoading && <div className={styles.loading}><i /> Koersreactie wordt gemeten…</div>}
      {!impactLoading && impact?.available && <>
        <div className={styles.metrics}>
          <div><small>Bij publicatie</small><strong>{fmtPrice(impact.publicationPrice)}</strong></div>
          <div><small>Nu</small><strong>{fmtPrice(impact.currentPrice)}</strong></div>
          <div><small>Sinds nieuws</small><strong data-tone={tone(impact.changePercent)}>{fmtPct(impact.changePercent)}</strong></div>
          <div><small>Hoogste</small><strong data-tone={tone(impact.highPercent)}>{fmtPct(impact.highPercent)}</strong></div>
          <div><small>Laagste</small><strong data-tone={tone(impact.lowPercent)}>{fmtPct(impact.lowPercent)}</strong></div>
        </div>
        <MiniChart impact={impact} />
        <div className={styles.windowGrid} data-no-doubletap="true">
          {TIMEFRAMES.map((value) => {
            const row = impact.windows?.[value];
            return <div key={value} data-active={value === timeframe}><b>{value}</b><span data-tone={tone(row?.changePercent)}>{row?.available ? fmtPct(row.changePercent) : "Nog niet beschikbaar"}</span></div>;
          })}
        </div>
        <section className={styles.meaning}>
          <h3>Wat betekent dit voor {symbol || "de markt"}?</h3>
          <p>{impactExplanation(impact, symbol)}</p>
          <div className={styles.impactFacts}>
            <span><small>Verwachte nieuwsimpact</small><b>{impact.expectedImpact || "Onbekend"}</b></span>
            <span><small>Gemeten reactie</small><b>{impact.measuredReaction || "Onbekend"}</b></span>
            <span><small>Momentum</small><b>{impact.momentum || "Onbekend"}</b></span>
            <span><small>Volatiliteit</small><b>{impact.volatility || "Onbekend"}</b></span>
            <span><small>Volume</small><b>{impact.volume || "Onbekend"}{impact.volumeRatio ? ` · ${impact.volumeRatio.toFixed(2)}×` : ""}</b></span>
            <span><small>Mogelijk ingeprijsd</small><b>{impact.pricedIn || "Onzeker"}</b></span>
          </div>
          <small className={styles.marketNote}>De koersreactie is gemeten marktdata, maar bewijst niet dat het nieuws de koersbeweging heeft veroorzaakt.{impact.observationCappedAt24h ? " Hoog/laag worden voor oudere berichten over de eerste 24 uur na publicatie gemeten." : ""}</small>
        </section>
      </>}
      {!impactLoading && impact && !impact.available && <div className={styles.unavailable}>{impact.reason || "Voor dit bericht is geen betrouwbare koersreactie beschikbaar."}</div>}
    </section>

    <section className={styles.advicePanel} data-no-doubletap="true" aria-label="Advies per tijdsvenster op basis van nieuws en koersreactie">
      <div className={styles.articleTopline}><span>ADVIES PER TIJDSVENSTER</span><small>Nieuws + gemeten koersreactie</small></div>
      <div className={styles.adviceFocus} data-tone={currentAdvice.tone}>
        <strong>Advies voor {timeframe}: {currentAdvice.status}</strong>
        <p>{currentAdvice.detail}</p>
      </div>
      <div className={styles.adviceRows}>
        {TIMEFRAMES.map((value) => {
          const advice = detailAdvice(article, value, impact);
          return <div className={styles.adviceRow} data-active={value === timeframe} key={value}>
            <b>{value}</b>
            <span>{advice.detail}</span>
            <em data-tone={advice.tone}>{advice.status}</em>
          </div>;
        })}
      </div>
      <small className={styles.marketNote}>Dit is beslissingsondersteuning. Nieuws en gemeten koersreactie openen, sluiten of wijzigen nooit automatisch een positie.</small>
    </section>
  </>;
}
