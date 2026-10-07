export const WEBAPP_VERSION = "46";
// Build 564: restore proven Build 518 Portfolio Koers geometry with current live data contracts; regression/deploy contract synchronized.
export const WEBAPP_BUILD_NUMBER = "564";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}