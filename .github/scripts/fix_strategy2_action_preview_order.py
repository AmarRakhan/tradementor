from pathlib import Path

p = Path("web/components/aster-recent-trades.tsx")
text = p.read_text()
old = 'const detailNextDcaNumber=finite(detailRuntime?.nextDcaNumber)??finite(detailNextDca?.number)??((detailDcaCount??0)+1);'
new = 'const detailNextDcaNumber=finite(detailRuntime?.nextDcaNumber)??finite(detailNextDca?.number)??1;'
if old not in text:
    raise SystemExit("next DCA number order repair anchor missing")
p.write_text(text.replace(old, new, 1))
print("Strategy 2 preview declaration order repaired")
