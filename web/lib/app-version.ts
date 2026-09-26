export const WEBAPP_VERSION = "46";
// Build 438: gemiddeld dagrendement herstelt betrouwbare historische dagen zonder stortingen/opnames als performance te tellen.
export const WEBAPP_BUILD_NUMBER = "438";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
