export const WEBAPP_VERSION = "46";
// Build 503: Actieve Trades 2.0 · basis-100 samengestelde marktindex, server-side en read-only.
export const WEBAPP_BUILD_NUMBER = "503";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}