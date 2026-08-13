# GitHub & Cloud Migration Playbook

Deze handleiding zet je stap voor stap naar een gedeelde, cloud-gestuurde werkwijze.

## 1) Lokaal project klaarzetten voor GitHub

- Controleer dat je `.gitignore` geheimen uitsluit
- Voeg dit toe als je dat nog mist:
  - keystores
  - `local.properties`
  - `trading_server/.env`
  - `trading_server/*.secret`

## 2) Repository opzetten

```powershell
git init
git add .
git commit -m "chore: project baseline"
git branch -M main
git remote add origin https://github.com/<gebruikersnaam>/<repo>.git
git push -u origin main
```

## 3) Omgebouwde releases-flow

1. Werk in `develop` of `test` branch
2. Testfunctie lokaal + op je testtoestel
3. Merge/PR naar `main` als stabiel
4. Build release APK + publiceer versie + changelog

## 4) Cloud migratie in code

- Verwijder lokaal hardcoded endpoints
- Lees API base URL en publieke instellingen uit cloud-config
- Gebruik een klein `ConfigService`-laagje:
  - `Trading config` (scan interval, active trades, min order)
  - `Security config` (wallet lock, dry-run)
  - `Feature flags` (testmodus, auto-scan, geluiden, enz.)

## 5) Waarom cloud nu beter

- Consistente berekeningen op alle toestellen
- Eén bron van waarheid voor instellingen
- Minder afhankelijkheid van losse lokale server
- Herstart/updates buiten toestelomgevingen

## 6) Release/ops checklist

- [ ] API endpoints getest op meerdere toestellen
- [ ] App connectie: groen (account secure, wallet connected)
- [ ] Scan & buy gedrag identiek op testtelefonen
- [ ] Logboek en takenlijst zichtbaar in versiecontrole
- [ ] Backup van `APK Releases` met tag en buildnummer

## 7) Noodprocedure

Als een toestel afwijkend gedrag toont:
- noteer toestelmodel + Android versie
- zet logs van scan-loop aan
- vergelijk met andere toestellen op exact zelfde build en config
- rol terug naar laatste publieke build indien nodig

