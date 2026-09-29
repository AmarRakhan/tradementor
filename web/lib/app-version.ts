export const WEBAPP_VERSION = "46";
// Build 470: Portfolio TP resetdoel is per gebruiker configureerbaar en gedeeld door legacy, STABLE V2 en BETA V3.
export const WEBAPP_BUILD_NUMBER = "470";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
