export const WEBAPP_VERSION = "46";
// Build 467: Zone Warriors toont actieve-zone stoelen apart van alle-zone totalen; alleen 130 is globale cap.
export const WEBAPP_BUILD_NUMBER = "467";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
