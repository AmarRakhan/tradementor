# Harde afspraken (TradeMentor)

Laatste update: 2026-08-07

## Bevestigde terugvalversie

- Laatst door de gebruiker bevestigde goede testversie: **2.51 build 220**.
- Vast APK-bestand: `C:\HyperEdge\Android\TradeMentor\APK Releases\TradeMentor-Test-v2.51-build220.apk`.
- Nieuwe builds vervangen dit bestand niet en krijgen altijd een hoger buildnummer.
- Bij regressies vergelijken we eerst met build 220; terugzetten mag zonder deze APK opnieuw te bouwen.

## 1) Map / bron voor waarheid

- Het vaste projectpad is:
  - `C:\HyperEdge\Android\TradeMentor`
- Alle bronbestanden, scripts, changelogs en build-opdrachten horen hier te staan.
- Geen ontwikkelstappen meer uitvoeren vanuit OneDrive of andere spiegels.

## 2) Buildregels (ononderhandelbaar)

- Er is **één interne testversie** (`test`) en **één publieke versie** (`main`).
- Verdelen:
  - `main` = publieke/stabiele versie.
  - `test` = interne testversie met nieuwe instellingen/strategieën.
- Per buildronde leveren we twee APK's:
  1. Admin APK
  2. Test APK
- Voor de test/verspreiding gebruiken we **geen onverwachte extra artifact-varianten**.
- De Test APK **moet uit de staging-build komen**:
  - voorkeur: `app\build\outputs\apk\public\staging\app-public-staging.apk`
  - fallback naar andere artifactpad alleen wanneer expliciet overeengekomen.

## 3) APK-locatie

- Primaire opslag: `C:\HyperEdge\Android\TradeMentor\APK Releases`
- Voor snelle distributie ook behouden we:
  - `C:\HyperEdge\Android\TradeMentor\build\output-artifacts` (alleen als tijdelijk cachepad).
- Oude/ongeldige APK's verwijderen uit test- en testtelefoon vóór een nieuwe testronde.

## 4) Versie-log

- Na elke build noteren we:
  - versie en build
  - welke bestanden exact zijn gebouwd
  - korte wijzigingsregel
  - datum/tijd (UTC+2)
- Deze lijst staat in:
  - `CHANGELOG.md` (als dit nog niet bestaat, maak het aan met direct 1-op-1 entries per build)

## 5) Werkwijze met debug output

- Als een buildscript tijdelijk fallbackt naar `app-public-debug.apk` zonder akkoord:
  - dat is niet akkoord.
  - dat gedrag blokkeren en expliciet stoppen met een duidelijke foutmelding.

## 6) Volgende afspraak

- Als de gebruiker “geen debug nodig” aangeeft:
  - we bouwen en publiceren alleen via dit pad en de afspraken hierboven.
  - we laten de gebruiker alleen APKs in de officiële map zien.

## 7) Financiële bronwaarheid Aster

- Voor actuele Aster-posities, prijzen, PnL, margin, orders en fills is de Aster API leidend.
- Rechtstreekse waarden worden zichtbaar als `Aster` gemarkeerd.
- Samenvoegingen van officiële Aster-velden worden als `Som Aster` gemarkeerd en hebben een vastgelegde formule.
- Eigen TradeMentor-berekeningen worden zichtbaar als `Berekend` gemarkeerd en tonen hun formule.
- Ontbrekende of onbetrouwbare financiële data wordt als `—` getoond en nooit stilzwijgend als nul.
- Het positiepercentage `unRealizedProfit / mark-notional` is uitsluitend een bruto UI-indicatie en is nadrukkelijk geen netto TP-status.
- TP-beslissingen blijven server-side en gebruiken de strategy-engine, fees, funding, verwachte sluitkosten, protection en bewezen exchange-state.
- Active Trade Capital voor Aster is uitsluitend `sum(positionInitialMargin)` van actieve Aster-posities. Er is geen browserfallback via notional/leverage toegestaan.
- Een nieuwe afgeleide financiële waarde vereist eerst een centrale definitie, formule en regressietest.