export const WEBAPP_VERSION = "46";
// Build 536: allow 0 LONG or 0 SHORT seats per Zone Warriors price zone.
export const WEBAPP_BUILD_NUMBER = "536";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}