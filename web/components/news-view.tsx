"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import styles from "./news-view.module.css";

type Timeframe = "1m" | "5m" | "15m" | "1u" | "4u" | "24u";
type ArchiveMode = "today" | "yesterday" | "7d" | "30d" | "all" | "saved" | "custom";
type AdviceTone = "positive" | "negative" | "caution" | "neutral";
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
  categories: string[];
  importance: "high" | "normal";
  sentiment: "bullish" | "bearish" | "neutral";
  sentimentScore: number;
  confidence: number;
};

type Advice = { label: string; detail: string; status: string; tone: AdviceTone };
type AlertPrefs = { breaking: boolean; important: boolean; topN: boolean; highImpact: boolean };

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1u", "4u", "24u"];
const CATEGORIES = ["Alles", "Belangrijk", "Koers", "Analyse", "Partnerships", "Regulatie"] as const;
const FALLBACK = ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","HYPE","AVAX","LINK","SUI","TRX","TON","BCH","AAVE","NEAR","LTC","DOT","UNI","XLM","SHIB","ATOM","ARB","OP","INJ","FIL","RENDER","SEI","TIA","ASTER","ENA","APT","PEPE","WIF","ONDO","MKR","LDO","JUP","FET","TAO","ETC","ALGO","ICP","VET","HBAR","RUNE","GRT","KAS","IMX","STX"];
const ARCHIVE_KEY = "tradementor.news.archive.v1";
const SAVED_KEY = "tradementor.news.saved.v1";
const ALERT_KEY = "tradementor.news.alerts.v1";

function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function pairSymbol(value: unknown) { return String(value || "").toUpperCase().replace(/[^A-Z0-9]/g, "").replace(/(USDT|USDC|USD|PERP)$/i, "").replace(/^1000(?=[A-Z])/, ""); }

function locateStrategySettings(value: unknown, depth = 0): Record<string, unknown> {
  if (depth > 6 || !value || typeof value !== "object") return {};
  const row = record(value);
  if ("universeTopN" in row || "manualSymbolSelectionEnabled" in row) return row;
  for (const key of ["settings", "state", "strategy2", "persisted", "config", "multiBb", "multiBbReport"]) {
    if (key in row) {
      const found = locateStrategySettings(row[key], depth + 1);
      if (Object.keys(found).length) return found;
    }
  }
  for (const child of Object.values(row)) {
    const found = locateStrategySettings(child, depth + 1);
    if (Object.keys(found).length) return found;
  }
  return {};
}

function readArchive(): NewsArticle[] {
  try {
    const value = JSON.parse(window.localStorage.getItem(ARCHIVE_KEY) || "[]");
    return Array.isArray(value) ? value.filter((item) => item && typeof item === "object" && typeof item.id === "string") as NewsArticle[] : [];
  } catch { return []; }
}

function persistArchive(items: NewsArticle[]) {
  try {
    const byId = new Map<string, NewsArticle>();
    for (const item of items) byId.set(item.id, item);
    const compact = Array.from(byId.values()).sort((a,b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt)).slice(0, 500);
    window.localStorage.setItem(ARCHIVE_KEY, JSON.stringify(compact));
  } catch { /* Nieuwsoverzicht blijft bruikbaar als lokale opslag vol of geblokkeerd is. */ }
}

function readSaved() {
  try {
    const value = JSON.parse(window.localStorage.getItem(SAVED_KEY) || "[]");
    return new Set<string>(Array.isArray(value) ? value.map(String) : []);
  } catch { return new Set<string>(); }
}

function readAlerts(): AlertPrefs {
  try {
    const row = record(JSON.parse(window.localStorage.getItem(ALERT_KEY) || "{}"));
    return { breaking: row.breaking === true, important: row.important !== false, topN: row.topN !== false, highImpact: row.highImpact === true };
  } catch { return { breaking:false, important:true, topN:true, highImpact:false }; }
}

function hoursOld(article: NewsArticle) { return Math.max(0, (Date.now() - Date.parse(article.publishedAt)) / 3_600_000); }

function adviceFor(article: NewsArticle, timeframe: Timeframe): Advice {
  const age = hoursOld(article);
  const windows: Record<Timeframe, number> = { "1m": .35, "5m": 1.5, "15m": 4, "1u": 16, "4u": 48, "24u": 96 };
  const ageLimit = windows[timeframe];
  if (age > ageLimit * 2.2) return { label: "rust", detail: "Dit nieuws is voor dit timeframe waarschijnlijk grotendeels verwerkt; kijk vooral naar de actuele prijsreactie.", status: "Neutraal", tone: "neutral" };
  if (article.sentiment === "neutral" || Math.abs(article.sentimentScore) < .15) return { label: "afwachten", detail: "De nieuwsrichting is niet sterk genoeg om op zichzelf een richting te bevestigen.", status: "Neutraal", tone: "neutral" };
  if ((timeframe === "1m" || timeframe === "5m") && article.importance === "high") {
    return { label: "voorzichtig", detail: "Hoge nieuwsimpact kan op korte timeframes veel ruis en snelle reversals veroorzaken.", status: "Voorzichtig", tone: "caution" };
  }
  if (age > ageLimit) return { label: "bevestiging", detail: "Het nieuws is nog relevant, maar controleer of de marktbeweging al is ingezet voordat je een conclusie trekt.", status: "Voorzichtig", tone: "caution" };
  if (article.sentiment === "bullish") {
    const strong = (timeframe === "4u" || timeframe === "24u") && article.confidence >= .68;
    return { label: strong ? "bullish" : "positief", detail: strong ? "De nieuwsimpact ondersteunt op dit timeframe een positieve bias, zolang marktstructuur en volume bevestigen." : "Positieve nieuwsimpact; wacht op bevestiging in koers en volume.", status: strong ? "Bullish" : "Positief", tone: "positive" };
  }
  const strong = (timeframe === "4u" || timeframe === "24u") && article.confidence >= .68;
  return { label: strong ? "bearish" : "negatief", detail: strong ? "De nieuwsimpact ondersteunt op dit timeframe een negatieve bias, zolang marktstructuur en volume bevestigen." : "Negatieve nieuwsimpact; controleer of koers en volume de beweging bevestigen.", status: strong ? "Bearish" : "Negatief", tone: "negative" };
}

function relativeTime(value: string) {
  const ms = Date.now() - Date.parse(value);
  const minutes = Math.max(0, Math.floor(ms / 60_000));
  if (minutes < 1) return "zojuist";
  if (minutes < 60) return `${minutes} min geleden`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} uur geleden`;
  const days = Math.floor(hours / 24);
  return `${days} dag${days === 1 ? "" : "en"} geleden`;
}

function localDayKey(value: string) {
  const d = new Date(value);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}
function todayKey() { return localDayKey(new Date().toISOString()); }
function yesterdayKey() { return localDayKey(new Date(Date.now()-86_400_000).toISOString()); }
function dayLabel(key: string) {
  if (key === todayKey()) return "Vandaag";
  if (key === yesterdayKey()) return "Gisteren";
  const [y,m,d] = key.split("-").map(Number);
  return new Date(y,m-1,d).toLocaleDateString("nl-NL", { day:"numeric", month:"long" });
}
function dayDisplay(key: string) {
  const [y,m,d] = key.split("-").map(Number);
  return new Date(y,m-1,d).toLocaleDateString("nl-NL", { weekday:"short", day:"numeric", month:"short", year:"numeric" });
}

function logoUrl(symbol: string) {
  if (symbol === "Macro") return "";
  return `https://assets.coincap.io/assets/icons/${symbol.toLowerCase()}@2x.png`;
}

function primaryCategory(article: NewsArticle) {
  if (article.importance === "high") return "Belangrijk";
  return article.categories.find((item) => item !== "Belangrijk") || "Analyse";
}

function impactText(article: NewsArticle, timeframe: Timeframe) {
  const advice = adviceFor(article, timeframe);
  const direction = article.sentiment === "bullish" ? "positief" : article.sentiment === "bearish" ? "negatief" : "gemengd";
  return `De tekstuele nieuwsimpact is ${direction}. ${advice.detail} Dit is beslissingsondersteuning; de bot opent, sluit of wijzigt hierdoor geen enkele order.`;
}

function CompactArticle({ article, timeframe, saved, onOpen }: { article: NewsArticle; timeframe: Timeframe; saved: boolean; onOpen: () => void }) {
  const symbol = article.coins[0] || "Macro";
  const advice = adviceFor(article, timeframe);
  const [imageFailed, setImageFailed] = useState(false);
  return <article className={styles.card} onClick={onOpen} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onOpen(); }} aria-label={`Open nieuwsartikel: ${article.title}`}>
    <div className={styles.thumb}>{symbol !== "Macro" && !imageFailed && <img src={logoUrl(symbol)} alt="" onError={() => setImageFailed(true)} />}<span className={styles.thumbFallback}>{symbol === "Macro" ? "◎" : symbol}</span></div>
    <div className={styles.cardBody}>
      <div className={styles.meta}><span className={styles.ticker}>{symbol}</span><span className={styles.source}>{article.source}</span><span>·</span><span>{relativeTime(article.publishedAt)}</span>{saved && <span title="Opgeslagen">♥</span>}<span className={styles.category}>{primaryCategory(article)}</span></div>
      <h3 className={styles.title}>{article.title}</h3>
      <div className={styles.advice}>💡 Advies: {timeframe} {advice.label}</div>
    </div>
    <span className={styles.chevron}>›</span>
  </article>;
}

export function NewsView() {
  const [universe, setUniverse] = useState<string[]>(FALLBACK);
  const [topN, setTopN] = useState(50);
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [coin, setCoin] = useState("Alle");
  const [category, setCategory] = useState<(typeof CATEGORIES)[number]>("Alles");
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [query, setQuery] = useState("");
  const [archiveMode, setArchiveMode] = useState<ArchiveMode>("today");
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<NewsArticle | null>(null);
  const [flipped, setFlipped] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [alerts, setAlerts] = useState<AlertPrefs>({ breaking:false, important:true, topN:true, highImpact:false });
  const lastTap = useRef(0);

  useEffect(() => {
    setSaved(readSaved());
    setAlerts(readAlerts());
    const cached = readArchive();
    if (cached.length) setArticles(cached);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadUniverse = async (attempt = 0) => {
      try {
        const status = await authenticatedRequest("/api/exchanges/aster") as Record<string, unknown>;
        if (cancelled) return;
        const settings = locateStrategySettings(status);
        const configuredTopN = Math.max(1, Math.min(100, Math.round(Number(settings.universeTopN ?? 50) || 50)));
        setTopN(configuredTopN);
        const manual = settings.manualSymbolSelectionEnabled === true && Array.isArray(settings.manualSymbols)
          ? (settings.manualSymbols as unknown[]).map((item) => pairSymbol(record(item).symbol)).filter(Boolean)
          : [];
        if (manual.length) { setUniverse(Array.from(new Set(manual))); return; }
        const markets = await authenticatedRequest("/api/exchanges/aster/strategy2/focus/markets") as Record<string, unknown>;
        if (cancelled) return;
        const ranking = Array.isArray(markets.ranking) ? markets.ranking : [];
        const symbols = ranking.map((item) => pairSymbol(record(item).symbol)).filter(Boolean).slice(0, configuredTopN);
        if (symbols.length) setUniverse(Array.from(new Set(symbols)));
        else setUniverse(FALLBACK.slice(0, configuredTopN));
      } catch {
        if (!cancelled && attempt < 2) window.setTimeout(() => void loadUniverse(attempt + 1), 1200 * (attempt + 1));
      }
    };
    void loadUniverse();
    return () => { cancelled = true; };
  }, []);

  const requestRange = archiveMode === "all" || archiveMode === "custom" ? "90d" : archiveMode === "7d" ? "7d" : archiveMode === "today" || archiveMode === "yesterday" ? "7d" : "30d";
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const loadNews = async () => {
      setLoading(true); setError("");
      try {
        const params = new URLSearchParams({ symbols: universe.slice(0, 60).join(","), range: requestRange, limit: "160" });
        const response = await fetch(`/api/news?${params.toString()}`, { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error("Nieuwsfeed kon niet worden geladen.");
        const payload = await response.json() as { items?: NewsArticle[] };
        if (cancelled) return;
        const fresh = Array.isArray(payload.items) ? payload.items : [];
        const cached = readArchive();
        const merged = new Map<string, NewsArticle>();
        for (const item of [...fresh, ...cached]) merged.set(item.id, item);
        const all = Array.from(merged.values()).sort((a,b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
        setArticles(all);
        persistArchive(all);
      } catch (reason) {
        if (!cancelled && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Nieuws is tijdelijk niet beschikbaar.");
      } finally { if (!cancelled) setLoading(false); }
    };
    if (universe.length) void loadNews();
    return () => { cancelled = true; controller.abort(); };
  }, [universe.join(","), requestRange]);

  useEffect(() => {
    if (!selected) { setFlipped(false); return; }
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => setFlipped(true));
    const esc = (event: KeyboardEvent) => { if (event.key === "Escape") setSelected(null); };
    window.addEventListener("keydown", esc);
    return () => { window.cancelAnimationFrame(frame); window.removeEventListener("keydown", esc); document.body.style.overflow = previous; };
  }, [selected]);

  const filtered = useMemo(() => {
    const now = Date.now();
    const q = query.trim().toLowerCase();
    return articles.filter((article) => {
      if (coin !== "Alle" && !article.coins.includes(coin)) return false;
      if (category === "Belangrijk" && article.importance !== "high") return false;
      if (category !== "Alles" && category !== "Belangrijk" && !article.categories.includes(category)) return false;
      if (q && !`${article.title} ${article.summary} ${article.source} ${article.coins.join(" ")} ${article.categories.join(" ")}`.toLowerCase().includes(q)) return false;
      const published = Date.parse(article.publishedAt);
      if (archiveMode === "saved" && !saved.has(article.id)) return false;
      if (archiveMode === "today" && localDayKey(article.publishedAt) !== todayKey()) return false;
      if (archiveMode === "yesterday" && localDayKey(article.publishedAt) !== yesterdayKey()) return false;
      if (archiveMode === "7d" && now - published > 7 * 86_400_000) return false;
      if (archiveMode === "30d" && now - published > 30 * 86_400_000) return false;
      if (archiveMode === "custom") {
        const from = customFrom ? new Date(`${customFrom}T00:00:00`).getTime() : 0;
        const to = customTo ? new Date(`${customTo}T23:59:59`).getTime() : Number.POSITIVE_INFINITY;
        if (published < from || published > to) return false;
      }
      return true;
    });
  }, [articles, coin, category, query, archiveMode, saved, customFrom, customTo]);

  const groups = useMemo(() => {
    const result: Array<{ key:string; items:NewsArticle[] }> = [];
    for (const article of filtered.slice(0, 90)) {
      const key = localDayKey(article.publishedAt);
      const last = result[result.length - 1];
      if (last?.key === key) last.items.push(article); else result.push({ key, items:[article] });
    }
    return result;
  }, [filtered]);

  const coinFilters = useMemo(() => Array.from(new Set(universe)).slice(0, Math.max(8, Math.min(topN, 24))), [universe, topN]);

  const toggleSaved = (article: NewsArticle) => {
    setSaved((current) => {
      const next = new Set(current);
      if (next.has(article.id)) next.delete(article.id); else next.add(article.id);
      try { window.localStorage.setItem(SAVED_KEY, JSON.stringify(Array.from(next))); persistArchive([article, ...readArchive()]); } catch {}
      return next;
    });
  };

  const updateAlert = (key: keyof AlertPrefs, value: boolean) => {
    setAlerts((current) => {
      const next = { ...current, [key]: value };
      try { window.localStorage.setItem(ALERT_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
  };

  const handleDetailTap = (event: React.PointerEvent) => {
    if ((event.target as HTMLElement).closest("button,a,input")) return;
    const now = Date.now();
    if (now - lastTap.current < 330) { setSelected(null); lastTap.current = 0; }
    else lastTap.current = now;
  };

  const archiveLabel = archiveMode === "today" ? "Vandaag" : archiveMode === "yesterday" ? "Gisteren" : archiveMode === "7d" ? "7 dagen" : archiveMode === "30d" ? "30 dagen" : archiveMode === "saved" ? "Opgeslagen" : archiveMode === "custom" ? "Periode" : "Archief";

  return <section className={styles.news} aria-label="Crypto nieuws op basis van Top-N">
    <header className={styles.header}><div><h1>Nieuws</h1><p>Actueel nieuws op basis van jouw top-{topN} coins</p></div><button type="button" className={styles.alertButton} onClick={() => setAlertsOpen(true)}>♧ Meldingen</button></header>

    <div className={`${styles.scroller} ${styles.coinRow}`} aria-label="Coinfilters">
      <button type="button" className={`${styles.coinFilter} ${coin === "Alle" ? styles.active : ""}`} onClick={() => setCoin("Alle")}>Alle</button>
      {coinFilters.map((symbol) => <button type="button" key={symbol} className={`${styles.coinFilter} ${coin === symbol ? styles.active : ""}`} onClick={() => setCoin(symbol)}><span className={styles.coinDot} data-symbol={symbol}>{symbol.slice(0,2)}</span>{symbol}</button>)}
    </div>

    <div className={`${styles.scroller} ${styles.categoryRow}`} aria-label="Nieuwscategorieën">
      {CATEGORIES.map((value) => <button type="button" key={value} className={`${styles.filter} ${category === value ? styles.active : ""}`} onClick={() => setCategory(value)}>{value}</button>)}
    </div>

    <div className={styles.timeframes} aria-label="Timeframe voor nieuwsadvies">
      {TIMEFRAMES.map((value) => <button type="button" key={value} className={`${styles.timeButton} ${timeframe === value ? styles.active : ""}`} onClick={() => setTimeframe(value)}>{value}</button>)}
    </div>

    <div className={styles.tools}>
      <label className={styles.search}><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Zoek nieuws, coin of onderwerp..." /></label>
      <div className={styles.archiveWrap}><button type="button" className={styles.archiveButton} onClick={() => setArchiveOpen((value) => !value)}>◷ {archiveLabel}⌄</button>{archiveOpen && <div className={styles.popover}>
        {([['today','Vandaag'],['yesterday','Gisteren'],['7d','Afgelopen 7 dagen'],['30d','Afgelopen 30 dagen'],['all','Alle historie'],['saved','Opgeslagen'],['custom','Eigen periode']] as Array<[ArchiveMode,string]>).map(([mode,label]) => <button type="button" key={mode} data-active={archiveMode === mode} onClick={() => { setArchiveMode(mode); if (mode !== "custom") setArchiveOpen(false); }}>{label}</button>)}
        {archiveMode === "custom" && <div className={styles.dateInputs}><input type="date" value={customFrom} onChange={(event) => setCustomFrom(event.target.value)} aria-label="Vanaf datum" /><input type="date" value={customTo} onChange={(event) => setCustomTo(event.target.value)} aria-label="Tot datum" /></div>}
      </div>}</div>
    </div>

    <div className={styles.statusLine}><i />{loading ? "Nieuws wordt bijgewerkt…" : error ? `${error} · lokale historie blijft zichtbaar` : `${filtered.length} artikelen · Top-${topN} gekoppeld`}</div>

    {groups.length ? groups.map((group) => <section key={group.key}><div className={styles.dayHeader}><h2>{dayLabel(group.key)}</h2><time>{dayDisplay(group.key)}</time></div><div className={styles.list}>{group.items.map((article) => <CompactArticle key={article.id} article={article} timeframe={timeframe} saved={saved.has(article.id)} onOpen={() => setSelected(article)} />)}</div></section>) : <div className={styles.empty}><div><strong>Geen nieuws voor deze selectie</strong><span>Kies een andere coin, categorie of archiefperiode.</span></div></div>}

    {selected && <div className={styles.detailLayer} onPointerUp={handleDetailTap} onDoubleClick={() => setSelected(null)} role="dialog" aria-modal="true" aria-label={`Nieuwsartikel ${selected.title}`}>
      <div className={`${styles.detailCard} ${flipped ? styles.flipped : ""}`}>
        <div className={styles.detailInner}>
          <div className={`${styles.detailFace} ${styles.detailFront}`}><div className={styles.frontPreview}><CompactArticle article={selected} timeframe={timeframe} saved={saved.has(selected.id)} onOpen={() => {}} /></div></div>
          <article className={`${styles.detailFace} ${styles.detailBack}`}>
            <header className={styles.detailHeader}><button type="button" className={styles.backButton} onClick={() => setSelected(null)} aria-label="Terug naar overzicht">←</button><span className={styles.ticker}>{selected.coins[0] || "Macro"}</span><span className={styles.source}>{selected.source} · {relativeTime(selected.publishedAt)}</span><button type="button" className={styles.saveButton} onClick={() => toggleSaved(selected)}>{saved.has(selected.id) ? "♥ Opgeslagen" : "♡ Opslaan"}</button></header>
            <div className={styles.detailScroll}>
              <h2 className={styles.detailTitle}>{selected.title}</h2>
              <div className={styles.heroImage}>{selected.coins[0] ? <img src={logoUrl(selected.coins[0])} alt={`${selected.coins[0]} logo`} /> : <span className={styles.thumbFallback}>◎ Macro</span>}</div>
              <p className={styles.quote}>{selected.summary || "Open het originele bronartikel voor de volledige publicatie."}</p>
              <section className={styles.impact}><strong>💡 Advies op {timeframe}</strong><p>{impactText(selected, timeframe)}</p></section>
              <section className={styles.tfPanel}><h3>💡 Advies op timeframe</h3>{TIMEFRAMES.map((value) => { const advice = adviceFor(selected, value); return <div className={styles.tfRow} key={value}><b>{value}</b><span>{advice.detail}</span><span className={styles.statusPill} data-tone={advice.tone}>{advice.status}</span></div>; })}</section>
            </div>
            <footer className={styles.detailActions}><button type="button" className={styles.readButton} onClick={() => window.open(selected.sourceUrl, "_blank", "noopener,noreferrer")}>↗ Lees volledig artikel</button><div className={styles.doubleHint}>◇ Dubbeltik<br/>om terug te draaien</div></footer>
          </article>
        </div>
      </div>
    </div>}

    {alertsOpen && <div className={styles.modalLayer} onMouseDown={() => setAlertsOpen(false)}><section className={styles.sheet} onMouseDown={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="Nieuws meldingen"><header><h3>Nieuws meldingen</h3><button type="button" onClick={() => setAlertsOpen(false)}>×</button></header>
      <label className={styles.toggleRow}><span><strong>Belangrijk nieuws</strong><small>Hoge impact, regulatie, ETF, hacks en macro.</small></span><input type="checkbox" checked={alerts.important} onChange={(event) => updateAlert("important", event.target.checked)} /></label>
      <label className={styles.toggleRow}><span><strong>Alleen mijn Top-N</strong><small>Gebruik dezelfde coin-universe als de Aster bot.</small></span><input type="checkbox" checked={alerts.topN} onChange={(event) => updateAlert("topN", event.target.checked)} /></label>
      <label className={styles.toggleRow}><span><strong>Breaking news</strong><small>Voorbereiding voor directe pushmeldingen.</small></span><input type="checkbox" checked={alerts.breaking} onChange={(event) => updateAlert("breaking", event.target.checked)} /></label>
      <label className={styles.toggleRow}><span><strong>Alleen hoge impact</strong><small>Beperk meldingen tot nieuws met sterke potentiële marktimpact.</small></span><input type="checkbox" checked={alerts.highImpact} onChange={(event) => updateAlert("highImpact", event.target.checked)} /></label>
      <p className={styles.disclaimer}>Nieuwsadvies is beslissingsondersteuning. Het nieuws-tabblad opent, sluit of wijzigt nooit automatisch een LONG, SHORT, DCA, TP of leverage-instelling.</p>
    </section></div>}
  </section>;
}
