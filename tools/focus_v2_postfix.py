from pathlib import Path
p=Path(__file__).resolve().parents[1]/"web/components/aster-strategy2-maker.tsx"
s=p.read_text()
old='Airbag {v.focusAirbag?`AAN · ${v.focusAirbagStart}% → max ${v.focusAirbagMax}%`:"UIT"}'
new='Airbag {v.focusAirbag?`AAN · ${v.focusAirbagStart}% → max ${v.focusAirbagMax}%`:"UIT · huidige Focus ongewijzigd"}'
if old in s:
    s=s.replace(old,new,1)
elif new not in s:
    raise SystemExit("legacy Airbag summary anchor missing")
p.write_text(s)
print("legacy Airbag UI contract preserved")
