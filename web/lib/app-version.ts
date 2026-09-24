export const WEBAPP_VERSION = "46";
// Build 423: Aster-only Ultra Rivalry presentation skin; trading behavior unchanged.
export const WEBAPP_BUILD_NUMBER = "423";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
