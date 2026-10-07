export const WEBAPP_VERSION = "46";
// Build 571: Price-zone current-cycle overview no longer gets stuck on loading when chart/event reads are slow or partially unavailable.
export const WEBAPP_BUILD_NUMBER = "571";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}