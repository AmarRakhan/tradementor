export const WEBAPP_VERSION = "46";
// Build 538: production backend accepts 0 LONG or 0 SHORT Zone Warriors seats.
export const WEBAPP_BUILD_NUMBER = "538";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}