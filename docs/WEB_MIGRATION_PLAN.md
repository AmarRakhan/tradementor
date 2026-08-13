# TradeMentor webmigratie

## Besluit

TradeMentor wordt web-first. De bestaande Android-app blijft voorlopig ongewijzigd beschikbaar als terugvalpunt, maar nieuwe productontwikkeling verhuist stapsgewijs naar een responsieve webomgeving voor telefoon, tablet en desktop.

## Eerste webversie

De eerste veilige webbasis bevat vier vaste bestemmingen:

1. MEXC
2. Hyperliquid
3. Aster
4. Wallet

De interface toont ontbrekende gegevens als onbekend en nooit als een aangenomen nulbedrag. Orderknoppen en nieuwe exposure blijven uit totdat authenticatie, exchange-reconciliatie, herstelgedrag en de centrale risicocontrole zijn aangesloten en getest.

## Migratievolgorde

1. Responsieve navigatie en visuele basis.
2. Persoonlijke aanmelding en afgeschermde gebruikerssessie.
3. Alleen-lezen wallet-, positie- en verbindingsstatus uit de bestaande cloud.
4. Exchange-truth reconciliatie en browserherstel.
5. Beschermende acties en sluitroutes.
6. Nieuwe orders uitsluitend via de centrale riskgate en ordercoördinator.
7. Mobiele browser-, desktop- en hersteltests.
8. Afgeschermde testpublicatie vóór publieke uitrol.

## Premium-abonnement

De webversie krijgt een Free- en Premium-laag. De eerste interface toont dit uitsluitend als voorstel; prijs, voorwaarden en echte betaling blijven uit tot expliciete goedkeuring.

De geplande betaalstroom is servergestuurd:

1. Een ingelogde gebruiker kiest Premium.
2. De server maakt een betaalpagina aan en koppelt die aan de persoonlijke gebruikers-id.
3. Alleen een geldig ondertekend betaalbericht mag de abonnementsstatus veranderen.
4. De server bewaart de actuele status en bepaalt bij iedere beschermde functie opnieuw de rechten.
5. De gebruiker kan facturen, betaalmethode en opzegging via een beveiligd klantenportaal beheren.

Geheime betaalgegevens en exchange-sleutels komen nooit in de browsercode terecht.

## Veiligheidsregels

- Geen API-geheimen in de browser of broncode.
- Geen live orderroute rechtstreeks vanuit de interface.
- De server controleert identiteit, risico, idempotentie en actuele exchange-state.
- Bij ontbrekende of tegenstrijdige data wordt nieuwe exposure geblokkeerd.
- Bestaande posities mogen nooit als verdwenen worden behandeld door een lege browsercache.
