export const WEBAPP_VERSION = "46";
// Build 515: Portfolio Koers entry-event detail · scroll + truthful ENTRY/DCA semantics.
export const WEBAPP_BUILD_NUMBER = "515";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}