export const WEBAPP_VERSION = "46";
// Build 461: Portfolio TP stoelreset beschikbaar in bestaande STABLE/V2-configurator.
export const WEBAPP_BUILD_NUMBER = "461";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
