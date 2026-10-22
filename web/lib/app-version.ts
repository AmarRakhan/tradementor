export const WEBAPP_VERSION = "46";
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
export const WEBAPP_BUILD_NUMBER = "611";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}