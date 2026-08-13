# TradeMentor Release Runbook (één versie uitrollen, zonder onderbrekingen)

Dit is de vaste volgorde voor jouw project vanaf nu.

## 1) Ontwikkelen in `test`

1. Nieuwe wijziging doen
2. Test lokaal of op emulator
3. Commit op `test`:
```powershell
git add .
git commit -m "feat: jouw wijziging"
git push origin test
```
4. Bouw en installeer test-APK op je apparaat

## 2) Testrelease check op toestel

1. Controleer buildnummer in de app
2. Open:
   - Wallet
   - Live Positions
   - Risk
3. Check minimale smoke-tests:
   - Login/screen loads
   - Wallet connect/wijziging zichtbaar
   - Scan knop gedrag (aan/uit)
   - Cloud-status statusindicator groen
4. Bij afwijking:
   - Verifieer dat exacte APK-tag op beide toestellen staat
   - Force stop
   - Heropen en terug naar Wallet

## 3) Naar `main` promoten

Als test stabiel is:

```powershell
git checkout main
git merge --no-ff test -m "chore: promote test to main"
git tag v2.xx.y
git push origin main --tags
```

## 4) Release APK voor gebruikers

1. Build release uit `main`
2. Controleer versiecode/buildnummer
3. Installeer/verspreid deze APK:
   - Testers via directe APK
   - Later via jouw publicatiekanaal (store/portal)

## 5) Wat publiceren betekent (belangrijk)

- `test` commit = interne testversie, niet automatisch publiek
- `main` + tag = versie die voor gebruikers bedoeld is
- Broncode blijft in GitHub privé tenzij je expliciet open publiceert

## 6) Bij probleem na publicatie

1. Build niet-werkend toestel checken met exact versie en buildcode
2. Rollback met vorige tag:
```powershell
git checkout v2.xx.y-vorige
```
of vorige release-APK opnieuw installeren.
3. Fix in `test`, opnieuw valideren, daarna opnieuw promoten.

## 7) Cloud-only check (verplicht voor finalisatie)

1. Verifieer in runtime dat alle calls naar de endpoint gaan op `tradementor-api...run.app`.
2. Verifieer dat Wallet/positions/scanner werken na force-stop zonder lokale server nodig te hebben.
3. Verifieer dat geen instellingen- of debugvenster nog naar een lokale/handmatige gateway-URL verwijst.
4. Pas alleen nieuwe cloudrelease toe als 1,2,3 op minimaal 1 testtoestel stabiel blijven.
