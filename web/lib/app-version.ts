export const WEBAPP_VERSION = "46";
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
export const WEBAPP_BUILD_NUMBER = "585";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}