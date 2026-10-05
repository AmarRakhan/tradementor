export const WEBAPP_VERSION = "46";
// Build 509: Portfolio Koers visuele upgrade · duidelijke BB, zoneband, volledige S/R-ladder en dag-high/low.
export const WEBAPP_BUILD_NUMBER = "509";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}