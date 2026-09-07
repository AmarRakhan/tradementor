from pathlib import Path

path = Path(__file__).resolve().parents[1] / "web" / "lib" / "portfolio-impact-battle.mjs"
source = path.read_text(encoding="utf-8")
old = '''  if (finite(dominanceScore) !== null) {
    const market = dominancePresentation(dominanceScore);'''
new = '''  const explicitDominanceScore = dominanceScore === null || dominanceScore === undefined || dominanceScore === "" ? null : finite(dominanceScore);
  if (explicitDominanceScore !== null) {
    const market = dominancePresentation(explicitDominanceScore);'''
if old not in source:
    raise SystemExit("Expected Bulls dominance compatibility block was not found")
path.write_text(source.replace(old, new, 1), encoding="utf-8")
print("Legacy Bulls helper compatibility restored")
