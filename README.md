# TradeMentor Android Project

## Status

- Android app and trading UI in this repository
- Trading server and cloud services are in the sibling folders `trading_server` and `cloud`
- We are running in an active development environment with cloud-linked trading configuration

## Doel van dit project

Deze repository bevat de code voor een mobiele trading scanner/app met:

- Wallet-koppeling
- Live positions
- Signal/scan-engine
- Strategieën (incl. Quantum Shield)
- Risk dashboard
- Cloud-gedreven configuratie (Firebase / Google Cloud)

## Snelle start (lokale werking)

1. Open Android Studio
2. Sync Gradle
3. Bouw en run op je toestel
4. Voor lokale tests: stel `local.properties` niet in versiecontrole (is al uitgesloten)

## Van lokaal project naar GitHub

### 1) Initialiseer git

```powershell
git init
git add .
git commit -m "chore: initial commit for trade mentor project"
```

### 2) Maak een GitHub-repo en koppel deze

```powershell
git branch -M main
git remote add origin https://github.com/<jouw-gebruikersnaam>/<jouw-repo>.git
git push -u origin main
```

### 3) Branchbeleid

- `main`: stabiele publieke versie
- `test` (of `develop`): testversies voor validatie
- feature branches: `feat/*`, `fix/*` en kleine scope

### 4) Veiligheid

- Houd sleutels en secrets uit de repo (al in `.gitignore`)
- Gebruik GitHub Secrets voor alle gevoelige waarden
- Voor app-builds: ondertekening + keystore buiten versiebeheer

## Cloud-migratie: lokaal naar cloud

### Checklist

1. Zet `baseUrl` / websocket / API endpoint in één centrale config
2. Gebruik environment-variabelen of runtime-config (niet hardcoded in code)
3. Controleer dat Firebase/Cloud keys niet in debug-logs staan
4. Bouw release en publiceer APK onder een eenduidig buildnummer
5. Houd lokale cache/logs als “niet build relevant”

## Aanbevolen mappenstructuur

- `app/` Android app broncode
- `trading_server/` server-code voor cloudtrading
- `cloud/` scripts/integraties naar cloudservices
- `docs/` strategie- en architectuurdocs
- `APK Releases/` lokaal gegenereerde build-artifacts

## Belangrijk voor samenwerking

- Elke release-actie loggen in `docs/CHANGELOG.md` of een release-notitie
- Verwerk migraties in kleine PR’s (één wijziging per wijziging)
- Gebruik duidelijke tags: `v2.xx` met bijbehorend buildnummer

- Harde afspraken staan vast in docs/HARD_AGREEMENTS.md
