export const WEBAPP_VERSION = "46";
// Build 569: Portfolio Koers data-truth audit, contiguous startup viewport, provenance-safe margins and confirmed-close reconciliation.
export const WEBAPP_BUILD_NUMBER = "569";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}