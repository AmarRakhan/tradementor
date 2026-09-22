import { WEBAPP_BUILD_NUMBER, WEBAPP_VERSION } from "@/lib/app-version";

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
  releasedAt: "2026-09-22",
  title: "Portfolio Koers live boven Portfolio Snapshot",
  newItems: [
    "Nieuwe compacte Portfolio Koers-kaart direct boven de bestaande Portfolio Snapshot, zonder die Snapshot opnieuw te ontwerpen.",
    "Echte portfolio-equity als OHLC-candles met 1m, 5m, 15m, 1u, 4u en 24u timeframes.",
    "Bollinger Bands 20,2, dynamische Zone 0/±N op bevestigde swing/S&R + ATR, Entry L/S-, TP- en aparte transfermarkers.",
    "Fullscreen, horizontaal/verticaal navigeren, pinch/zoom en OHLC-tooltip op mobiel en desktop.",
  ],
  problems: [
    "Portfolioverloop was niet als persistente, analyseerbare koersgrafiek direct bij het portfolio-overzicht zichtbaar.",
    "Browser-only historie kon na apparaat- of sessiewissel verdwijnen en mocht niet als serverwaarheid worden gebruikt.",
  ],
  causes: [
    "De bestaande portfoliografiek bouwde historie alleen lokaal op; er was nog geen account-scoped serverpersistente Portfolio Koers-dataset.",
  ],
  fixes: [
    "De kaart leest uitsluitend serverbevestigde Aster-equityhistorie en vult de lopende candle aan met de al zichtbare live equity uit de bestaande app.",
    "Externe transfers worden apart gelabeld en niet als Entry/TP-marker gepresenteerd.",
    "Zones gebruiken geen vaste dollargrid en geen volume; ze ontstaan uitsluitend uit bevestigde swings, S/R-clustering en ATR.",
    "De backend chart-route is read-only voor trading: ordersSent blijft 0 en er is geen open/close/DCA/hedge-pad toegevoegd.",
  ],
  now: [
    "De grafiek staat vóór Portfolio Snapshot en laat de bestaande Snapshot, actieve posities en tradinginstellingen ongemoeid.",
    "Nieuwe historische candles worden persistent opgebouwd uit echte accountmetingen; ontbrekende oude candles worden niet verzonnen.",
    "De 15m-weergave is standaard en alle zes goedgekeurde timeframes zijn rechtstreeks selecteerbaar.",
  ],
  before: "Portfolio Snapshot had geen persistente live OHLC-kaart met zones, Bollinger en trade-/balansmarkers erboven.",
  after: "Portfolio Koers staat erboven als aparte read-only analysemodule terwijl Portfolio Snapshot zelf ongewijzigd blijft.",
  technicalDetails: [
    "Frontend: web/components/portfolio-koers-chart.tsx + portfolio-koers-chart.css + pure regressiehelpers.",
    "Backend: account-scoped Firestore OHLC-buckets per timeframe en /v1/me/aster/portfolio-chart.",
    "Geen Strategy-2 scanner-, leverage-, DCA-, hedge-, TP- of order-executionlogica gewijzigd.",
  ],
  confidence: "confirmed",
};

const HISTORICAL_RELEASES: ReleaseHistoryEntry[] = [
  {
    id: `v${WEBAPP_VERSION}-build-${WEBAPP_BUILD_NUMBER}-release-history`,
    version: WEBAPP_VERSION,
    build: WEBAPP_BUILD_NUMBER,
    releasedAt: "2026-09-21",
    title: "LONG en SHORT-stoelen onafhankelijk instelbaar",
    newItems: [
      "LONG slots en SHORT slots kunnen nu ieder rechtstreeks worden verhoogd of verlaagd zonder eerst Totaal posities aan te passen.",
      "Totaal posities wordt automatisch opnieuw berekend als de som van de twee zijden.",
    ],
    problems: [
      "Wie bijvoorbeeld van 35 naar 45 LONG-stoelen wilde, moest eerst het totaal verhogen en daarna opnieuw onthouden en instellen hoeveel SHORT-stoelen moesten blijven staan.",
      "Een wijziging aan één zijde veranderde voorheen impliciet de andere zijde omdat het totaal als vaste waarde werd behandeld.",
    ],
    causes: [
      "De slot-helper hield Totaal posities vast en berekende de tegenoverliggende zijde als restwaarde.",
    ],
    fixes: [
      "Bij een LONG-wijziging blijft het actuele aantal SHORT-stoelen exact staan en volgt Totaal posities automatisch LONG + SHORT.",
      "Bij een SHORT-wijziging blijft het actuele aantal LONG-stoelen exact staan en volgt Totaal posities automatisch LONG + SHORT.",
      "De bestaande harde limiet van 100 totale posities blijft behouden; alleen de gewijzigde zijde wordt zo nodig begrensd.",
      "Regressietests bewaken zowel de rekenregel als de koppeling in Botinstellingen, inclusief de bestaande blur/commit-flow.",
    ],
    now: [
      "35 LONG + 30 SHORT → LONG naar 45 geeft direct 45 LONG + 30 SHORT = 75 totaal.",
      "45 LONG + 30 SHORT → SHORT naar 20 geeft direct 45 LONG + 20 SHORT = 65 totaal.",
      "De gebruiker hoeft de niet-aangepaste zijde niet meer opnieuw in te voeren of te onthouden.",
    ],
    before: "LONG of SHORT wijzigen hield het totaal vast en schoof daardoor automatisch de andere zijde mee.",
    after: "LONG en SHORT zijn onafhankelijke invoervelden; alleen het gewijzigde veld verandert en het totaal volgt automatisch.",
    technicalDetails: [
      "Aangepast in web/components/aster-strategy2-maker.tsx, web/lib/position-slot-input.ts en de bijbehorende regressiecontracten.",
      "Geen scanner-, Bollinger-, leverage-, DCA-, TP-, order- of exchange-executionlogica gewijzigd.",
      "Bestaande opgeslagen LONG/SHORT-instellingen en actieve posities worden niet automatisch gewijzigd door deze release.",
    ],
    confidence: "confirmed",
  },
  {
    id: "v46-build-390-sizing-isolation",
    version: "46",
    build: "390",
    releasedAt: "2026-09-21",
    title: "Strategy-2 sizingmodus beschermd tegen oude UI-state",
    newItems: [
      "Botinstellingen vergelijken bevestigde UI-state voortaan met de nieuwste server-configVersion voordat instellingen opnieuw worden geladen.",
      "Opslaan en Starten lezen vlak vóór verzending de actuele serverinstellingen en bewaren de server-side positieomvangmodus tenzij de gebruiker de schakelaar Vaste positieomvang expliciet heeft gewijzigd.",
    ],
    problems: [
      "Een eerder bevestigde browserstate kon nieuwer serverherstel blijven overschrijven en daardoor entrySizingMode opnieuw op notional zetten.",
      "Bij Top-350 en vrije LONG-stoelen kon dit geldige 1m Bollinger-kandidaten alsnog blokkeren doordat een kleine vaste notional tegen de minimale Aster-order botste.",
    ],
    causes: [
      "strategy2ServerStatus gaf iedere lokale confirmedState onbeperkt voorrang, ook wanneer de server inmiddels een hogere configVersion had.",
      "De Botinstellingen stuurden entrySizingMode bij iedere gewone save/start opnieuw mee vanuit die mogelijk verouderde schakelaarstate.",
    ],
    fixes: [
      "Een server-snapshot met een hogere configVersion vervangt nu automatisch een oudere confirmedState.",
      "De positieomvangmodus wordt bij save/start tegen een no-store server-snapshot gereconcilieerd; alleen een expliciete interactie met Vaste positieomvang mag margin/notional wijzigen.",
      "Nieuwe regressietests bewaken zowel server-versiefreshness als isolatie van de sizingmodus bij overige instellingen.",
    ],
    now: [
      "Wijzigingen aan slots, Top-N, Portfolio TP, Bollinger-timeframe of andere Botinstellingen kunnen een gerepareerde marginmodus niet meer stil terugzetten naar notional.",
      "De schakelaar Vaste positieomvang blijft wel volledig bruikbaar wanneer de gebruiker hem bewust zelf aan- of uitzet.",
      "Deze release verandert geen bestaande positie, order, DCA-state of actuele accountinstelling automatisch.",
    ],
    before: "Een stale browser-confirmatie kon een nieuwere serverconfig negeren en later opnieuw als notional opslaan.",
    after: "De nieuwste serverconfig is leidend en sizing verandert alleen na een expliciete gebruikeractie op de sizing-schakelaar.",
    technicalDetails: [
      "Aangepast in web/lib/aster-strategy2-server-status.mjs en web/components/aster-strategy2-maker.tsx.",
      "De publieke Aster-controle vond tijdens diagnose 44 actuele LONG-signalen binnen Top-350 op 1m; de marktvoorwaarde zelf was dus niet de primaire blokkade.",
      "Geen backend tradingformule, Bollingerberekening, leverage-resolver of order-executionpad is door deze webrelease aangepast.",
      "Build 390 behoudt bestaande Profit Lock- en Sniper-historiecontracten; de Sniper-regressietest valideert voortaan toekomstvast in plaats van één hardcoded buildnummer.",
    ],
    confidence: "confirmed",
  },

  {
    id: "v46-build-389-portfolio-tp-additive",
    version: "46",
    build: "389",
    releasedAt: "2026-09-21",
    title: "Portfolio TP behoudt per-trade Take Profit",
    newItems: [
      "Portfolio Take Profit werkt nu aanvullend op de bestaande LONG/SHORT Take Profit per positie.",
      "De portfolio-doelwaarde sluit nog steeds alle posities zodra het portfoliodoel wordt bereikt.",
    ],
    problems: [
      "Wanneer Take Profit op Portfolio stond, werd de normale pair-level Take Profit volledig uitgeschakeld.",
      "Daardoor konden winstgevende individuele LONG/SHORT-posities hun eigen ingestelde TP passeren zonder automatisch te sluiten.",
    ],
    causes: [
      "De webapp schreef takeProfitEnabled=false zodra de modus niet PER_TRADE was.",
      "De Multi BB runtime en de portfolio-orderguard behandelden PORTFOLIO ten onrechte als een exclusieve TP-modus en blokkeerden individuele mbb-tp closes.",
    ],
    fixes: [
      "PORTFOLIO houdt takeProfitEnabled nu actief; alleen OFF schakelt individuele TP uit.",
      "De pair-aware runtime blijft in PORTFOLIO mode de LONG/SHORT TP-waarden toepassen.",
      "De last-millisecond portfolio guard staat individuele TP-closes toe zolang de portfolio-exit zelf niet actief is; bij bereikt portfolio-doel behoudt de volledige portfolio-exit prioriteit.",
    ],
    now: [
      "PER_TRADE: individuele LONG/SHORT TP actief.",
      "PORTFOLIO: individuele LONG/SHORT TP actief én volledige portfolio-close op het ingestelde portfoliodoel.",
      "OFF: individuele en portfolio Take Profit uit.",
    ],
    before: "Portfolio mode schakelde de individuele pair Take Profit uit.",
    after: "Portfolio mode is additief: pair TP blijft werken en het portfolio-doel sluit daarnaast alles zodra dat doel wordt bereikt.",
    technicalDetails: [
      "Aangepast in web/components/aster-strategy2-maker.tsx, cloud_api/aster_multi_bb.py en cloud_api/aster_multi_bb_portfolio.py.",
      "Profit Lock Ladder behoudt zijn bestaande expliciete TP-suppressie; deze fix verandert die aparte strategie niet.",
      "Geen DCA-, Bollinger-, leverage-, slot- of Stoploss-regel is door deze release gewijzigd.",
    ],
    confidence: "confirmed",
  },

  {
    id: "v46-build-388-slot-capacity-release-history",
    version: "46",
    build: "388",
    releasedAt: "2026-09-21",
    title: "Portfolio Snapshot toont echte slotcapaciteit",
    newItems: [
      "Portfolio Snapshot toont nu per zijde zowel actieve posities als de ingestelde LONG/SHORT-capaciteit.",
      "De compacte status gebruikt dezelfde zichtbare Slot-overzicht-bron als Botinstellingen en behoudt de bestaande actieve-positiesbron als fallback.",
    ],
    problems: [
      "Na het verhogen van LONG-slots van 30 naar 35 bleef Portfolio Snapshot alleen 30L / 30S tonen.",
      "Daardoor leek de portefeuille visueel volledig bezet terwijl Botinstellingen correct 30 / 35 LONG en 5 vrije LONG-stoelen aangaf.",
    ],
    causes: [
      "De compacte Portfolio Snapshot las alleen actieve LONG/SHORT-aantallen uit de legacy Active Trades Index en kende de ingestelde zijde-capaciteit niet.",
    ],
    fixes: [
      "Portfolio Snapshot leest nu de actuele LONG- en SHORT-teller uit het bestaande Slot-overzicht, inclusief ingestelde capaciteit.",
      "De status toont bijvoorbeeld 30/35L / 30/30S zodat vrije capaciteit direct zichtbaar is.",
      "Als het Slot-overzicht tijdelijk nog niet beschikbaar is, blijft de bestaande actieve LONG/SHORT-weergave als veilige fallback functioneren.",
    ],
    now: [
      "Actieve positie-aantallen en ingestelde stoelcapaciteit zijn in Portfolio Snapshot niet langer met elkaar te verwarren.",
      "Deze wijziging raakt uitsluitend de webpresentatie; scanner-, Bollinger-, order-, DCA-, TP- en exchange-logica blijven ongewijzigd.",
    ],
    before: "Portfolio Snapshot toonde alleen 30L / 30S en kon daardoor volledig gevuld lijken terwijl 5 LONG-stoelen vrij waren.",
    after: "Portfolio Snapshot toont actieve/beoogde capaciteit per zijde, bijvoorbeeld 30/35L / 30/30S.",
    technicalDetails: [
      "Bron voor capaciteit: bestaand Botinstellingen Slot-overzicht, dat sinds Build 382 Aster exchange-truth voor bezetting gebruikt.",
      "Fallback blijft de bestaande Active Trades Index zodat de Snapshot niet leegvalt wanneer de instellingencomponent nog niet gemount is.",
      "Geen accountinstelling, positie, order of strategieparameter wordt door deze release gewijzigd.",
    ],
    confidence: "confirmed",
  },
  {
    id: "v46-build-387-profit-close-release-history",
    version: "46",
    build: "387",
    releasedAt: "2026-09-21",
    title: "Portfolio winstknoppen gelijkgetrokken + fixes zichtbaar",
    newItems: [
      "Alle productiefixes worden voortaan ook als afzonderlijke, zichtbare release-notitie in Versiegeschiedenis opgenomen.",
      "Deze release documenteert de live backendfix waardoor Portfolio Snapshot en Tradecentrum dezelfde Multi BB-winstposities herkennen.",
    ],
    problems: [
      "Tradecentrum kon bijvoorbeeld 5 winstposities en +$17,57 tonen, terwijl Portfolio Snapshot tegelijk Close Long/Short/All op 0 posities en US$ 0,00 zette.",
      "Daardoor gaf één scherm twee verschillende antwoorden over exact dezelfde open Aster-posities.",
    ],
    causes: [
      "De veilige Strategy-2 profit-close gebruikte legacy ownedLegs als ownershipbron, terwijl de actieve Multi BB-engine haar beheerde posities in multiBbPositions bijhoudt.",
      "De live Tradecentrum-lijst zag de Aster-posities wel, maar de profit-close preview verloor Multi BB-posities tijdens de ownershipfilter.",
    ],
    fixes: [
      "De Strategy-2 ownershipresolver neemt nu ook geldige bot-managed LONG/SHORT-legs uit multiBbPositions mee.",
      "De bestaande Strategy-2/Sniper scheiding blijft intact: deze wijziging maakt Sniper-posities niet sluitbaar via de Aster Multi BB-profitknoppen.",
      "Vlak vóór iedere daadwerkelijke profit-close wordt de Aster-positie opnieuw gelezen en moet de positie nog steeds aan de winstgrens voldoen.",
      "De volledige backendtestset, candidate-healthcheck en productiecontrole zijn vóór en na promotie geslaagd.",
    ],
    now: [
      "Portfolio Snapshot Close Long, Close Short en Close All herkennen dezelfde beheerde Multi BB-posities als Tradecentrum.",
      "Een winstpositie verdwijnt niet meer uit Portfolio Snapshot alleen omdat deze via Multi BB-runtimeownership in plaats van legacy ownedLegs wordt beheerd.",
      "Build 386 SNIPER Live Trading blijft volledig behouden; Build 387 voegt deze fixregistratie en zichtbare release-notitie toe.",
    ],
    before: "Tradecentrum en Portfolio Snapshot konden voor dezelfde Aster-accountpositie verschillende winst-aantallen tonen.",
    after: "Multi BB-posities worden in de veilige Strategy-2 profit-close correct als owned herkend, terwijl Sniper-isolatie behouden blijft.",
    technicalDetails: [
      "Backendfix commit: b2f20b6e924a8a71d8c2d7f3986c96d74daf4cf2.",
      "Live backendrevision na verificatie: tradementor-api-src-b2f20b6e-249023.",
      "Geen bestaande positie is door deze release automatisch gesloten; alleen herkenning, preview en expliciet bevestigde profit-close scope zijn gecorrigeerd.",
    ],
    confidence: "confirmed",
  },

  {
  id: "v46-build-386-sniper-live",
  version: "46",
  build: "386",
  releasedAt: "2026-09-21",
  title: "SNIPER Live Trading",
  newItems: [
    "Nieuw hoofdtabblad SNIPER tussen ASTER en NIEUWS met eigen Overzicht, Trades, Signalen, Prestaties en Instellingen.",
    "Sniper kan na expliciete live-bevestiging echte Aster USDT-perpetual orders plaatsen en beheren.",
    "Aster en Sniper delen portfolio/equity, available margin en account-risk, maar hebben volledig gescheiden scanners, trades, slots en normale close-acties.",
    "Een atomische symbol lock voorkomt dat Aster en Sniper ooit tegelijk dezelfde munt beheren, ongeacht LONG/SHORT-richting.",
  ],
  problems: [
    "De eerdere Sniper-build was alleen simulation-only en stond buiten de actuele productie-app.",
    "Zonder harde strategy ownership kon een Aster bulk-close theoretisch ook een Sniper-positie meenemen wanneer beide engines dezelfde exchange-accountdata gebruikten.",
    "Een gedeelde scanner/capaciteitsflow mocht nooit opnieuw leiden tot meerdere strategieën die dezelfde munt of extra stoelen claimen.",
  ],
  causes: [
    "De oude Aavansh Sniper-interface had bewust geen productie-execution backend.",
    "Aster exchange-position rows bevatten van zichzelf geen TradeMentor strategy-owner; ownership moet daarom vóór iedere entry intern en atomisch worden vastgelegd.",
  ],
  fixes: [
    "Sniper heeft een eigen live runtime, scannerstate, tradeledger, historie, settings en schedulerpad gekregen.",
    "Strategy-2 en Sniper gebruiken symbol-level ownership: ASTER.activeSymbols en SNIPER.activeSymbols mogen nooit overlappen.",
    "Aster Close Profits >= $0,50 selecteert alleen bewezen Aster-owned symbols; Sniper exits raken alleen bewezen Sniper trades.",
    "De algemene Close All blijft bewust accountbreed: eerst emergency lock en beide bots UIT, daarna alle posities sluiten en exchange-flat verifiëren.",
    "Pending/unknown orders blijven fail-closed en worden eerst via exchange-reconciliation hersteld voordat een nieuwe order is toegestaan.",
    "Een accountbrede execution coordinator voorkomt dat Aster en Sniper gelijktijdig dezelfde verouderde available margin reserveren.",
    "De eerste echte Sniper-activering is geblokkeerd achter een zeer kleine open/fill/close Aster-canary; de scanner wordt pas daarna ingeschakeld.",
    "Gesloten Sniper-trades gebruiken exchange-bevestigde realized PnL, fees en funding voor hun netto resultaat.",
  ],
  now: [
    "Sniper staat tussen Aster en Nieuws en toont uitsluitend eigen posities, signalen, historie en performance.",
    "Aster-posities worden niet als Sniper-trades getoond en Sniper-symbols worden niet als beheerbare Aster-posities weergegeven.",
    "De gedeelde portfolio- en available waarden blijven in beide strategieën zichtbaar, terwijl normaal positiebeheer volledig gescheiden blijft.",
  ],
  before: "Sniper bestond als aparte simulation-only prototypebuild en was niet bruikbaar voor echte orders in de actuele productie-app.",
  after: "Sniper is als tweede geïsoleerde live Aster-engine in V46 geïntegreerd, met symbol ownership, eigen tradebeheer en accountbrede noodstop.",
  technicalDetails: [
    "Primaire visuele referentie: https://chatgpt.com/s/m_6aab179ba6008191b3b874803a1508ab.",
    "Aanvullende goedgekeurde referenties: 3b80f501-69c7-424a-bb80-9aff04bb7594, 0cee1df2-8608-4a48-9e7d-1421d4ff3177, e6590034-d49b-485f-a581-53fc605b11ea, de872ec8-e8c9-4ffa-af9e-e35970c35c93, a1138afd-dd0f-46ec-be4e-eb7302ba181f, 25ca0d1c-4e95-473b-b1de-311e75a0f3f4, e8366e61-315b-4016-a02e-a23736fc59ea en 3548d2b7-c1d8-494b-b0c2-c588505a6b7c.",
    "Bestaande prototypebasis: aavansh-sniper-build372 / web/components/sniper-dashboard.tsx.",
    "Historische Sniper-replay modelleert fees, spread, slippage, next-bar latency en stop-first bij onzekere intrabar-volgorde; ontbrekende historische orderbook/orderflow-data wordt expliciet als beperking gemeld.",
    "Fault/recovery-tests dekken onder meer onzekere submissions, pending open/close recovery, timeout-exits, symbol overlap, strategy-scoped bulk close en accountbrede noodstop.",
    "De beperkte live canary is een harde runtime-gate bij de eerste live activering; de versiegeschiedenis wordt niet als bewijs van een reeds uitgevoerde canary gebruikt.",
  ],
  confidence: "confirmed",
},

  {
    id: "v46-build-385-aster-realtime-equity",
    version: "46",
    build: "385",
    releasedAt: "2026-09-21",
    title: "Aster portefeuillewaarde volgt realtime markprijzen",
    newItems: [
      "De Aster portefeuillewaarde beweegt nu mee met de bestaande realtime markprijs-feed in plaats van te wachten op de volgende volledige accountsnapshot.",
      "De bestaande realtime positie-PnL wordt direct doorvertaald naar de zichtbare equity.",
    ],
    problems: [
      "Na het herstellen van de Aster-data konden markprijzen en open PnL al live bewegen, terwijl de totale portefeuillewaarde nog op de laatste server-snapshot bleef staan.",
      "Daardoor kon de Aster-app tijdelijk een iets hogere of lagere accountwaarde tonen dan Webapp 46.",
    ],
    causes: [
      "De realtime reducer werkte positieprijzen en unrealized PnL bij, maar liet het top-level equity-veld ongewijzigd tot de volgende gesigneerde accountrefresh.",
    ],
    fixes: [
      "Realtime equity wordt voortaan berekend als bevestigde walletBalance plus de opnieuw berekende totale unrealized PnL.",
      "Als walletBalance tijdelijk ontbreekt, gebruikt de client alleen de bevestigde equity plus het verschil in unrealized PnL als veilige fallback.",
      "Available balance, positie-openingen/sluitingen en orderstate blijven bewust server-confirmed en worden niet door de browser verzonnen.",
    ],
    now: [
      "Bij normale marktbewegingen volgt de zichtbare Aster-equity de realtime markfeed in dezelfde 250 ms renderbatch als de positie-PnL.",
      "Volledige account- en ordertruth blijft periodiek door de Aster API worden bevestigd.",
    ],
    before: "De realtime stream veranderde markprijzen en positie-PnL, maar de totale equity bleef staan tot een latere accountsnapshot.",
    after: "Markprijs, open PnL en zichtbare equity bewegen samen; volledige accounttruth blijft door Aster bevestigd.",
    technicalDetails: [
      "Alleen web-presentatie/state-afleiding en regressietests gewijzigd; geen order-, DCA-, TP-, wallet- of backend-executionlogica aangepast.",
      "De browser wijzigt geen beschikbare marge op basis van een schatting; availableBalance blijft Aster API-truth.",
    ],
    confidence: "confirmed",
  },
  {
    id: "v46-build-384-portfolio-cycle",
    version: "46",
    build: "384",
    releasedAt: "2026-09-21",
    title: "Portfolio Cyclus zichtbaar in Portfolio Snapshot",
    newItems: [
      "Portfolio Snapshot heeft nu permanent een compact Portfolio Cyclus-vak in de bestaande vrije ruimte rechts van Profit sparen.",
      "Zonder actieve Portfolio Take Profit op portfoliowaarde toont het vak Niet ingesteld, Portfolio TP niet actief en Instellen.",
      "Met actieve Portfolio Take Profit op portfoliowaarde toont het vak live voortgang, resterend bedrag, resterend percentage en een duidelijke status.",
    ],
    problems: [
      "De Portfolio TP-cycle was functioneel aanwezig, maar de gebruiker kon in Portfolio Snapshot niet direct zien hoe ver de huidige cyclus van sluiting verwijderd was.",
      "Een zichtbaar cyclusnummer zonder duidelijke startbasis gaf onnodige verwarring.",
    ],
    causes: [
      "De compacte Portfolio Snapshot had nog geen vaste presentatiecomponent die de server-side Portfolio TP-cycle naar een duidelijke voortgangsstatus vertaalde.",
    ],
    fixes: [
      "Het bestaande lege derde vak naast Profit sparen is gevuld zonder de overige Portfolio Snapshot-layout te herschikken.",
      "De actieve state gebruikt de bestaande server-side Portfolio TP-cycledata voor basiswaarde, doelwaarde en actuele equity.",
      "De tegel toont geen cyclusnummer en valt buiten Portfolio-modus altijd terug op de nette Niet ingesteld-state.",
      "Klikken op het vak brengt de gebruiker naar de bestaande Portfolio Take Profit-instellingen.",
    ],
    now: [
      "Portfolio Cyclus is altijd zichtbaar op dezelfde vaste plek.",
      "Alleen Portfolio Take Profit in modus Portfolio activeert de live voortgangsweergave.",
      "De tegel verzint geen cyclusdata: zonder geldige server-cycle blijft de inactive state zichtbaar.",
    ],
    before: "De vrije ruimte rechts van Profit sparen gaf geen bruikbare status van de actieve Portfolio TP-cycle.",
    after: "Diezelfde bestaande ruimte toont nu compact of Portfolio TP niet is ingesteld, of hoe dicht de actieve Portfolio TP-cycle bij sluiten is.",
    technicalDetails: [
      "Visuele referentie inactive state: file_00000000192481f495e9311d4ed77933.",
      "Visuele referentie active state: file_00000000b78081f4a8a332da9a783f3b.",
      "De overige Portfolio Snapshot-cards, tradinglogica, DCA-logica, open posities en orders zijn niet gewijzigd.",
    ],
    confidence: "confirmed",
  },
  {
    id: "v46-build-383-fixed-position-size-isolation",
    version: "46",
    build: "383",
    releasedAt: "2026-09-21",
    title: "Vaste positieomvang raakt basisinstap niet meer",
    newItems: [
      "Instap LONG/SHORT · margin blijft altijd zichtbaar en behoudt exact de opgeslagen waarde.",
      "Vaste positieomvang gebruikt voortaan aparte LONG/SHORT positievelden in USDT.",
      "Een vaste positie moet expliciet worden ingevuld; margin wordt nooit meer automatisch met leverage vermenigvuldigd.",
    ],
    problems: [
      "Bij het inschakelen van Vaste positieomvang kon de webapp een oude margin van bijvoorbeeld 0,30 automatisch tonen als 6 USDT bij 20x.",
      "Daardoor leek een bestaande basisinstelling gewijzigd, terwijl 6 USDT notional een wezenlijk andere instelling is dan 0,30 USDT margin.",
    ],
    causes: [
      "De Build-380 UI gebruikte legacy entryNotionalUsd en als fallback margin × minimum leverage om notionalvelden vooraf te vullen.",
      "Hetzelfde LONG/SHORT invoervak wisselde bovendien tussen margin en positie, waardoor de twee onafhankelijke instellingen visueel als één waarde leken.",
    ],
    fixes: [
      "De leverage-vermenigvuldiging is volledig uit de UI-loadmigratie verwijderd.",
      "Margin- en notionalwaarden zijn nu afzonderlijke velden; het activeren van Vaste positieomvang overschrijft de marginvelden niet.",
      "In marginmodus worden bestaande notionalvelden niet opnieuw geschreven.",
      "Bij een lege vaste positie blokkeert opslaan/starten met een expliciete melding in plaats van een automatische omrekening.",
    ],
    now: [
      "0,30 margin blijft 0,30 margin, ongeacht of een markt 20x, 50x, 100x of 300x ondersteunt.",
      "Wie Vaste positieomvang wil gebruiken moet de gewenste positie-USDT apart en bewust invullen.",
      "DCA, Portfolio TP, Stoploss, leveragefilters en bestaande actieve posities worden door deze UI-fix niet aangepast.",
    ],
    before: "Vaste positieomvang kon automatisch afgeleide notionalwaarden tonen en opslaan op basis van margin × minimum leverage.",
    after: "Basis-margin en vaste positieomvang zijn strikt gescheiden; geen automatische conversie of overschrijving meer.",
    technicalDetails: [
      "Regressietests bewaken dat legacy marginwaarden nooit via minimum leverage in notional worden omgezet.",
      "De bestaande server-side execution mode blijft leidend; deze release verandert geen open posities of orders.",
    ],
    confidence: "confirmed",
  },

  {
    id: "v46-build-382-slot-truth",
    version: "46",
    build: "382",
    releasedAt: "2026-09-20",
    title: "Portfolio Cycle snapshot + juiste slotbezetting",
    newItems: [
      "Portfolio Snapshot toont het nieuwe Portfolio Cycle-vak uit de actuele Portfolio TP-cycle.",
      "Het Slot-overzicht in Botinstellingen gebruikt dezelfde actuele Aster-posities als Portfolio Snapshot.",
    ],
    problems: ["Slot-overzicht kon vrije LONG-stoelen tonen terwijl Aster al volledig bezet was."],
    causes: ["De balkjes gebruikten primair Strategy-2 ownership-state in plaats van actuele Aster-posities."],
    fixes: ["LONG, SHORT en totaal bezet/vrij gebruiken nu Aster exchange-truth met Strategy-2 als fallback."],
    now: ["30 LONG + 30 SHORT toont 30/30, 30/30, 60/60 en 0 vrij."],
    confidence: "confirmed",
  },
  {
    id: "v46-build-381-portfolio-tp-2",
    version: "46",
    build: "381",
    releasedAt: "2026-09-20",
    title: "Portfolio Take Profit 2.0",
    newItems: [
      "Portfolio Take Profit kan nu als percentage of als vast dollar-winstbedrag worden ingesteld.",
      "De gebruiker kiest de berekeningsbasis: Cycle start, een eenmalig vastgezette huidige waarde of een aangepaste basiswaarde.",
      "Reset cycle zet alleen de Portfolio TP-cycle start naar de actuele Aster-equity en verstuurt daarbij nul orders.",
      "Per trade, Portfolio en Uit tonen voortaan een duidelijke goudkleurige actieve state.",
    ],
    problems: [
      "Portfolio TP kon alleen procentueel worden ingesteld en rekende altijd vanaf de bestaande cycle start.",
      "De drie Take Profit-modusknoppen waren visueel te gelijk.",
    ],
    causes: [
      "De bestaande Portfolio TP-configuratie kende alleen portfolioTpPercent en cycleStartEquity.",
      "De compacte tabstyling gebruikte een subtiele statuskleur in plaats van een expliciete geselecteerde state.",
    ],
    fixes: [
      "Nieuwe persistente inputMode, value, baseMode en customBaseEquity toegevoegd met backward-compatible migratie.",
      "Huidige waarde wordt server-side één keer vastgezet per opgeslagen configuratie.",
      "Na een succesvolle Portfolio TP wordt de werkelijke post-close equity de nieuwe cycle start.",
    ],
    now: [
      "Portfolio TP ondersteunt %/$, drie basiskeuzes, veilige cycle reset en automatische post-close cycli.",
    ],
    confidence: "confirmed",
  },
  {
    id: "v46-build-380-fixed-position-size",
    version: "46",
    build: "380",
    releasedAt: "2026-09-20",
    title: "Vaste positieomvang als optionele instapmodus",
    newItems: [
      "Nieuwe schakelaar Vaste positieomvang: instapbedrag kan optioneel de werkelijke LONG/SHORT positie in USDT zijn in plaats van margin.",
      "LONG en SHORT bewaren ieder hun eigen positieomvang en de benodigde margin wordt per markt uit de werkelijk gekozen leverage afgeleid.",
    ],
    problems: ["Bij gelijke margin kregen markten met verschillende leverage verschillende werkelijke positieomvang."],
    causes: ["Build 379 stuurde de compacte LONG/SHORT instapvelden expliciet als entrySizingMode=margin."],
    fixes: ["Vaste positieomvang gebruikt de server-authoritative notional resolver terwijl het bestaande margin-gedrag beschikbaar blijft."],
    now: ["Gebruikers kunnen per account kiezen tussen vaste positieomvang en vaste margin."],
    confidence: "confirmed",
  },
  {
    id: "v46-build-379-compact-settings-maxlev-stoploss",
    version: "46",
    build: "379",
    releasedAt: "2026-09-20",
    title: "Compacte Botinstellingen met Maximum leverage en Stoploss",
    newItems: ["Compact premium Botinstellingen, optionele Maximum leverage en server-side Stoploss."],
    problems: ["Botinstellingen waren te ruim en leverage had nog geen optionele bovengrens."],
    causes: ["Bestaande UI en leverage-resolver waren voor de nieuwe compacte instellingen nog niet samengebracht."],
    fixes: ["Slot-overzicht, Maximum leverage en Stoploss zijn toegevoegd zonder bestaande posities te resetten."],
    now: ["Dit is de directe voorganger van build 380."],
    confidence: "confirmed",
  },
  {
    id: "v46-build-375-long-refill",
    version: "46",
    build: "375",
    releasedAt: "2026-09-19",
    title: "Vrije LONG-slots niet meer geblokkeerd door verborgen oude hedge-modus",
    newItems: ["Normale Botinstellingen wissen voortaan expliciet de oude verborgen asymmetric-pairmodus bij Opslaan, Simuleren en Starten."],
    problems: ["Een gebruiker kon vrije LONG-slots hebben terwijl geen LONG-instap plaatsvond, doordat een niet-zichtbare oude asymmetric hedge-instelling nog actief bleef."],
    causes: ["De normale Botinstellingen bouwden nieuwe settings bovenop alle eerder opgeslagen velden, waardoor asymmetricHedgeModeEnabled=true onzichtbaar behouden kon blijven."],
    fixes: ["Normale Multi DCA-instellingen sturen asymmetricHedgeModeEnabled nu expliciet als false.", "Regressietests bewaken dat de verborgen paired-entrymodus niet opnieuw wordt meegenomen door een normale save/start."],
    now: ["Vrije LONG- en SHORT-capaciteit wordt weer volgens de zichtbare instellingen behandeld."],
    before: "Een oude verborgen asymmetricHedgeModeEnabled=true kon vrije LONG-slots stil blokkeren.",
    after: "Normale Botinstellingen kunnen die verborgen paarmodus niet meer stilzwijgend vasthouden.",
    technicalDetails: ["Geen DCA-, TP-, order-, wallet-, WebSocket- of exchange-berekening gewijzigd."],
    confidence: "confirmed",
  },
  {
    id: "v46-build-374-hedge-card",
    version: "46",
    build: "374",
    releasedAt: "2026-09-19",
    title: "Hedge Dekking-kaart visueel vereenvoudigd",
    newItems: [
      "De Hedge Dekking-kaart sluit visueel rustiger aan op de overige Portfolio Snapshot-kaarten.",
    ],
    problems: [
      "De Hedge Dekking-kaart sprong te sterk uit en oude doelinformatie nam onnodig ruimte in.",
    ],
    causes: [
      "De compacte kaart toonde naast het actuele percentage ook een doelpercentage en statusbadge, met extra statuskleuren en glow.",
    ],
    fixes: [
      "Doelpercentage en doelstatusbadge zijn uit de compacte Hedge Dekking-kaart verwijderd.",
      "De kaart gebruikt nu een rustige donkere basis met subtiele goud/groene accenten zonder overdreven glow.",
      "De bestaande realtime hedge-dekkingberekening en het openen van de detailweergave zijn ongewijzigd gebleven.",
    ],
    now: [
      "De compacte kaart toont alleen het schild, HEDGE DEKKING en het actuele percentage.",
      "Waarden boven 100% blijven op mobiel en desktop binnen de kaart zonder overlap.",
    ],
    before: "De kaart toonde onder meer Doel 80% en een status zoals Boven doel en kreeg daardoor een opvallende alarmkaart-uitstraling.",
    after: "De kaart toont rustig het actuele hedgepercentage in dezelfde visuele hiërarchie als de omliggende Portfolio Snapshot-kaarten.",
    technicalDetails: [
      "Alleen webpresentatie, CSS, versieadministratie en regressietests gewijzigd; geen trading-, DCA-, order-, API-, WebSocket- of accountlogica.",
      "Visuele doelreferentie: file_00000000aa6c8210baf1b0ac8f94d18e.",
      "Responsive gedrag gecontroleerd via bestaande 640px- en 380px-layoutcontracten.",
    ],
    confidence: "confirmed",
  },
  {
    id: "v46-build-373-release-history",
    version: "46",
    build: "373",
    releasedAt: "2026-09-19",
    title: "Versiegeschiedenis en app-ontwikkellogboek",
    newItems: [
      "Mobiele versiegeschiedenis met nieuwste release bovenaan.",
      "Ongelezen badge bij de knop linksboven.",
      "Zoeken in oude releases, problemen en oplossingen.",
    ],
    problems: [
      "Gebruikers konden niet centraal terugvinden wat tussen appreleases veranderde en waarom.",
    ],
    causes: [
      "De bestaande versieknop controleerde alleen op updates; release-uitleg stond verspreid over commits, chats en technische notities.",
    ],
    fixes: [
      "Eén centrale releasebron toegevoegd met probleem, oorzaak, oplossing, voor/na en technische context per release.",
      "De linkerbovenhoek opent nu het mobiele ontwikkellogboek zonder de huidige pagina te verlaten.",
      "Buildnummer en releasehistorie zijn aan één releasecontract gekoppeld.",
    ],
    now: [
      "Nieuwe releases zijn direct herkenbaar en blijven later terugleesbaar.",
      "De gebruiker ziet hoeveel nieuwe builds nog niet zijn gelezen.",
      "Iedere volgende live webupdate moet een nieuw buildnummer én release-entry krijgen.",
    ],
    before: "De tekst CRYPTO BOT 2026 was statisch en de releasehistorie was niet vanuit de app bereikbaar.",
    after: "De linkerbovenhoek is een knop Versiegeschiedenis met een ongelezen teller en een volledig mobiel logboek.",
    technicalDetails: [
      "Alleen web-UI, versieadministratie en deploymentcontract gewijzigd.",
      "Leesstatus wordt lokaal en persistent in de PWA/browser opgeslagen; tradingstate wordt niet aangeraakt.",
      "Centrale bron: web/lib/release-history.ts.",
      "CI/deployment controleert buildnummer en release-entry vóór promotie.",
    ],
    confidence: "confirmed",
  },
  {
    id: "v46-build-372-baseline",
    version: "46",
    build: "372",
    releasedAt: "2026-09-19",
    title: "V46-productiebasis vóór centraal ontwikkellogboek",
    newItems: ["Bestaande V46 mobiele productie draaide als build 372."],
    problems: ["Er was nog geen centrale, gebruikersleesbare versiegeschiedenis."],
    causes: ["De zichtbare versieknop was uitsluitend bedoeld om een nieuwere appbuild te controleren."],
    fixes: [],
    now: ["Dit is de laatste bevestigde V46-basis vóór de introductie van het nieuwe logboek in build 373."],
    technicalDetails: ["Bevestigde live V46-buildweergave."],
    confidence: "confirmed",
  },
  {
    id: "v46-github-first-control-plane",
    version: "46",
    build: null,
    releasedAt: "2026-09-19T14:23:27+02:00",
    title: "GitHub-first ontwikkeling en deployment bewezen",
    newItems: ["Normale ontwikkeling, diagnose en deployment kunnen via GitHub zonder dagelijkse Cloud Workstation-koppeling."],
    problems: ["Ontwikkelwerk kon stilvallen wanneer een tijdelijke cloud/workstationverbinding wegviel."],
    causes: ["Dagelijkse ontwikkeling leunde te veel op rechtstreekse cloudtoegang."],
    fixes: ["GitHub Actions, WIF, candidate-checks, rollback en GitHub-only productie-diagnostiek ingericht en end-to-end bewezen."],
    now: ["Normale UI- en backendwijzigingen lopen via GitHub; Workstation is alleen nog break-glass."],
    technicalDetails: ["Bevestigd door GitHub-only deployment proof #154 en post-deploy health proof #155."],
    confidence: "confirmed",
  },
  {
    id: "smart-rescue-20260914",
    version: "46",
    build: null,
    releasedAt: "2026-09-14",
    title: "Smart Rescue DCA ontworpen en geïntegreerd",
    newItems: ["Smart Rescue DCA als aanvullende herstelmodus."],
    problems: ["Verliesposities hadden behoefte aan gecontroleerder herstel dan alleen vaste DCA-stappen."],
    causes: [],
    fixes: ["Herstellogica en bijbehorende instellingen als aparte, optionele module uitgewerkt."],
    now: ["De app kan een slimmere herstelroute aanbieden zonder bestaande modi te vervangen."],
    confidence: "reconstructed",
  },
  {
    id: "profit-lock-ladder-20260911",
    version: "46",
    build: null,
    releasedAt: "2026-09-11",
    title: "Profit Lock Ladder toegevoegd als optionele modus",
    newItems: ["Profit Lock Ladder met eigen aan/uit-keuze."],
    problems: ["Winstbescherming moest kunnen meegroeien zonder bestaande tradingmodi te vervangen."],
    causes: [],
    fixes: ["Nieuwe LONG-only modus ontworpen waarbij SHORT-posities uitsluitend als beschermingslaag dienen."],
    now: ["Gebruikers kunnen winstbescherming activeren zonder de bestaande standaardmodi kwijt te raken."],
    confidence: "reconstructed",
  },
  {
    id: "tradecentrum-20260903",
    version: "46",
    build: null,
    releasedAt: "2026-09-03",
    title: "Tradecentrum uitgebreid met winstsluiting en DCA-inzicht",
    newItems: ["Bulkactie voor winstgevende posities en extra sortering op DCA-activiteit."],
    problems: ["Kleine winsten vrijmaken kostte te veel losse handelingen en actieve posities waren lastiger te prioriteren."],
    causes: [],
    fixes: ["Tradecentrum uitgebreid met compacte winstactie en duidelijkere rangschikking."],
    now: ["Winstgevende posities en veelvuldig bijgezochte posities zijn sneller te herkennen en te beheren."],
    confidence: "reconstructed",
  },
  {
    id: "markets-risk-20260902",
    version: "46",
    build: null,
    releasedAt: "2026-09-02",
    title: "Markets-overzicht en liquidatierisico uitgebreid",
    newItems: ["Markets-overzicht, Bollinger-status en afzonderlijke liquidatierisico-indicatie."],
    problems: ["Marktselectie en liquidatieafstand waren niet snel genoeg in één oogopslag te beoordelen."],
    causes: [],
    fixes: ["Marktinformatie, sortering en risicometers als aparte visuele signalen toegevoegd."],
    now: ["Gebruikers zien marktcontext en liquidatiegevaar sneller naast de tradinginformatie."],
    confidence: "reconstructed",
  },
  {
    id: "manual-markets-20260831",
    version: "46",
    build: null,
    releasedAt: "2026-08-31",
    title: "Handmatige muntkeuze toegevoegd",
    newItems: ["Zelf munten kiezen met LONG/SHORT-richting per markt."],
    problems: ["Automatische selectie bood niet genoeg controle voor gerichte tests en specifieke markten."],
    causes: [],
    fixes: ["Een optionele handmatige marktselectie naast de bestaande automatische selectie toegevoegd."],
    now: ["Gebruikers kunnen specifieke munten en richting kiezen zonder de automatische flow te verwijderen."],
    confidence: "reconstructed",
  },
  {
    id: "android-239-build-207-github-migration",
    version: "2.39",
    build: "207",
    releasedAt: "2026-08-05T19:56:29+02:00",
    title: "Android-project naar GitHub en cloudmigratie gebracht",
    newItems: ["De bestaande TradeMentor Android-code werd als eerste GitHub-snapshot vastgelegd."],
    problems: ["De app bestond al lokaal, maar had nog geen centrale Git-geschiedenis voor de verdere cloudmigratie."],
    causes: ["Ontwikkeling vond vóór deze stap buiten de huidige GitHub-repository plaats."],
    fixes: ["Projectcode, Android-app, serveronderdelen en migratie-instructies in GitHub opgenomen."],
    now: ["Vanaf dit punt is de ontwikkelgeschiedenis rechtstreeks uit Git-commits te reconstrueren."],
    technicalDetails: [
      "Eerste bevestigde Git-commit: d8dae028f79cb831e6f23d209ba220b3f7c253e6.",
      "Snapshot bevatte Android versionName 2.39 en versionCode 207.",
    ],
    confidence: "confirmed",
  },
  {
    id: "local-v162-build80-20260802",
    version: "1.62",
    build: "80",
    releasedAt: "2026-08-02",
    title: "Vroege lokale app groeide naar circa build 80",
    newItems: ["De lokale Android-app was inmiddels uitgegroeid tot een veel bredere tradingapp."],
    problems: [],
    causes: [],
    fixes: [],
    now: ["Deze mijlpaal is uit pre-GitHub projecthistorie gereconstrueerd."],
    confidence: "reconstructed",
  },
  {
    id: "early-v001-20260729",
    version: "001",
    build: null,
    releasedAt: "2026-07-29",
    title: "Eerste werkende TradeMentor-builds",
    newItems: ["Eerste werkende appbouw en vroege releaseplanning."],
    problems: [],
    causes: [],
    fixes: ["Blueprint, projectstatus en changelogstructuur werden gebruikt om de ontwikkeling te ordenen."],
    now: ["Exacte afzonderlijke buildnummers uit deze pre-GitHub fase zijn niet allemaal hard te bewijzen."],
    confidence: "reconstructed",
  },
  {
    id: "project-start-20260728",
    version: "0.1.0-dev",
    build: "1",
    releasedAt: "2026-07-28",
    title: "Start van TradeMentor / Crypto Bot 2026",
    newItems: ["Eerste Android-project en basisarchitectuur opgezet."],
    problems: ["Er bestond nog geen gezamenlijke tradingapp."],
    causes: [],
    fixes: ["De eerste mobiele basis voor scanner, portfolio, strategie- en risicofuncties werd opgezet."],
    now: ["Dit is de oudste gereconstrueerde appmijlpaal in de huidige projecthistorie."],
    confidence: "reconstructed",
  },
];

function releaseTime(value: string) {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function buildNumber(entry: ReleaseHistoryEntry) {
  const parsed = Number(entry.build);
  return Number.isFinite(parsed) ? parsed : -1;
}

export function getReleaseHistory(): ReleaseHistoryEntry[] {
  const historical = [...HISTORICAL_RELEASES].sort((a, b) => {
    const dateDifference = releaseTime(b.releasedAt) - releaseTime(a.releasedAt);
    return dateDifference || buildNumber(b) - buildNumber(a);
  });
  return [CURRENT_RELEASE, ...historical];
}

export function releaseSearchText(entry: ReleaseHistoryEntry) {
  return [
    entry.version,
    entry.build || "",
    entry.title,
    ...entry.newItems,
    ...entry.problems,
    ...entry.causes,
    ...entry.fixes,
    ...entry.now,
    entry.before || "",
    entry.after || "",
    ...(entry.technicalDetails || []),
  ].join(" ").toLocaleLowerCase("nl-NL");
}
