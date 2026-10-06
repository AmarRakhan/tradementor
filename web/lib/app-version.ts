export const WEBAPP_VERSION = "46";
// Build 549: Portfolio Koers price zones/support-resistance are always-visible chart fundamentals.
export const WEBAPP_BUILD_NUMBER = "549";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}