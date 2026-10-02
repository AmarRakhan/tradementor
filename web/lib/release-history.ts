import { WEBAPP_BUILD_NUMBER, WEBAPP_VERSION } from "@/lib/app-version";

// Build 420 release-contract: stable Portfolio Koers overlays, compact strategy cockpit and explicit optional refill.

export type ReleaseConfidence = "confirmed" | "reconstructed";

export type ReleaseHistoryEntry = {
  id: string;
  version: string;
  build: string | null;
  releasedAt: string;
  title: string;
  newItems: string[];
  problems: string[];
  causes: string[];
  fixes: string[];
  now: string[];
  before?: string;
  after?: string;
  technicalDetails?: string[];
  confidence: ReleaseConfidence;
};

export const CURRENT_RELEASE: ReleaseHistoryEntry = {
  id: `v${WEBAPP_VERSION}-build-${WEBAPP_BUILD_NUMBER}-release-history`,
  version: WEBAPP_VERSION,
  build: WEBAPP_BUILD_NUMBER,
  releasedAt: "2026-10-02",
  title: "Portfolio Koers · Actieve Trades 1.0",
  newItems: [
    "Portfolio Koers heeft voor BETA één nieuw derde tabblad: Actieve Trades.",
    "Actieve Trades toont één gecombineerde candlestick-index van alle werkelijk open Aster LONG- en SHORT-posities.",
    "Alleen in dit tabblad verschijnt de nieuwe Actieve Trades Samenvatting met open P&L, daghoog/laag, herstel, LONG/SHORT-bijdrage, aantal trades en totaal notional.",
  ],
  problems: [
    "De bestaande Accountwaarde- en Performance-grafieken lieten niet als één tijdreeks zien hoe het pakket open posities gezamenlijk beweegt.",
    "Nieuwe entries, DCA, partial closes en exits mochten geen kunstmatige sprong veroorzaken in een gecombineerde actieve-trades-index.",
  ],
  causes: [
    "Portfolio Koers beschikte alleen over account-equity OHLC en cashflow-gecorrigeerde performance; er bestond nog geen aparte open-position basket-tijdreeks.",
  ],
  fixes: [
    "Een aparte read-only Active Trades analytics-route gebruikt de canonical exchange-bevestigde open posities als bron.",
    "Alleen ongewijzigde positielegs dragen markt-P&L-delta bij; nieuwe, verwijderde of resized legs worden op het overgangsmoment gerebased.",
    "Historische Actieve-Trades candles worden alleen vanaf echte waarnemingen opgebouwd; ontbrekende historie wordt niet gefingeerd.",
    "De nieuwe release-feature active_trades_chart staat standaard alleen voor BETA aan en voor STABLE uit.",
  ],
  now: [
    "BETA ziet PERFORMANCE | ACCOUNTWAARDE | ACTIEVE TRADES; STABLE behoudt exact de bestaande twee tabs.",
    "Accountwaarde blijft de standaardtab en bestaande Portfolio Koers-berekeningen blijven ongewijzigd.",
  ],
  technicalDetails: [
    "Backend: cloud_api/aster_portfolio_chart.py en /v1/me/aster/portfolio-chart/active-trades.",
    "Frontend: web/components/portfolio-koers-chart.tsx en web/app/portfolio-koers-chart.css.",
    "Release gate: active_trades_chart · beta=true · stable=false.",
    "Geen entry-, DCA-, TP-, hedge-, scanner-, settings- of exchange-submitlogica gewijzigd.",
  ],
  confidence: "confirmed",
};
const HISTORICAL_RELEASES: ReleaseHistoryEntry[] = [
  {
  id: "v46-build-482-performance-detail",
  version: "46",
  build: "482",
  releasedAt: "2026-10-01",
  title: "Rendement Overzicht 1.0 · auditbare dagperformance",
  newItems: [
    "Rendement vandaag en Gemiddeld per dag zijn volledig aanklikbaar en openen dezelfde nieuwe Rendement Overzicht-detailweergave.",
    "De detailweergave heeft Per dag, Analyse, Gemiddeld en Uitleg met aflopende daghistorie, een intraday performancegrafiek en aanklikbare dagdetails.",
    "De backend levert een read-only audit breakdown voor realized PnL, funding, fees, liquidatie/ADL, overige trading adjustments en externe cashflows.",
  ],
  problems: [
    "De bestaande Snapshot-percentages waren zichtbaar, maar de gebruiker kon niet herleiden welke dagwaarden en componenten het getal vormden.",
    "Gemiddeld per dag had geen zichtbare onderbouwing van meetperiode, gemeten dagen of de gebruikte rekenmethode.",
  ],
  causes: [
    "De bestaande daggroei-endpoint berekende de juiste cashflow-gecorrigeerde cijfers, maar de Snapshot las alleen de twee eindpercentages uit.",
    "Historische dagregels en ledgercomponenten waren nog niet als auditinterface aan de frontend ontsloten.",
  ],
  fixes: [
    "De bestaande SAME_DAY_SNAPSHOT_NET_CASHFLOW_ADJUSTED-berekening blijft de source of truth; er is geen tweede rendement-engine toegevoegd.",
    "Externe cashflows blijven geneutraliseerd terwijl REALIZED_PNL, funding, commission en insurance/liquidation-effecten in de performance zichtbaar blijven.",
    "Dagdetails gebruiken opgeslagen betrouwbare dagresultaten en voegen alleen read-only ledgeruitleg toe; wanneer historisch unrealized PnL niet exact bewijsbaar is, wordt dit expliciet als equity-rest getoond.",
    "De nieuwe detailpagina gebruikt een 3D flip-in/flip-out en behoudt de bestaande Portfolio Snapshot-state en scrollpositie.",
  ],
  now: [
    "De gebruiker kan vanaf Rendement vandaag exact naar de daghistorie en opbouw doorklikken.",
    "Gemiddeld per dag toont de meetperiode vanaf trackingstart, gemeten dagen en de exacte rekenkundige-gemiddelde methode van de backend.",
    "Stortingen en opnames staan apart en worden niet als winst of verlies gepresenteerd.",
  ],
  technicalDetails: [
    "Source of truth: cloud_api/main.py::_portfolio_daily_growth en cloud_api/portfolio_growth.py.",
    "Nieuwe read-only detailroute: /v1/me/aster/portfolio-growth/daily-detail.",
    "Frontend: web/components/portfolio-performance-detail.tsx, gekoppeld vanuit aster-portfolio-snapshot-enhancer.tsx.",
    "Intraday grafiek hergebruikt cashflowAdjustedPortfolioSeries uit de bestaande Portfolio Koers-module.",
    "Geen trading-, entry-, DCA-, hedge-, TP-, scanner- of order-submitlogica gewijzigd.",
  ],
  confidence: "confirmed",
},

  {
    id: "v46-build-481-snapshot-visual-polish",
    version: "46",
    build: "481",
  releasedAt: "2026-10-01",
  title: "Portfolio Snapshot · Auto Hedge + Portfolio Cyclus visueel afgewerkt",
  newItems: [
    "Auto Hedge gebruikt een rustigere drie-regelige hiërarchie: label, duidelijke ACTIEF/UIT-status en een beter leesbare triggerregel.",
    "Portfolio Cyclus gebruikt dezelfde compacte visuele ritmiek en toont bij UIT voortaan expliciet 'Geen actieve cyclus'.",
    "Een actieve Portfolio Cyclus toont het percentage boven de voortgangsbalk en het resterende dollarbedrag er direct onder.",
  ],
  problems: [
    "Build 480 was functioneel correct, maar de Auto Hedge-trigger stond nog te klein en te dicht op de overige tekst.",
    "De Portfolio Cyclus-tegel oogde bij UIT te leeg en de twee tegels waren qua padding en verticale ritmiek nog niet in balans.",
  ],
  causes: [
    "De Build 480 typografie was nog te sterk gecomprimeerd voor het smalle mobiele snapshot-grid.",
    "De inactieve Portfolio Cyclus had slechts twee zichtbare tekstregels, waardoor de kaart visueel onaf voelde.",
  ],
  fixes: [
    "Auto Hedge toont nu 'Trigger −US$ X,XX' uit de bestaande opgeslagen thresholdUsd-waarde, zonder extra bediening op de voorkant.",
    "De lettergroottes, regelafstand, icon-size en inner padding van beide tegels zijn opnieuw uitgebalanceerd voor mobiel.",
    "Portfolio Cyclus toont bij UIT een derde regel 'Geen actieve cyclus'; actief blijft progressPercent + voortgangsbalk + remainingUsd gebruiken.",
    "Alle bestaande klik-, dubbelklik-, dubbeltap-, detail-, configuratie- en persistenceflows zijn ongemoeid gelaten.",
  ],
  now: [
    "Auto Hedge is in één oogopslag leesbaar zonder dat de triggerregel wegvalt.",
    "Portfolio Cyclus voelt ook in de UIT-status als een volwaardige statuskaart.",
    "Beide tegels hebben een consistente visuele hiërarchie zonder wijzigingen aan trading- of Portfolio TP-logica.",
  ],
  technicalDetails: [
    "Actuele gebruiker-screenshot: file_00000000ba448210b16f35eaf915a01f.",
    "Auto Hedge UI: web/components/aster-position-loss-auto-hedge-bridge.tsx en web/app/position-loss-auto-hedge.css.",
    "Portfolio Cyclus UI: web/components/aster-profit-pot-snapshot-bridge.tsx en web/app/profit-pot-snapshot.css.",
    "Geen trading-, hedge-, Portfolio TP-, opslag-, API-, state-management-, navigatie- of fliplogica gewijzigd.",
  ],
  confidence: "confirmed",
},

  {
    id: "v46-build-480-portfolio-snapshot-controls",
    version: "46",
    build: "480",
    releasedAt: "2026-10-01",
    title: "Portfolio Snapshot · Auto Hedge + Portfolio Cyclus status",
    newItems: [
      "Auto Hedge toont op de Snapshot-voorkant alleen de actuele status ACTIEF/UIT en de opgeslagen verliestrigger.",
      "Portfolio Cyclus toont het behaalde percentage, een compacte voortgangsbalk en het resterende dollarbedrag tot het huidige Portfolio TP-doel.",
    ],
    problems: [
      "De Auto Hedge-tegel bevatte een dubbele schuifbediening en de Portfolio Cyclus-tegel combineerde te veel configuratie- en statusinformatie.",
    ],
    causes: [
      "Configuratiebediening stond dubbel op de Snapshot-voorkant en in de bestaande detailweergave.",
    ],
    fixes: [
      "De Auto Hedge-schakelaar is van de Snapshot-voorkant verwijderd; de bestaande detailtoggle en persistence bleven intact.",
      "Portfolio Cyclus is teruggebracht tot dynamische voortgang en remainingUsd.",
    ],
    now: [
      "Beide Snapshot-tegels zijn status-only op de voorkant en blijven doorlinken naar hun bestaande instellingen/detailweergaven.",
    ],
    technicalDetails: [
      "Visuele referentie: file_00000000bd588210a3ac396a4df67d6b.",
      "Geen trading-, hedge-, Portfolio TP-, opslag-, API-, state-management- of navigatielogica gewijzigd.",
    ],
    confidence: "confirmed",
  },
  {
    id: "v46-build-479-compact-aster-portfolio-koers",
    version: "46",
    build: "479",
    releasedAt: "2026-10-01",
    title: "ASTER start compacter · Portfolio Koers strakker op zichtbare koers",
    newItems: [
      "De losse strategie-banner boven Portfolio Koers is uit de ASTER-hoofdweergave verwijderd.",
      "Portfolio Koers gebruikt een lagere hoofdgrafiek en een strakkere zichtbare high/low-range.",
    ],
    problems: [
      "De extra strategie-banner nam onnodig verticale ruimte in.",
      "De grafiek liet te veel lege verticale ruimte boven en onder de relevante koers zien.",
    ],
    causes: [
      "De hoofdgrafiekhoogte en autoscale-guides waren nog afgestemd op een ruimere eerdere compositie.",
    ],
    fixes: [
      "De ASTER-strategie-banner is uit de hoofdroute verwijderd en de grafiekhoogte en price-scale margins zijn compacter gemaakt.",
      "Candles, Bollinger Bands, support/resistance, actieve zone, timeframes en tradinglogica zijn behouden.",
    ],
    now: [
      "Portfolio Koers staat directer onder de bovenste balk en Portfolio Snapshot komt eerder in beeld.",
    ],
    technicalDetails: [
      "Gebruikersreferentie: file_000000008f308210972dfd629470e115.",
      "Geen entry-, sizing-, DCA-, TP-, Auto Hedge-, Zone Warriors-, scanner-, opslag- of exchange-submitlogica gewijzigd.",
    ],
    confidence: "confirmed",
  },
  {
    id: "v46-build-478-botconfigurator-exact-artwork",
    version: "46",
    build: "478",
    releasedAt: "2026-09-30",
    title: "Botconfigurator 3.0 · strategie-artwork exact uit referentie",
    newItems: [
      "Zone Warriors gebruikt in de strategiekaart nu een directe clean card-crop uit de goedgekeurde variant 1: frontale groen/gouden Spartaanse helm met de horizontale groen/gouden lichtlijnen.",
      "Classic DCA gebruikt nu de aangeleverde candlestick-compositie met meerdere gouden BUY-munten, BUY-labels en de duidelijke groen gestippelde herstel-/winstpijl.",
    ],
    problems: [
      "De eerdere Build 475/476-correctie gebruikte handmatig nagetekende SVG-interpretaties die zichtbaar bleven afwijken van de aangeleverde referentiebeelden.",
      "Door de generieke vectorinterpretatie waren vooral de Zone Warriors-helm en de Classic DCA candlesticks/BUY-momenten op mobiel onvoldoende herkenbaar.",
    ],
    causes: [
      "De vorige assets waren opnieuw ontworpen in SVG in plaats van rechtstreeks afgeleid van het goedgekeurde bronbeeld.",
      "De strategiekaart gebruikte object-fit cover, waardoor brede artwork bovendien agressiever kon worden afgesneden.",
    ],
    fixes: [
      "Twee nieuwe cache-busted WebP-assets zijn gemaakt als directe crops uit de door de gebruiker aangeleverde referentiebeelden.",
      "Alleen de twee img-bronnen in Botconfigurator 3.0 zijn omgezet naar de nieuwe assets en de afbeeldingsfit is gewijzigd naar contain met gecentreerde positionering.",
      "De bestaande kaartstructuur, selectiegedrag en alle strategie-, configuratie-, opslag-, navigatie- en handelslogica zijn ongewijzigd gebleven.",
      "De eerdere SVG-assets blijven in de repository voor historie maar worden door de twee strategiekaarten niet meer gebruikt.",
    ],
    now: [
      "Zone Warriors is op mobiel direct herkenbaar als de groen/gouden Spartaanse helm uit de referentie.",
      "Classic DCA toont direct de bedoelde candles, gouden BUY-munten en stijgende groene winstpijl zonder generiek vervangend grafiekicoon.",
      "Nieuwe bestandsnamen voorkomen dat bestaande browser- of PWA-cache de oude strategie-artwork blijft tonen.",
    ],
    technicalDetails: [
      "UI: web/components/aster-bot-configurator-v3.tsx.",
      "Zone Warriors asset: web/public/zone-warriors-card-ref1-20260930.webp.",
      "Classic DCA asset: web/public/classic-dca-card-ref8-20260930.webp.",
      "Zone Warriors bronreferentie: file_00000000a75081f4aad2910c0590568b; variant 1.",
      "Classic DCA bronreferentie: file_000000001fc8821086578987f39a0a07; candlesticks + BUY-munten + gestippelde winstpijl.",
      "Oude SVG-assets zone-warriors-icon-ref1.svg en classic-dca-icon-ref10.svg zijn behouden maar niet meer gekoppeld aan de strategiekaarten.",
      "Geen strategieparameters, entry-sizing, DCA, TP, Auto Hedge, Zone Warriors-runtime, opslag, exchange-submit of navigatielogica gewijzigd.",
    ],
    confidence: "confirmed",
  },

  {
    id: "v46-build-477-portfolio-snapshot-details",
    version: "46",
    build: "477",
    releasedAt: "2026-09-30",
    title: "Portfolio Snapshot · Prijszone Details + Scanner Status",
    newItems: [
      "De normale Portfolio Snapshot toont direct onder de header twee compacte detailknoppen: Prijszone Details en Scanner Status.",
      "Het grote Prijszone-strategieblok is uit de standaardweergave gehaald en opent voortaan als zelfstandige detailweergave.",
      "Scanner Status toont per LONG en SHORT de live timeframe, laatste scan, gescande markten, Bollinger-kandidaten, zonepassage, blockers, orders, laatste entry en vrije capaciteit.",
      "De scannerdiagnostiek geeft uitsluitend op basis van runtime-feiten één status: NORMAAL, GEEN KANDIDATEN, GEBLOKKEERD, SCANNER STIL of ORDERFOUT.",
    ],
    problems: [
      "De prijszonesamenvatting nam veel verticale ruimte in op het hoofdscherm terwijl dezelfde informatie vooral nodig is voor diagnose.",
      "Bij langere perioden zonder nieuwe entries was niet direct zichtbaar of er werkelijk geen kandidaten waren of dat een latere filter, capaciteit of scannerstatus de entry tegenhield.",
    ],
    causes: [
      "De Portfolio Snapshot combineerde kerncijfers en uitgebreide strategie-uitleg in één permanente kaart.",
      "De Multi-BB runtime publiceerde nog geen compacte per-richting observability-counters voor de entrypipeline.",
    ],
    fixes: [