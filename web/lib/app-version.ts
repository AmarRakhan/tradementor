export const WEBAPP_VERSION = "46";
// Build 474: Portfolio Koers UI 4.1 marker-density — rustige referentieweergave met maximaal 3 TP, 2 LONG en 2 SHORT markers.
export const WEBAPP_BUILD_NUMBER = "474";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
