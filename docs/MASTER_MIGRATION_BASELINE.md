# TradeMentor master migration baseline

Vastgelegd op: 2026-08-08 (Europe/Amsterdam)

## Bron van waarheid

- Werkmap: `C:\HyperEdge\Android\TradeMentor`
- Git branch: `main`
- Laatste vastgelegde commit bij start: `ca41b6e`
- De werkmap bevat veel bestaande, nog niet vastgelegde wijzigingen. Deze zijn gebruikerswerk en worden niet gereset, opgeschoond of overschreven.
- Laatst beschikbare testbasis: versie `2.65-test`, build `234`.
- Test-APK: `APK Releases\TradeMentor-Test-v2.65-build234.apk`.
- Admin-APK: `APK Releases\TradeMentor-Admin-v2.65-build234.apk`.
- Bevestigde historische terugval-APK blijft versie `2.51`, build `220`, zoals vastgelegd in `docs\HARD_AGREEMENTS.md`.

## Nulmeting

- Android/JVM: 45 tests geslaagd, 0 mislukt.
- Cloud/Python: 77 tests geslaagd, 0 mislukt.
- Totaal: 122 tests geslaagd.
- Android compilatie is geslaagd met de Kotlin-compiler in-process en tijdelijke bestanden binnen de projectmap.

## Huidige architectuur

- Android-app: Kotlin, Jetpack Compose, Firebase Authentication, Firestore, WorkManager en Reown AppKit.
- Cloud API: Python/FastAPI op Google Cloud Run.
- Ingebouwde cloudendpoint: `https://tradementor-api-604335232956.europe-west4.run.app`.
- MEXC: cloudclient, credential vault, live/accountinspectie, automatisering en Hedge DCA V3.
- Hyperliquid: wallet/accountkoppeling, cloudgateway, live positions, scanner, DCA-cyclestore en orderveiligheid.
- Lokale app-state: meerdere benoemde SharedPreferences-stores voor navigatie, strategie, scanner, handelscyclus en beveiliging.
- Cloud-state: Firebase/Firestore-documenten voor gebruikers-, execution- en automatiseringsstate plus Google Secret Manager voor geheime koppelingen.

## Live-stategrens

- Geen app-installatie, schemawijziging of migratie mag bestaande Hyperliquid-posities, open orders, DCA-levels, cycles, instellingen of betrouwbare enabled-status resetten.
- Geen Aster-bot mag door alleen installatie of pagina-open starten.
- Een exacte pre-installatiesnapshot van live positions, orders, fills, instellingen en cycle-state moet vlak voor een toekomstige upgrade via geauthenticeerde read-only endpoints worden vastgelegd. Deze momentopname wordt niet uit oude screenshots afgeleid.
- Exchange-state is leidend bij reconciliation. Ontbrekende of tegenstrijdige lokale state blokkeert nieuwe risk-increasing orders.

## Bekende kritieke bevinding bij aanvang

- MEXC Hedge DCA V3 reconstrueerde na een expliciete stop een handmatig gesloten ontbrekende side opnieuw.
- Dit gedrag is op 2026-08-08 live waargenomen: na handmatig sluiten van de Short verscheen opnieuw een Short en ging MEXC terug van één naar twee BTCUSDT-posities.
- De lokale bron bevat nu een fail-safe stopguard en drie regressietests:
  - geen `OPEN_SIDE`, `ADD_DCA`, `EMERGENCY_HEDGE` of `OPEN_RESCUE` in protective-only;
  - risk-reducing acties blijven beschikbaar;
  - monitoring stopt pas wanneer positions en orders exchange-bevestigd vlak zijn.
- Deze fix is nog niet naar productiecloud gepubliceerd. Publicatie vereist een afzonderlijke deployment-, simulatie- en regressiegate.

## Eerste navigatiemigratie

- De bron bevat exact vier hoofdtabdefinities: MEXC, HYPERLIQUID, ASTER en WALLET.
- Hyperliquid blijft in de Compose-tree gemount om bestaand polling/cachegedrag bij tabwissels te behouden.
- Strategy is bereikbaar via `DCA STRATEGY SETTINGS` onder Hyperliquid. Alleen openen verandert geen botstate.
- Aster is in deze fase een veilige, read-only bestemming met botstatus UIT en zonder ordermogelijkheid.
- Oude scherm- en servicecode is niet destructief verwijderd; dependency-analyse volgt vóór eventuele cleanup.

## Hyperliquid migration guard

- De bron bevat nu een pure, side-effectvrije snapshot- en reconciliationlaag.
- Hyperliquid/exchange-state is altijd leidend voor posities en open orders.
- Een ontbrekende exchange-read pauzeert de migratie; oude app- of cloudstate wordt dan nooit als handelswaarheid gebruikt.
- Een verschil met lokale of cloudstate levert `SYNC_REQUIRED` op en blokkeert alle risk-increasing acties.
- Hervatten mag pas nadat de exchange-authoritatieve reparatie persistent is opgeslagen en exact is teruggelezen.
- Een ontbrekende of tegenstrijdige enabled-status schakelt de bot niet stilzwijgend in, maar houdt deze veilig UIT.

## Aster Futures V3 fundament

- Officiële bron: [Aster API Docs](https://github.com/asterdex/api-docs) en de actuele [Futures API V3-specificatie](https://github.com/asterdex/api-docs/blob/master/V3%28Recommended%29/EN/aster-finance-futures-api-v3.md).
- Officiële Hedge Mode-uitleg: [Aster Hedge Mode](https://docs.asterdex.com/trading/perpetuals/hedge-mode).
- Nieuwe Aster-automatisering staat standaard `OFF` en in `paper`.
- De koppeling is gebaseerd op de officiële Aster Futures API V3; V1 is legacy en wordt niet gebruikt voor nieuw werk.
- Hedge Mode moet accountbreed door Aster zijn bevestigd voordat een orderpayload kan ontstaan.
- Iedere Hedge Mode-order krijgt expliciet `positionSide=LONG` of `positionSide=SHORT`; `BOTH` is uitgesloten.
- In Hedge Mode wordt `reduceOnly` niet verzonden, conform de officiële V3-regels. Sluiten wordt ondubbelzinnig bepaald door orderrichting plus `positionSide`.
- Hoeveelheid, minimale orderwaarde en maximale leverage worden uit actuele exchangefilters/brackets afgeleid en naar beneden afgerond.
- HTTP 503 betekent een onbekende uitvoeringsstatus en mag nooit leiden tot blind opnieuw bestellen.
- User-streamgebeurtenissen worden op exchange-eventtijd geordend omdat Aster aangeeft dat ze uit volgorde kunnen aankomen.
- Dit fundament maakt nog geen echte verbinding, bewaart geen credentials en kan geen order verzenden.
- Multi-pair state bewaart Long en Short per contract als onafhankelijke legs, verwijdert geen state bij een mislukte exchange-read en accepteert geen oudere WebSocket-eventtijd.
- Een nieuw ontdekte of gewijzigde actieve Aster-positie blokkeert nieuwe exposure totdat zowel de persistente round-trip als de fill/DCA-reconstructie is bewezen.

## Centrale handelsveiligheid

- De Portfolio Risk Manager beoordeelt nieuwe exposure over MEXC, Hyperliquid en Aster samen.
- Nieuwe exposure faalt dicht bij ontbrekende/stale data, te kleine liquidatieafstand, te hoge marginratio, onvoldoende noodreserve, te grote totale exposure, exchangeconcentratie of de dagelijkse drawdown-circuit-breaker.
- De Order Coordinator vereist een gereed adapter, geslaagde reconciliation, betrouwbare enabled-status en riskgoedkeuring voordat `OPEN`, `ADD` of `HEDGE` kan doorgaan.
- `CLOSE` en `CANCEL` blijven mogelijk wanneer automatisering of het risicobudget UIT staat, mits exchange-state betrouwbaar is.
- Een reeds geaccepteerde/gevulde intentie wordt teruggespeeld en nooit dubbel verstuurd. Een onzekere intentie blijft geblokkeerd tot exchange-reconciliation.

## Market Selector, Wallet en startup

- De CoinMarketCap-selectielaag ondersteunt ieder ingesteld top-N-getal binnen 1–500 en faalt dicht wanneer minder dan 90% van de gevraagde ranglijst beschikbaar is.
- Kandidaten worden alleen toegelaten als het contract werkelijk actief is op de betreffende exchange en worden op absolute 24-uursbeweging gerangschikt.
- De selector geeft nooit zelfstandig ordertoestemming, leverage of richting; dat blijft de verantwoordelijkheid van strategie en risk manager.
- Wallet-aggregatie telt exchange-equity op zonder unrealized PnL dubbel bij te tellen en noemt een totaal expliciet voorlopig wanneer een exchange ontbreekt of stale is.
- Startup herstelt een betrouwbare enabled-status pas na read, reconciliation en realtime stream. Een nieuwe/onbekende Aster-configuratie blijft altijd UIT.
- Herverbinden gebruikt begrensde exponential backoff; er ontstaan geen snelle oneindige retrylussen.

## Blokkerende gates vóór een APK of cloudpublicatie

1. Android- en cloudregressie blijven volledig groen.
2. MEXC-stopgedrag wordt met een geïsoleerde cloudintegratietest bewezen.
3. Hyperliquid pre-migratiesnapshot en reconciliation-contract zijn geïmplementeerd en getest.
4. Navigatie wordt op een toestel gecontroleerd zonder live tradingacties.
5. Nieuwe Aster-code blijft standaard OFF en fail-safe totdat officiële API-, Hedge Mode-, risk- en recoverygates slagen.
