export const WEBAPP_VERSION = "46";
// Build 638 (alleen web): nieuw thema Black Luxe onder Wallet → Kies jouw uitstraling — diep zwart, goud en felle accenten; standaard voor wie nog geen thema koos. Alleen kleuren: blokken, grafiek en stier/beer-filmpje ongewijzigd.
// Build 637 (alleen web): Portfolio Koers — omhoog en omlaag slepen werkt direct in de grafiek (prijsas niet eerst aanraken); links/rechts vegen houdt automatische schaal; alleen weergave.
// Build 636 (alleen web): Hoorn bij Portfolio TP klinkt tegelijk met de pushmelding als de app open is (ook in een ander tabblad); geen late hoorn meer bij later openen (venster 1 min). Bevat 635.
// Build 635 (alleen web): Portfolio Koers — slepen werkt direct na een tik, zones over de hele koershistorie, elk tijdframe start zoals 15m, verversen wacht op je vinger en houdt je zoom, knop "Nu" terug naar de actuele koers; alleen weergave.
// Build 634: hedge afbouwen wordt een grid — omlaag per stap een deel van de hedge verkopen (alleen met winst na fees), omhoog na N stappen terugkopen, vangnet na extra daling, kleine munten in minder grotere stappen (geen 100% dicht / 90% terug meer).
// Build 633 (alleen web): onderste navigatiebalk blijft op iPhone onderaan — verdwijnt tijdens typen en wordt na het sluiten van het toetsenbord opnieuw vastgezet; alleen weergave.
// Build 632: Hoorn bij Portfolio TP — zodra je portfolio take profit is behaald speelt de app één keer een hoorn af (alleen terwijl de app open is); schakelaar per apparaat en testknop in Pushmeldingen beheren. Bevat 631 (backend). Geen trading-wijzigingen.
// Build 629: hedge afbouwen — een gewijzigde instelling geldt direct voor alle lopende posities (geen vastgezette instellingen per cyclus meer); de ladder meet vanaf de eigen gemiddelde instapkoers van de hedge (de winst die je ziet), een hedge die al voorbij stappen is verkoopt die meteen en wordt na de laatste stap weer 100% gehedged; nooit terugkopen midden in een cyclus. Bevat 628: alles-sluiten-fase sluit nooit met verlies.
// Build 627 (alleen backend): alleen de Cloud Run-revisie met verkeer doet achtergrond-botwerk (tick, realtime, Spike, Auto Hedge, noodhedge); oude en kandidaat-revisies staan stand-by. Bij twijfel werkt hij door.
// Build 626: Auto Hedge voor LONG én SHORT — apart verliesbedrag per kant, hedge afbouwen gespiegeld met eigen instellingen per kant (standaard UIT), stap alleen met winst na fees, TP sluit beide samen en alleen netto groen (elk pair), Re-Hedge All voor beide kanten en ook halverwege de afbouw, nooit verkopen om recht te trekken, één positie per munt met Auto Hedge AAN, Hedge Mode-check, echte afbouworders.
// Build 625: Extreme Spike — minimale afstand tot het gemiddelde (%) per kant, naast de Bollinger-band; aanbevolen 2 %, instelbaar 0–20 %, met uitleg. Stopt instappen in rustige markten waar 4σ maar 0,5–1 % is.
// Build 623 (alleen backend): Spike-statistiek "verhandelbaar" werkt ook als de stoelen vol zijn — hefboomgrenzen eens per 6 uur in één bulk-aanvraag.
// Build 622 (alleen backend): Spike-doorschiet-meting — per spike en niveau de daling vóór TP 0,5/1/2 % en de maximale daling binnen 4 uur (basis voor de Auto Hedge-drempel).
// Build 621 (alleen backend): Spike-statistiek — per uur hoeveel munten 20,2 t/m 20,7+ raakten (LONG/SHORT, alle vs. verhandelbaar), in asterStrategy2/{uid}/spikeStats.
// Build 620 (alleen backend): ordergeschiedenis compact in het accountdocument (laatste 7 dagen, lopende cycli en nieuwste rij per munt); oudere rijen naar de subcollectie orderAttributionArchive. Document blijft ruim onder de Firestore-limiet.
// Build 619 (alleen backend): bot ging in DATA_HOLD doordat het accountdocument over de Firestore-limiet van 1 MiB groeide; verlopen instap-cooldowns (1022, ~285 kB) worden nu opgeruimd vóór elke scan.
// Build 618: Extreme Spike realtime werkt weer: Aster sloot de Spike-websocket met 3001 bij 200 munten in één aanmelding; nu in porties van 25. Status "Wacht op spike" in plaats van ORDERFOUT; Spike-verbindingen zichtbaar in systemStatus. Bouwt op live 616 (2f07a076), zonder Auto Hedge per gebruiker (617).
// Build 616: Spike-check gebruikt in productie de echte klok (614 telde het voorwerk vóór de scan nog niet mee; live nog 18/69 SPIKE_INVALID_LIVE_CANDLE).
// Build 615: terug van Extreme Spike naar Bollinger (of Geen filter) werkt weer: die keuze wordt direct opgeslagen en de Bollinger-kaart met schakelaar en tijdframes verschijnt meteen; alleen weergave/instellingen.
// Build 614: Extreme Spike keurde vrijwel elke munt af (SPIKE_INVALID_LIVE_CANDLE) doordat de scanner de begintijd van de tick gebruikte; nu een verse klok. Gekozen tijdframe licht ook op onder het app-thema.
// Build 613: Instapfilter springt niet meer terug na een paar seconden; een aangeklikte maar nog niet opgeslagen keuze blijft staan tot je opslaat; alleen weergave.
// Build 612: Extreme Spike — het gekozen tijdframe (LONG en SHORT) en de gekozen instapmodus lichten nu duidelijk op (volle groene knop met ✓); alleen weergave.
// Build 611: Extreme Spike 1.1 — instapfilter BB(20,k) "vanaf k" (20,2 t/m 20,7), exclusief met Bollinger; LONG/SHORT apart aan/uit met eigen tijdframe, Spike-TP en optionele trailing; realtime instap op de live prijs; na een Auto Hedge geldt de normale TP. Standaard UIT.
// Build 610: geen "HEDGED 100%" meer: deels-afgebouwd-label alleen bij echte afbouw (<100%) en alleen zolang Auto Hedge het pair vasthoudt (niet bij RECOVERY); alleen weergave.
// Build 609: label van een deels afgebouwde hedge heet nu "HEDGED 75%" (i.p.v. UNWIND); stap en TEST op de munt-kaart; alleen weergave.
// Build 608: SHORT Recovery 2.0 — Auto Hedge-SHORT in stappen afbouwen (AAN/UIT, totale daling, aantal stappen); te kleine stap → 100% sluiten en 90% van de LONG terug; leeg → weer 100% hedgen; LONG-TP sluit LONG+SHORT samen alleen bij netto plus. Start in testmodus (geen orders).
// Build 607: Portfolio Snapshot krijgt de rij Markt met de CoinMarketCap market cap 24u-verandering (groen/rood, + of −); alleen weergave, geen trading-wijzigingen.
// Build 606: Re-Hedge All 1.0 — één knop zet alle Recovery-LONG's via de bestaande Auto Hedge-route terug op 1:1 met hun actuele LONG; SHORT nooit groter dan LONG; geen andere trading- of strategiewijzigingen.
// Build 605: Close Profits 2.1 — de groene Close Profits-ronde staat op de server: onderbroken ronde hervatten zonder dubbele sluiting, onbekende uitkomst eerst bij Aster gecontroleerd; geen andere trading- of strategiewijzigingen.
// Build 604: Close Profits 2.0 — groene Close Profits-knop sluit alleen SHORTS met meer dan $0,50 open winst via de bestaande individuele Close-route; geen andere trading- of strategiewijzigingen.
// Build 601: retry incomplete verified TP marker details on bounded cadence; trading and accounting unchanged.
// Build 600: historical TP label and entry-margin read-only display correction; preserve all build 599 features.
// Build 599: central PWA and bull/bear cache synchronization; preserve all build 598 features.
// Canonical release metadata synchronized with release-history.ts for shared V46 deployment.
// Build 598: twee bestaande snapshot-tegels met hergebruik van de centrale Aster gesloten-tradehistorie en 3D-flip.
// Build 597: Slot-overzicht verplaatst onder Actieve zone; geen botinstellingen- of tradingwijzigingen.
// Build 596: bevestigd winstzakje onthouden tijdens sessie, direct heropenen, gedeelde in-flight aanvraag.
// Build 595: Historische LONG/SHORT-marker vult ontbrekende margin uitsluitend aan vanuit overeenkomende uitvoeringsgegevens.
// Build 594: Portfolio Koers markerdetails: geverifieerde winst en historische marge; koers blijft ongewijzigd.
// Build 593: global position cap in prijszone-stoelen persists across reload, with server save acknowledgment.
// Build 592: Aster-only automatic exchange refresh; Hyperliquid manual/history preserved.
// Build 591: wait for Firebase session before binding Snapshot request to account; no trading changes.
// Build 590: distinguish incomplete account data from Aster authorization or connection errors; no trading changes.
// Build 589: canonical price-zone cap and fail-closed personal settings loading; web-only, no order logic changes.
// Build 588: canonical account GET deduplication, auth-ready loading and non-live Snapshot safety.
// Build 587: direction-specific LONG/SHORT Bollinger entry timeframes; no scanner pipeline changes.
// Build 586: compact canonical next-free-position cards (LONG or SHORT), approved mockup.
// Build 585: five extra canonical zones above/below occupied range.
// Build 584: full-history Bollinger Bands aligned with canonical account candles.
// Build 583: vertical bidirectional scrolling across all canonical zone rows.
// Build 582: compact LONG distance display, no absolute target values.
// Build 581: read-only canonical zone price range diagnostics and next LONG capacity thresholds.
// Build 580: canonical server-authoritative Aster zoneState and one-source zone consumers.
// Build 579: device-independent Portfolio Koers LONG/SHORT/TP marker projection.
// Build 578: regression-gate sync for one-source zone truth.
// Build 577: one-source zone capacity truth and complete canonical price ranges.
// Build 576: final release-gate repair for compact Prijszone overview.
// Build 575: release-gate sync for the compact Prijszone overview.
 // Build 574: Prijszone Details compact five-column zone overview without horizontal scrolling.
export const WEBAPP_BUILD_NUMBER = "638";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}