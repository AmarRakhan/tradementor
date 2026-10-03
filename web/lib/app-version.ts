export const WEBAPP_VERSION = "46";
// Build 490: Auto Hedge-tegel volledig links uitgelijnd en tekst binnen kaart gehouden.
export const WEBAPP_BUILD_NUMBER = "490";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}