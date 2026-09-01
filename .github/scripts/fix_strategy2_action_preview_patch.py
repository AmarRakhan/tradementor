from pathlib import Path

p = Path("web/components/aster-recent-trades.tsx")
text = p.read_text()
needle = '<div><span>Portfoliowaarde bij TP</span><strong>{money(detailPortfolioAtTp)}</strong></div>{detailAirbag&&<section'
replacement = '<div><span>Portfoliowaarde bij TP</span><strong>{money(detailPortfolioAtTp)}</strong></div></div>{detailAirbag&&<section'
if needle not in text:
    raise SystemExit("summary wrapper repair anchor missing")
p.write_text(text.replace(needle, replacement, 1))
print("Strategy 2 preview summary wrapper repaired")
