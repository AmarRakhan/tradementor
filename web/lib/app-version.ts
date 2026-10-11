export const WEBAPP_VERSION = "46";
// Build 598: synchronize PWA cache namespaces and bull/bear media URLs with central release version.
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
export const WEBAPP_BUILD_NUMBER = "598";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}