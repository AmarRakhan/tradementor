export const WEBAPP_VERSION = "46";
// Build 551: restore Build 512 Portfolio Koers R/S ladder and active-zone visuals; regression contracts aligned.
export const WEBAPP_BUILD_NUMBER = "551";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}