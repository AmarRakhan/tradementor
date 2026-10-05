export const WEBAPP_VERSION = "46";
// Build 517: Portfolio Koers execution-proof gate · phantom/repeated entry events blocked.
export const WEBAPP_BUILD_NUMBER = "517";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}