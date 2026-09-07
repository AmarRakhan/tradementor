from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "web/components/news-view.tsx"
NEWS = ROOT / "web/app/api/news/route.ts"
EXPANDED = ROOT / "web/components/news-article-expanded.tsx"
EXPANDED_CSS = ROOT / "web/components/news-article-expanded.module.css"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source block, found {count}")
    return text.replace(old, new, 1)


view = VIEW.read_text()
view = replace_once(
    view,
    'import articleStyles from "./news-article-detail.module.css";\n',
    'import articleStyles from "./news-article-detail.module.css";\nimport { NewsArticleExpanded } from "./news-article-expanded";\n',
    "expanded component import",
)
view = replace_once(
    view,
    '''type ArticleDigest = {\n  sourceUrl: string;\n  article: {\n    label: string;\n    intro: string;\n    paragraphs: string[];\n    keyPoints: string[];\n    basedOnFullSource: boolean;\n    note: string;\n  };\n};''',
    '''type ArticleDigest = {\n  sourceUrl: string;\n  article: {\n    label: string;\n    intro: string;\n    paragraphs: string[];\n    sections?: Array<{ heading: string; paragraphs: string[] }>;\n    keyPoints: string[];\n    watchFor?: string[];\n    conclusion?: string;\n    imageUrl?: string;\n    imageFromSource?: boolean;\n    author?: string;\n    wordCount?: number;\n    basedOnFullSource: boolean;\n    note: string;\n  };\n};''',
    "expanded digest type",
)
view = view.replace('const DETAIL_KEY = "tradementor.news.detail.nl.v1";', 'const DETAIL_KEY = "tradementor.news.detail.nl.v2";')
view = replace_once(
    view,
    '  const lastTap = useRef(0);',
    '''  const lastTap = useRef<{ time: number; x: number; y: number } | null>(null);\n  const pointerStart = useRef<{ pointerId: number; time: number; x: number; y: number } | null>(null);\n  const closeTimer = useRef<number | null>(null);''',
    "detail gesture refs",
)
view = replace_once(
    view,
    '    const params = new URLSearchParams({ url:selected.sourceUrl, title:selected.title, source:selected.source, summary:selected.summary });',
    '    const params = new URLSearchParams({ url:selected.sourceUrl, title:selected.title, source:selected.source, summary:selected.summary, image:selected.imageUrl || "", coin:selected.coins[0] || "", category:primaryCategory(selected) });',
    "expanded digest query",
)
view = replace_once(
    view,
    '''  const handleDetailTap = (event: React.PointerEvent) => {\n    if ((event.target as HTMLElement).closest("button,a,input")) return;\n    const now = Date.now();\n    if (now - lastTap.current < 330) { setSelected(null); lastTap.current = 0; }\n    else lastTap.current = now;\n  };''',
    '''  const isNeutralDetailTarget = (target: EventTarget | null) => {\n    const element = target instanceof HTMLElement ? target : null;\n    return !element?.closest("button,a,input,select,textarea,[data-no-doubletap='true']");\n  };\n\n  const closeDetail = () => {\n    if (!selected || closeTimer.current !== null) return;\n    setFlipped(false);\n    lastTap.current = null;\n    pointerStart.current = null;\n    closeTimer.current = window.setTimeout(() => {\n      closeTimer.current = null;\n      setSelected(null);\n    }, 680);\n  };\n\n  const handleDetailPointerDown = (event: React.PointerEvent) => {\n    if (!isNeutralDetailTarget(event.target)) { pointerStart.current = null; return; }\n    pointerStart.current = { pointerId:event.pointerId, time:Date.now(), x:event.clientX, y:event.clientY };\n  };\n\n  const handleDetailPointerUp = (event: React.PointerEvent) => {\n    const start = pointerStart.current;\n    pointerStart.current = null;\n    if (!start || start.pointerId !== event.pointerId || !isNeutralDetailTarget(event.target)) return;\n    const duration = Date.now() - start.time;\n    const movement = Math.hypot(event.clientX - start.x, event.clientY - start.y);\n    if (duration > 450 || movement > 14) return;\n    const tap = { time:Date.now(), x:event.clientX, y:event.clientY };\n    const previous = lastTap.current;\n    if (previous && tap.time - previous.time <= 380 && Math.hypot(tap.x - previous.x, tap.y - previous.y) <= 30) {\n      closeDetail();\n      return;\n    }\n    lastTap.current = tap;\n  };\n\n  const handleDetailDoubleClick = (event: React.MouseEvent) => {\n    if (isNeutralDetailTarget(event.target)) closeDetail();\n  };''',
    "robust double tap",
)
view = replace_once(
    view,
    '{selected && <div className={styles.detailLayer} onPointerUp={handleDetailTap} onDoubleClick={() => setSelected(null)} role="dialog" aria-modal="true" aria-label={`Nieuwsartikel ${selected.title}`}>',
    '{selected && <div className={styles.detailLayer} onPointerDown={handleDetailPointerDown} onPointerUp={handleDetailPointerUp} onDoubleClick={handleDetailDoubleClick} role="dialog" aria-modal="true" aria-label={`Nieuwsartikel ${selected.title}`}>',
    "detail gesture handlers",
)
view = view.replace('className={styles.backButton} onClick={() => setSelected(null)}', 'className={styles.backButton} onClick={closeDetail}')
old_article = '''              <div className={styles.heroImage}>{selected.coins[0] ? <img src={logoUrl(selected.coins[0])} alt={`${selected.coins[0]}-logo`} /> : <span className={styles.thumbFallback}>◎ Macro</span>}</div>\n              <section className={articleStyles.article} aria-label="Vereenvoudigd artikel in de app">\n                <div className={articleStyles.label}>Crypto Bot 2026 · duidelijk uitgelegd</div>\n                {detailLoading && <div className={articleStyles.loading}><i /> We maken van de bron een helder Nederlands artikel…</div>}\n                {!detailLoading && detailDigest && <>\n                  <p className={articleStyles.lead}>{detailDigest.article.intro}</p>\n                  {detailDigest.article.paragraphs.map((paragraph, index) => <p className={articleStyles.paragraph} key={`${selected.id}-p-${index}`}>{paragraph}</p>)}\n                  {!!detailDigest.article.keyPoints.length && <div className={articleStyles.points}><strong>Belangrijkste punten</strong>{detailDigest.article.keyPoints.map((point, index) => <span key={`${selected.id}-k-${index}`}>• {point}</span>)}</div>}\n                  <small className={articleStyles.note}>{detailDigest.article.note}{detailDigest.article.basedOnFullSource ? " De oorspronkelijke bron kon volledig worden ingelezen." : " De bron gaf niet alle tekst vrij; daarom is de beschikbare broninformatie gebruikt."}</small>\n                </>}\n                {!detailLoading && !detailDigest && <><p className={articleStyles.lead}>{selected.summary || "Voor dit bericht is nog geen uitgebreide brontekst beschikbaar."}</p>{detailError && <small className={articleStyles.note}>{detailError}</small>}</>}\n              </section>'''
new_article = '''              <NewsArticleExpanded article={selected} digest={detailDigest} loading={detailLoading} error={detailError} timeframe={timeframe} />'''
view = replace_once(view, old_article, new_article, "expanded article renderer")
view = view.replace('<section className={styles.tfPanel}><h3>💡 Advies per tijdsvenster</h3>', '<section className={styles.tfPanel} data-no-doubletap="true"><h3>💡 Advies per tijdsvenster</h3>')
legacy_detail_analysis = '''              <section className={styles.impact}><strong>💡 Wat betekent dit voor {timeframe}?</strong><p>{impactText(selected, timeframe)}</p></section>\n              <section className={styles.tfPanel} data-no-doubletap="true"><h3>💡 Advies per tijdsvenster</h3>{TIMEFRAMES.map((value) => { const advice = adviceFor(selected, value); return <div className={styles.tfRow} key={value}><b>{value}</b><span>{advice.detail}</span><span className={styles.statusPill} data-tone={advice.tone}>{advice.status}</span></div>; })}</section>'''
view = replace_once(view, legacy_detail_analysis, '', "remove duplicate content-only detail advice")
VIEW.write_text(view)

news = NEWS.read_text()
news = replace_once(
    news,
    '  AVAX: ["avalanche", "avax"], LINK: ["chainlink", "link"], DOT: ["polkadot", "dot"], SUI: ["sui"], AAVE: ["aave"],',
    '  AVAX: ["avalanche", "avax"], LINK: ["chainlink", "$link", "link token"], ZEC: ["zcash", "zec"], DOT: ["polkadot", "dot"], SUI: ["sui"], AAVE: ["aave"],',
    "LINK false-positive alias",
)
NEWS.write_text(news)

expanded = EXPANDED.read_text()
expanded = replace_once(
    expanded,
    '  sentiment: "bullish" | "bearish" | "neutral";\n};',
    '  sentiment: "bullish" | "bearish" | "neutral";\n  importance: "high" | "normal";\n};',
    "importance for detail advice",
)
detail_helper = r'''type DetailAdvice = { status: string; detail: string; tone: "positive" | "negative" | "caution" | "neutral" };

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

'''
expanded = replace_once(expanded, 'function MiniChart({ impact }: { impact: Impact }) {', detail_helper + 'function MiniChart({ impact }: { impact: Impact }) {', "price-aware detail advice helper")
expanded = replace_once(
    expanded,
    '''  const sections = digest?.article.sections?.length\n    ? digest.article.sections\n    : digest?.article.paragraphs?.length\n      ? [{ heading:"Wat is er gebeurd?", paragraphs:digest.article.paragraphs }]\n      : [];''',
    '''  const sections = digest?.article.sections?.length\n    ? digest.article.sections\n    : digest?.article.paragraphs?.length\n      ? [{ heading:"Wat is er gebeurd?", paragraphs:digest.article.paragraphs }]\n      : [];\n  const currentAdvice = detailAdvice(article, timeframe, impact);''',
    "current price-aware advice",
)
price_advice_panel = r'''

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
    </section>'''
expanded = replace_once(expanded, '    </section>\n  </>;\n}', '    </section>' + price_advice_panel + '\n  </>;\n}', "price-aware timeframe panel")
EXPANDED.write_text(expanded)

css = EXPANDED_CSS.read_text()
if ".advicePanel {" not in css:
    css += r'''

.advicePanel {
  margin: 0 0 10px;
  padding: 12px;
  border: 1px solid rgba(0,243,154,.3);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(4,28,19,.92), rgba(2,15,10,.96));
}

.adviceFocus {
  padding: 9px 10px;
  margin-bottom: 8px;
  border: 1px solid rgba(0,243,154,.16);
  border-radius: 9px;
  background: rgba(0,10,6,.48);
}

.adviceFocus strong {
  display: block;
  margin-bottom: 4px;
  font-size: 10px;
}

.adviceFocus p {
  margin: 0;
  color: #b8ccc4;
  font-size: 9.5px;
  line-height: 1.42;
}

.adviceRows {
  display: grid;
  gap: 4px;
}

.adviceRow {
  display: grid;
  grid-template-columns: 34px minmax(0,1fr) 102px;
  gap: 7px;
  align-items: center;
  padding: 7px 6px;
  border: 1px solid rgba(0,243,154,.1);
  border-radius: 8px;
  background: rgba(0,8,5,.38);
}

.adviceRow[data-active="true"] {
  border-color: rgba(0,243,154,.58);
  box-shadow: inset 0 0 10px rgba(0,243,154,.055);
}

.adviceRow b {
  color: #8fd8b9;
  font-size: 9px;
}

.adviceRow span {
  color: #aebfb9;
  font-size: 8.5px;
  line-height: 1.32;
}

.adviceRow em {
  justify-self: end;
  max-width: 102px;
  padding: 4px 6px;
  border: 1px solid currentColor;
  border-radius: 999px;
  font-size: 7.5px;
  line-height: 1.05;
  font-style: normal;
  text-align: center;
}

@media (max-width: 390px) {
  .advicePanel { padding: 10px; }
  .adviceRow { grid-template-columns: 30px minmax(0,1fr) 88px; gap: 5px; }
  .adviceRow span { font-size: 8px; }
  .adviceRow em { max-width: 88px; font-size: 7px; }
}
'''
EXPANDED_CSS.write_text(css)
print("Applied News detail/article/impact patch successfully")
