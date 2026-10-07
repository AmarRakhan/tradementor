export const WEBAPP_VERSION = "46";
// Build 568: denser 15m Portfolio Koers + complete recent event history + margin-only entry details.
export const WEBAPP_BUILD_NUMBER = "568";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}