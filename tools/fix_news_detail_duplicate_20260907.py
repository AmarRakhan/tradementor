from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "web/components/news-view.tsx"

text = VIEW.read_text()
legacy = '''              <section className={styles.impact}><strong>💡 Wat betekent dit voor {timeframe}?</strong><p>{impactText(selected, timeframe)}</p></section>\n              <section className={styles.tfPanel} data-no-doubletap="true"><h3>💡 Advies per tijdsvenster</h3>{TIMEFRAMES.map((value) => { const advice = adviceFor(selected, value); return <div className={styles.tfRow} key={value}><b>{value}</b><span>{advice.detail}</span><span className={styles.statusPill} data-tone={advice.tone}>{advice.status}</span></div>; })}</section>'''

if legacy in text:
    text = text.replace(legacy, "", 1)
elif '<section className={styles.impact}><strong>💡 Wat betekent dit voor {timeframe}?' in text:
    raise RuntimeError("Legacy content-only News advice changed shape; refusing a partial removal")

VIEW.write_text(text)
print("Removed duplicate content-only News detail advice")
