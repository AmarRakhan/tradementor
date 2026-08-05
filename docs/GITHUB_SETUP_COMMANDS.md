# GitHub-koppelingscommando's

Gebruik deze volgorde op je eigen pc in `C:\HyperEdge\Android\TradeMentor`.

## 1) GitHub-repo maken
- Maak op GitHub een lege repo aan: `tradementor` (publiek of privé)

## 2) Lokaal koppelen

```powershell
git config --global --add safe.directory C:/HyperEdge/Android/TradeMentor
git remote add origin https://github.com/<jouw-gebruikersnaam>/tradementor.git
git checkout -b main
```

> Als je met je eigen Windows-gebruiker werkt kan "dubious ownership" verschijnen; bovenstaande safe.directory-regel voorkomt dat.

## 3) Eerste baseline commit (geen lokale runtime-data)

```powershell
git add README.md docs .github app build.gradle.kts settings.gradle.kts gradle* gradlew* gradle.properties cloud trading_server
git commit -m "chore: baseline trade mentor cloud-first setup"
git push -u origin main
```

### Als er veel oude debug-bestanden zijn

```powershell
git rm -r --cached .android .android-signing-home .android-user-home .gradle-user .gradle-user-home .codex-tools .tmp* 2>$null
git add README.md docs .github app build.gradle.kts settings.gradle.kts gradle* gradlew* gradle.properties cloud trading_server
git commit -m "chore: clean git history before cloud push"
```

## 4) Test/public branch structuur

Gebruik deze lokale structuur:
- `main` = publieke stabiele versie
- `test` = interne testversie

```powershell
git checkout -b test
git push -u origin test
```

Uit test naar main:

```powershell
git checkout main
git merge --no-ff test -m "chore: release from test"
git push origin main
```

### Belangrijk: wat is “publiceren” in deze context

- `main` = release-kanaal (APK voor gebruikers/installaties).
- “Publiceren” = build + uitrollen van een APK/store-versie.
- “Code delen” = alleen wanneer jij expliciet de broncode in de repo deelt (bijv. via publieke repo of directe toegang).
- Hou de repo op GitHub privé, dan kan niemand de broncode inzien.

## 5) Veiligheid check

```powershell
git status --ignored
```

Als iets per ongeluk zichtbaar blijft in `git status`, voeg dan toe aan `.gitignore` en commit opnieuw.

```powershell
echo "foldernaam/" >> .gitignore
git add .gitignore
git commit -m "chore: keep local runtime artifacts out of git"
```

## 6) Nieuwe versie op telefoon installeren (ook vanuit cloud-setup)

1. Haal `test` of `main` APK (debug/release) op je telefoon:
   - Test build: via Android Studio Run / lokale `APK Releases` map
   - Release build: via jouw release kanaal
2. Installeer in instellingen op apparaat:
   - `Instellingen` → `Beveiliging` → `Onbekende bronnen` indien nodig
   - Installeren als bestaande TradeMentor-versie aanwezig is
3. Open app en controleer:
   - Login scherm blijft werken
   - Wallet/statuspictogram wordt groen/verbonden
   - Cloud-status en settings laden uit backend
4. Bij upgrade:
   - Gebruik dezelfde package naam
   - Gebruik dezelfde signing-keystore
   - Daarna direct `App > Refresh` om backend-data opnieuw te laden
5. Als de app niet herkent dat hij cloud draait:
   - Force stop app
   - Wi-Fi/cel-data aan
   - Opnieuw openen en 1x terug naar `Wallet`/`Live Positions`

Tip: op eerste start na cloudmigratie geen oude lokale serverdata meer gebruiken als fallback; laat de app eerst cloudstatus valideren.

## 7) Release tagging (aanbevolen)

Gebruik tags per versie, zodat je altijd terug kunt naar een werkende staat:

```powershell
# test-versie taggen
git checkout test
git tag test-v2.40.1
git push origin test-v2.40.1

# publieke versie taggen
git checkout main
git merge --no-ff test -m "chore: release to main"
git tag v2.40.1
git push origin main --tags
```

## 8) Als een toestel anders gedrag geeft (snelle diagnoselijst)

- Check versie op toestel = verwacht tag of buildcode
- Check of er één installatiemethode is gebruikt (APK same package, same keystore)
- Force stop en clear cache (niet clear data)
- Verifieer cloud-endpoint binnen scherminstellingen
- Verifieer app toestemming voor achtergrondtasks (battery optimization)
- Check of signal/scan knoppen niet op handmatige lock staat

Als testtelefoon en fold verschillen:
- vergelijk op exact dezelfde APK (zelfde hash)
- vergelijk instellingen op beide toestellen
- alleen verschil mag toestel-specifiek zijn (Android-versie, batterijbeheer)

Zie ook het volledige releasepad:
- [docs/DEPLOYMENT_RUNBOOK.md](/C:/HyperEdge/Android/TradeMentor/docs/DEPLOYMENT_RUNBOOK.md)
