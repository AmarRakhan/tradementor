export const WEBAPP_VERSION = "46";
// Build 479: ASTER start compacter — strategie-banner weg en Portfolio Koers strakker op zichtbare high/low.
export const WEBAPP_BUILD_NUMBER = "479";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
