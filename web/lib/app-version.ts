export const WEBAPP_VERSION = "46";
// Build 552: keep confirmed Portfolio Koers zones through history gaps/cold starts and preserve the approved default viewport.
export const WEBAPP_BUILD_NUMBER = "552";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}