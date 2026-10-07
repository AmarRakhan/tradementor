export const WEBAPP_VERSION = "46";
// Build 571: canonical Aster account truth, browser business-truth removal and cross-surface SSOT gates.
export const WEBAPP_BUILD_NUMBER = "571";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}