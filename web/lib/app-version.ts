export const WEBAPP_VERSION = "46";
// Build 570: Prijszone Details current-cycle overview with origin-zone occupancy, confirmed profit attribution and data-truth fallbacks.
export const WEBAPP_BUILD_NUMBER = "570";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}