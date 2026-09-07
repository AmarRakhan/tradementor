from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "web/components/news-view.tsx"
NEWS = ROOT / "web/app/api/news/route.ts"


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
VIEW.write_text(view)

news = NEWS.read_text()
news = replace_once(
    news,
    '  AVAX: ["avalanche", "avax"], LINK: ["chainlink", "link"], DOT: ["polkadot", "dot"], SUI: ["sui"], AAVE: ["aave"],',
    '  AVAX: ["avalanche", "avax"], LINK: ["chainlink", "$link", "link token"], ZEC: ["zcash", "zec"], DOT: ["polkadot", "dot"], SUI: ["sui"], AAVE: ["aave"],',
    "LINK false-positive alias",
)
NEWS.write_text(news)
print("Applied News detail/article/impact patch successfully")
