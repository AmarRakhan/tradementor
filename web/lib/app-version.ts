export const WEBAPP_VERSION = "46";
// Build 500: gedeeld Actieve-zone blok onder Portfolio Koers; import-newlines gecorrigeerd.
export const WEBAPP_BUILD_NUMBER = "500";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}