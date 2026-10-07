export const WEBAPP_VERSION = "46";
// Build 576: final release-gate repair for compact Prijszone overview.
// Build 575: release-gate sync for the compact Prijszone overview.
 // Build 574: Prijszone Details compact five-column zone overview without horizontal scrolling.
export const WEBAPP_BUILD_NUMBER = "576";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}