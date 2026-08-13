# Branch- en releaseflow (public + test)

## Branches

- `main` = publieke/stabiele versie
- `test` = interne testversie (nieuwe functies, snelle iteraties)

## Dagelijkse werkmethode

1. Werk op `test`:
   - nieuwe code, UI-wijzigingen, strategie-aanpassingen
2. Doe een lokale testbuild op 1+ telefoon
3. Als alles goed draait: merge naar `main`
4. Bouw nieuwe publieke release vanaf `main`

## Commando's

```powershell
git checkout test
git pull origin test --ff-only

git add .
git commit -m "feat: jouw wijziging"
git push origin test
```

Publicatie naar `main`:

```powershell
git checkout main
git merge --no-ff test -m "chore: release from test"
git push origin main
```

## Wat niet in `main` komt

- lokale debug-instellingen
- test-only knoppen of logging
- oude crash artifacts / diagnostiek
- API- of sleutelbestand dat per toestel verschilt

## Aanbevolen tagging

- `v2.xx.x-test` = tags op `test`
- `v2.xx.x` = tags op `main`

## Noodprocedure

Als een appversie op meerdere toestellen afwijkend gedrag geeft:

- blijf op `test` voor quick fixes
- maak een kleine branch (`fix/..`) vanaf `test`
- los op, test op meerdere toestellen, merge terug naar `test`
- pas daarna door naar `main`

