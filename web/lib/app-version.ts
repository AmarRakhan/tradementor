export const WEBAPP_VERSION = "46";
// Build 433: dagrendement opnieuw verankerd op dezelfde kalenderdag; cashflows blijven rendement-neutraal.
export const WEBAPP_BUILD_NUMBER = "433";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
